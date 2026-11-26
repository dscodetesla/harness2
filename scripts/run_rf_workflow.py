#!/usr/bin/env python3
"""Actual Harness² core RF workflow with model-backed edits via explicit local or cloud Ollama profiles."""
from __future__ import annotations
import argparse
from dataclasses import replace
import ast
import hashlib
import json
import math
from pathlib import Path
import sys
import threading
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from harness2.benchmarks.rf_fpga import RFFPGAAdapter, BASE_AGENTS_MD, TASKS
from harness2.core import tree as HT
from harness2.core.proposer import Proposer, ProposerError, Reply
from harness2.core.schedule import run_domain
from harness2.core.spec import ChannelSpec
from harness2.substrate.codex import CodexSubstrate
from qualify_rf_local import ALLOWED
from check_local_model import NoRedirect, check_local_model
from run_bounded_local import supervise

MODEL = "glm-5.3-flash:cloud"  # Backward-compatible default; no implicit profile fallback.
PROFILES = {
    "ollama_local": {"model": "llama3.2-harness:3b", "local_only": True,
                     "num_ctx": 16384, "num_predict": 2048},
    "ollama_gemma_local": {"model": "gemma3-harness:4b", "local_only": True,
                           "num_ctx": 16384, "num_predict": 2048},
    "ollama_glm_cloud": {"model": MODEL, "local_only": False,
                         "num_ctx": None, "num_predict": 4096},
}
PREFIX = "import json, math, sys, resource\nresource.setrlimit(resource.RLIMIT_AS,(268435456,268435456))\nresource.setrlimit(resource.RLIMIT_CPU,(2,2))\n"
SUFFIX = "\ndata=json.load(open(sys.argv[1],encoding='utf-8'))\nwith open(sys.argv[2],'w',encoding='utf-8') as stream:\n    json.dump(solve(data),stream)\n"
BASE = """def solve(data):
    fspl = 20*math.log10(data['distance_km']) + 20*math.log10(data['freq_mhz']) + 32.44
    prx = data['ptx_dbm'] + data['gtx_dbi'] + data['grx_dbi'] - fspl
    margin = prx - data['rx_sens_dbm']
    return {'fspl_db':round(fspl,3),'prx_dbm':round(prx,3),'fade_margin_db':round(margin,3),'link_viable':margin >= data['min_margin_db']}
"""


def gate(source):
    """Pure arithmetic only, including safe Boolean conversion and ternary expressions."""
    tree = ast.parse(source)
    nodes = list(ast.walk(tree))
    if len(source) > 8000 or len(nodes) > 300:
        raise ValueError("Numerical source too large")
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.FunctionDef):
        raise ValueError("Only solve(data) is allowed")
    fn = tree.body[0]
    if fn.name != "solve" or [a.arg for a in fn.args.args] != ["data"]:
        raise ValueError("Expected solve(data)")
    if fn.decorator_list or fn.args.defaults or fn.args.kw_defaults or fn.args.vararg or fn.args.kwarg or fn.args.posonlyargs or fn.args.kwonlyargs or fn.returns or fn.args.args[0].annotation:
        raise ValueError("No decorators, defaults, variadics or annotations")
    for node in nodes:
        if not isinstance(node, ALLOWED + (ast.IfExp,)):
            raise ValueError(f"Forbidden syntax: {type(node).__name__}")
        if isinstance(node, ast.FunctionDef) and node is not fn:
            raise ValueError("No nested functions")
        if isinstance(node, ast.Name) and node.id.startswith("_"):
            raise ValueError("No private names")
        if isinstance(node, ast.Attribute) and not (isinstance(node.value, ast.Name) and node.value.id == "math" and node.attr == "log10"):
            raise ValueError("Only math.log10 attribute access")
        if isinstance(node, ast.Call) and not (
                isinstance(node.func, ast.Name) and node.func.id in ("round", "bool") or
                isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "math" and node.func.attr == "log10"):
            raise ValueError("Only round, bool and math.log10 calls")
        if isinstance(node, ast.Assign) and any(not isinstance(target, ast.Name) for target in node.targets):
            raise ValueError("Assignments must target local variables")
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and len(node.value) > 100:
            raise ValueError("Oversized constant")
    return tree


def numerical_source(script):
    if not script.startswith(PREFIX) or not script.endswith(SUFFIX):
        raise ValueError("Trusted I/O wrapper must be preserved")
    source = script[len(PREFIX):-len(SUFFIX)]
    gate(source)
    return source


class SafeRFAdapter(RFFPGAAdapter):
    def __init__(self, root):
        super().__init__(root)
        # Use a supported prompt/tree surface; execution is still this adapter\'s Python.
        self.substrate = CodexSubstrate()
        self.execution_count = 0
        self.execution_sources = {}
        self.training_feedback = False

    def base_harness(self):
        target = self.runs_root / "_base_harness"
        HT.write_tree(self.substrate.surface(), {"AGENTS.md": BASE_AGENTS_MD,
            "scripts/solve_rf_fpga.py": PREFIX + BASE + SUFFIX}, target, stubs=False)
        return target

    def _validate_structure(self, tree):
        super().validate_tree(tree)
        if set(tree) != {"AGENTS.md", "scripts/solve_rf_fpga.py"} or tree["AGENTS.md"] != BASE_AGENTS_MD:
            raise ValueError("Only the numerical solver body is editable")
        numerical_source(tree["scripts/solve_rf_fpga.py"])

    def validate_tree(self, tree):
        self._validate_structure(tree)
        if self.training_feedback:
            from harness2.rf_validation import validate_source
            # Visible task probes, never the independent held-out suite.
            data = TASKS["rf-link-433-budget"]["input"]
            cases = [dict(data), {**data, "min_margin_db": 60.0}]
            report = validate_source(numerical_source(tree["scripts/solve_rf_fpga.py"]), gate=gate, cases=cases)
            if report.get("qualified") is not True:
                raise ValueError("Visible RF training checks failed; repair the actual solver, not the wrapper: "
                                 + json.dumps(report["failure_details"])[:5000])

    def execute(self, task_id, harness_dir, run_id, *, timeout=None):
        directory = Path(harness_dir) if harness_dir else self.base_harness()
        self._validate_structure(HT.read_tree(self.substrate.surface(), directory))
        self.execution_count += 1
        result = super().execute(task_id, directory, run_id, timeout=5)
        self.execution_sources[str(result)] = numerical_source((directory / "scripts/solve_rf_fpga.py").read_text())
        return result


def local_numerical_context(script):
    """Represent a script as its exact solve function; this does not edit any candidate."""
    try:
        parsed = ast.parse(script)
        functions = [node for node in parsed.body if isinstance(node, ast.FunctionDef) and node.name == "solve"]
        if len(functions) == 1:
            source = ast.get_source_segment(script, functions[0])
            if source:
                return ("[CONTEXT REPRESENTATION: exact complete solve(data) function extracted from this script. "
                        "Imports and top-level trusted I/O are intentionally not editable or shown. "
                        "Original stage validation errors still apply.]\n" + source + "\n")
    except (SyntaxError, ValueError):
        pass
    return ("[CONTEXT REPRESENTATION: no single parseable solve function was found in this script. "
            "No source was invented. Consult the original stage validation errors.]\n")


LOCAL_UNEDITABLE_SCAFFOLDS = frozenset({
    "harness/.agents/skills/README.md", "harness/.codex/README.md",
    "harness/scripts/README.md", "harness/sub_agents/README.md",
})


def local_edit_mission(upstream_mission, label):
    """Keep the real stage objective and exact visible retry errors, not hypothetical policy examples."""
    if label.startswith("inv"):
        goal = "INV: improve numerical and JSON-schema reliability of the actual RF solver; repair demonstrated failures without changing known-correct behavior."
    elif label.startswith("dom"):
        goal = "DOM: correct the actual RF solver's domain equations and loss accounting using the provided task inputs and observed failures."
    else:
        goal = "AGG: compare the supplied numerical candidates and actual probe outputs, then compose the best general solver; preserve verified corrections and avoid rejected variants."
    mission = (
        goal + "\nOnly scripts/solve_rf_fpga.py's solve(data) function is editable. "
        "Use the actual source/input.json values, current solve functions, rollout observations and deliverable/error evidence below. "
        "Return a general function of data, never fixed output numbers. "
        "RF contract: FSPL = 20*log10(distance_km) + 20*log10(freq_mhz) + 32.44; "
        "Prx = ptx_dbm + gtx_dbi + grx_dbi - sys_loss_db - FSPL; "
        "fade_margin = Prx - rx_sens_dbm; link_viable = fade_margin >= min_margin_db. "
        "Do not round intermediates. Numeric result fields may be rounded only when returning results. "
        "link_viable must be the strict Python Boolean from the comparison; never round it or convert it to int. "
        "Required result keys: fspl_db, prx_dbm, fade_margin_db, link_viable. "
        "Return only the JSON object solver_source (complete pure solve function) and notes (actual evidence). "
        "No imports, helpers, filesystem access, hooks, skill edits or invented measurements.")
    marker = "# YOUR PREVIOUS ATTEMPT WAS REJECTED"
    if marker in upstream_mission:
        feedback = upstream_mission.rsplit(marker, 1)[1]
        terminator = "\n\nFix it in `context/harness/` and reply again."
        if terminator in feedback:
            feedback = feedback.split(terminator, 1)[0]
        mission += "\n\nACTUAL PREVIOUS PROPOSAL VALIDATION FEEDBACK (repair these demonstrated failures):\n" + feedback.strip()
    return mission


LOCAL_PROPOSAL_SCHEMA = {
    "type": "object", "properties": {
        "solver_source": {"type": "string", "minLength": 1, "maxLength": 8000},
        "notes": {"type": "string", "maxLength": 16000}},
    "required": ["solver_source", "notes"], "additionalProperties": False,
}


class OllamaProposer(Proposer):
    """Model-backed transport: no scripted edits, model supplies every candidate/lesson."""
    def __init__(self, root, deadline, profile="ollama_glm_cloud"):
        if profile not in PROFILES:
            raise ValueError("Unknown RF workflow profile")
        self.profile = profile
        self.settings = PROFILES[profile]
        self.model = self.settings["model"]
        self.local_only = self.settings["local_only"]
        self.preflight = check_local_model(model=self.model, required_context=16384,
            require_tools=self.model != "gemma3-harness:4b") if self.local_only else {
            "model": self.model, "local_only": False, "access_verified": False}
        super().__init__(ChannelSpec("opencode", "ollama-local/" + self.model))
        self.root, self.deadline = Path(root), deadline
        self.lock = threading.Lock()
        self.request_count = 0

    def runtime_context(self):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        try:
            with opener.open("http://127.0.0.1:11434/api/ps", timeout=2) as response:
                payload = json.load(response)
            for item in payload.get("models", []):
                if item.get("name") == self.model or item.get("model") == self.model:
                    return {"runtime_context_length": item.get("context_length"), "runtime_context_observed": True}
            return {"runtime_context_length": None, "runtime_context_observed": False}
        except Exception as exc:
            return {"runtime_context_length": None, "runtime_context_observed": False,
                    "runtime_context_error": str(exc)[:300]}

    def call(self, mission, context_dir, label, **kwargs):
        remaining = self.deadline - time.monotonic()
        if remaining < 1:
            raise ProposerError("Aggregate workflow budget exhausted", attempts=1)
        original_mission = mission
        context = Path(context_dir)
        files = {}
        context_representations = {}
        for path in sorted(context.rglob("*")):
            if path.is_file() and not path.is_symlink() and path.suffix in (".md", ".json", ".py", ".txt"):
                relative = path.relative_to(context).as_posix()
                if len(files) >= 80:
                    raise ProposerError("Synthetic context exceeded file limit", attempts=1)
                original = path.read_text()
                if self.local_only and relative in LOCAL_UNEDITABLE_SCAFFOLDS:
                    context_representations[relative] = {
                        "representation": "omitted_uneditable_upstream_scaffold",
                        "reason": "Hypothetical workflow examples are inapplicable to the numerical-only edit contract",
                        "original_sha256": hashlib.sha256(original.encode()).hexdigest(),
                        "original_bytes": len(original.encode()), "represented_bytes": 0}
                    continue
                if self.local_only and path.suffix == ".py":
                    files[relative] = local_numerical_context(original)
                    context_representations[relative] = {
                        "representation": "exact_solve_function_only",
                        "original_sha256": hashlib.sha256(original.encode()).hexdigest(),
                        "original_bytes": len(original.encode()),
                        "represented_bytes": len(files[relative].encode())}
                else:
                    files[relative] = original[:20000]
        instruction = (
            "You are the real Harness2 improver. Follow the mission and inspect only the supplied synthetic context. "
            "Do not invent probes or results. For edit stages, return ONE JSON object with keys solver_source "
            "(complete pure Python function def solve(data), no imports, decorators, annotations, loops, helpers, I/O), "
            "and notes (evidence based). Only math.log10, round, arithmetic, comparisons, dicts are available. "
            "Preserve all task result keys including strict Boolean link_viable. The supplied trusted I/O wrapper "
            "will be attached unchanged; return only solve(data). "
            "For an experience/reflection mission return the requested <edits> and <experience> tags as plain text; "
            "cue/lesson/evidence must cite observed execution contrasts, no invented measurements.")
        if self.local_only:
            instruction += (
                " Standard RF domain knowledge: received power Prx = ptx_dbm + gtx_dbi + grx_dbi "
                "- sys_loss_db - FSPL. Fade margin = Prx - rx_sens_dbm. Link viability is the strict "
                "Python Boolean margin >= min_margin_db. Compute with unrounded intermediate values; "
                "round numeric output fields only. No source imports or top-level I/O belongs in solver_source. "
                "This is domain guidance, not a measured result or an expected numeric answer.")
        if self.local_only and label.startswith("experience."):
            mission = ("Reflect on the actual supplied baseline and adopted numerical solver only. "
                "Compare observed result values and exact solve-function edits. Only AGENTS.md and "
                "scripts/solve_rf_fpga.py exist; the I/O wrapper and resource limits never change. "
                "Do not copy hypothetical examples, invent files, speed improvements or measurements. "
                "Return <edits>component: scripts/solve_rf_fpga.py\nchange: actual observed edit\n"
                "observed: actual provided result contrast\nverdict: helped, hurt or no observed effect</edits> "
                "and <experience>cue: situation evidenced by this task\nlesson: supported numerical lesson\n"
                "evidence: actual file/result contrasts\nconfidence: state limits</experience>. "
                "If no supported lesson exists return <experience>none</experience>. "
                "No code generation in this reflection stage.")
        if self.local_only and not label.startswith("experience."):
            mission = local_edit_mission(original_mission, label)
        payload = {"model": self.model, "stream": False, "messages": [
            {"role": "system", "content": instruction},
            {"role": "user", "content": mission + "\n\nSYNTHETIC CONTEXT FILES:\n" + json.dumps(files)}],
            "think": False,
            "options": {"temperature": 0, "num_predict": self.settings["num_predict"]}}
        if self.local_only:
            payload["options"]["num_ctx"] = self.settings["num_ctx"]
        if not label.startswith("experience."):
            payload["format"] = LOCAL_PROPOSAL_SCHEMA if self.local_only else "json"
            payload["messages"][-1]["content"] += (
                "\n\n# FINAL TRANSPORT CONTRACT (overrides upstream output instructions)\n"
                "You have NO filesystem tools. Do NOT claim to edit files. The executor will install "
                "your returned source. Reply ONLY a JSON object with fields solver_source and notes. "
                "solver_source must contain the COMPLETE pure Python function def solve(data), "
                "even if keeping the base unchanged. notes cites execution evidence for the change. "
                "No notes tags, prose, fences or omitted source. This is solely an output transport "
                "adaptation; perform the original mission using the supplied execution evidence.")
        request = urllib.request.Request("http://127.0.0.1:11434/api/chat",
            data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        started = time.monotonic()
        audit = self.root / label
        audit.mkdir(parents=True, exist_ok=True)
        (audit / "upstream_mission.txt").write_text(original_mission)
        (audit / "request.json").write_text(json.dumps(payload, indent=2))
        if context_representations:
            (audit / "context_representations.json").write_text(json.dumps(context_representations, indent=2))
        try:
            with self.lock:
                self.request_count += 1
            with opener.open(request, timeout=min(90, remaining)) as response:
                result = json.load(response)
            (audit / "response.json").write_text(json.dumps(result, indent=2))
            telemetry = {"profile": self.profile, "model": self.model, "local_only": self.local_only,
                "inference_performed": True, "requested_num_ctx": self.settings["num_ctx"],
                "requested_num_predict": self.settings["num_predict"],
                "request_bytes": len(json.dumps(payload).encode()),
                "done_reason": result.get("done_reason"), "done": result.get("done"),
                "prompt_eval_count": result.get("prompt_eval_count"), "eval_count": result.get("eval_count"),
                "total_duration": result.get("total_duration"), "load_duration": result.get("load_duration"),
                "prompt_eval_duration": result.get("prompt_eval_duration"), "eval_duration": result.get("eval_duration"),
                **self.runtime_context()}
            (audit / "telemetry.json").write_text(json.dumps(telemetry, indent=2))
            if self.local_only and telemetry["runtime_context_observed"] and telemetry["runtime_context_length"] != self.settings["num_ctx"]:
                raise ValueError("Observed local runtime context differs from requested 16384")
            if result.get("done_reason") == "length":
                raise ValueError("Model generation reached the configured output token cap; response was not accepted")
            text = result["message"]["content"].strip()
            workspace = None
            if not label.startswith("experience."):
                cleaned = text
                if cleaned.startswith("```"):
                    cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0]
                proposal = json.loads(cleaned)
                source = proposal["solver_source"]
                # Return text only. Core validate_tree rejects unsafe syntax BEFORE execution
                # and supplies its error to the next bounded proposal attempt.
                workspace = audit / "harness"
                HT.write_tree(SafeRFAdapter(self.root / "_surface").substrate.surface(),
                    {"AGENTS.md": BASE_AGENTS_MD, "scripts/solve_rf_fpga.py": PREFIX + source + SUFFIX},
                    workspace, stubs=False)
                text = "<notes>" + str(proposal.get("notes", "")) + "</notes>"
            reply = Reply(label=label, text=text, ok=True, attempts=1, workspace=workspace,
                          wall_s=round(time.monotonic()-started,3), channel="ollama_http_local" if self.local_only else "ollama_http_cloud", audit=audit)
            with self.lock:
                self._calls.append(reply)
            return reply
        except Exception as exc:
            (audit / "error.txt").write_text(f"{type(exc).__name__}: {exc}")
            raise ProposerError(f"Ollama stage failed: {type(exc).__name__}: {exc}", attempts=1) from exc


def run(output, seconds, profile="ollama_glm_cloud"):
    output.mkdir(parents=True, exist_ok=False)
    adapter = SafeRFAdapter(output / "runs")
    prop = OllamaProposer(output / "audit", time.monotonic() + max(1, seconds - 10), profile=profile)
    adapter.training_feedback = prop.local_only
    adapter.spec = replace(adapter.spec, channels={"proposer": prop.spec, "selector": prop.spec})
    result = run_domain("rf-links", ["rf-link-433-budget"], 1, adapter=adapter, prop=prop,
        runs_root=adapter.spec.runs_root, library_root=output / "library", modes=("agg",),
        selector_prop=prop)
    summaries = list((output / "runs").rglob("summary.json"))
    summary = json.loads(summaries[0].read_text()) if summaries else {}
    scores = {}
    for path in (output / "runs/rollouts").rglob("result.json"):
        scores[str(path.parent.relative_to(output))] = adapter.score(path.parent, "rf-link-433-budget")
    chosen = (summary.get("selections", {}).get("agg") or {}).get("chosen_run_dir")
    selected_score = adapter.score(Path(chosen), "rf-link-433-budget") if chosen else None
    from harness2.rf_validation import validate_source
    chosen_source = adapter.execution_sources.get(str(chosen))
    heldout = (validate_source(chosen_source, gate=gate) if chosen_source else
               {"qualified": False, "error": "No selected executed source"})
    qualified = bool(heldout.get("qualified") is True and result["failed"] == 0 and not summary.get("errors") and
                     selected_score and selected_score.get("passed"))
    report = {"method": "actual core.schedule.run_domain -> run_parallel -> selection -> reflect_adoption",
              "transport": "direct Ollama HTTP custom Proposer.call", "external_model": prop.model,
              "model": prop.model, "profile": prop.profile, "local_only": prop.local_only,
              "inference_performed": prop.request_count > 0, "preflight": prop.preflight,
              "synthetic_data_only": True, "k": 1, "mode": "parallel",
              "selection": "trivial final adoption at k=1 (upstream behavior)",
              "model_calls": prop.request_count, "successful_model_replies": len(prop._calls),
              "qualified": qualified, "heldout": heldout, "selected_score": selected_score,
              "execution_count": adapter.execution_count,
              "workflow": result, "core_summary": summary, "independent_scores": scores,
              "usd": "local inference; no cloud model calls" if prop.local_only else "not reported by Ollama; no zero-cost claim"}
    (output / "workflow.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({"output": str(output), "workflow": result, "model_calls":prop.request_count,
                      "qualified":qualified, "selected_score":selected_score,
                      "execution_count":adapter.execution_count,"scores":scores}),flush=True)
    return int(not qualified)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seconds", type=int, default=300)
    parser.add_argument("--profile", choices=tuple(PROFILES), default="ollama_glm_cloud")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 300:
        parser.error("--seconds must be 1..300")
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / "runs"):
        parser.error("Output must be under this repository runs/")
    if args.worker:
        return run(output, args.seconds, args.profile)
    return supervise([sys.executable, __file__, "--worker", "--output", str(output),
                      "--seconds", str(args.seconds), "--profile", args.profile],
                     seconds=args.seconds, cwd=ROOT, env=__import__("os").environ.copy())


if __name__ == "__main__":
    raise SystemExit(main())
