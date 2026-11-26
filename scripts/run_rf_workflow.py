#!/usr/bin/env python3
"""Actual Harness² core RF workflow with model-backed edits via configured Ollama Cloud."""
from __future__ import annotations
import argparse
import ast
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
from harness2.benchmarks.rf_fpga import RFFPGAAdapter, BASE_AGENTS_MD
from harness2.core import tree as HT
from harness2.core.proposer import Proposer, ProposerError, Reply
from harness2.core.schedule import run_domain
from harness2.core.spec import ChannelSpec
from harness2.substrate.codex import CodexSubstrate
from qualify_rf_local import ALLOWED
from check_local_model import NoRedirect
from run_bounded_local import supervise

MODEL = "glm-5.3-flash:cloud"
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

    def base_harness(self):
        target = self.runs_root / "_base_harness"
        HT.write_tree(self.substrate.surface(), {"AGENTS.md": BASE_AGENTS_MD,
            "scripts/solve_rf_fpga.py": PREFIX + BASE + SUFFIX}, target, stubs=False)
        return target

    def validate_tree(self, tree):
        super().validate_tree(tree)
        if set(tree) != {"AGENTS.md", "scripts/solve_rf_fpga.py"} or tree["AGENTS.md"] != BASE_AGENTS_MD:
            raise ValueError("Only the numerical solver body is editable")
        numerical_source(tree["scripts/solve_rf_fpga.py"])

    def execute(self, task_id, harness_dir, run_id, *, timeout=None):
        directory = Path(harness_dir) if harness_dir else self.base_harness()
        self.validate_tree(HT.read_tree(self.substrate.surface(), directory))
        self.execution_count += 1
        return super().execute(task_id, directory, run_id, timeout=5)


class OllamaProposer(Proposer):
    """Model-backed transport: no scripted edits, model supplies every candidate/lesson."""
    def __init__(self, root, deadline):
        super().__init__(ChannelSpec("opencode", "ollama-local/" + MODEL))
        self.root, self.deadline = Path(root), deadline
        self.lock = threading.Lock()
        self.request_count = 0

    def call(self, mission, context_dir, label, **kwargs):
        remaining = self.deadline - time.monotonic()
        if remaining < 1:
            raise ProposerError("Aggregate workflow budget exhausted", attempts=1)
        context = Path(context_dir)
        files = {}
        for path in sorted(context.rglob("*")):
            if path.is_file() and not path.is_symlink() and path.suffix in (".md", ".json", ".py", ".txt"):
                relative = path.relative_to(context).as_posix()
                if len(files) >= 80:
                    raise ProposerError("Synthetic context exceeded file limit", attempts=1)
                files[relative] = path.read_text()[:20000]
        instruction = (
            "You are the real Harness2 improver. Follow the mission and inspect only the supplied synthetic context. "
            "Do not invent probes or results. For edit stages, return ONE JSON object with keys solver_source "
            "(complete pure Python function def solve(data), no imports, decorators, annotations, loops, helpers, I/O), "
            "and notes (evidence based). Only math.log10, round, arithmetic, comparisons, dicts are available. "
            "Preserve all task result keys including strict Boolean link_viable. The supplied trusted I/O wrapper "
            "will be attached unchanged; return only solve(data). "
            "For an experience/reflection mission return the requested <edits> and <experience> tags as plain text; "
            "cue/lesson/evidence must cite observed execution contrasts, no invented measurements.")
        payload = {"model": MODEL, "stream": False, "messages": [
            {"role": "system", "content": instruction},
            {"role": "user", "content": mission + "\n\nSYNTHETIC CONTEXT FILES:\n" + json.dumps(files)}],
            "think": False,
            "options": {"temperature": 0, "num_predict": 4096}}
        if not label.startswith("experience."):
            payload["format"] = "json"
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
        (audit / "request.json").write_text(json.dumps(payload, indent=2))
        try:
            with self.lock:
                self.request_count += 1
            with opener.open(request, timeout=min(90, remaining)) as response:
                result = json.load(response)
            (audit / "response.json").write_text(json.dumps(result, indent=2))
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
                          wall_s=round(time.monotonic()-started,3), channel="ollama_http_cloud", audit=audit)
            with self.lock:
                self._calls.append(reply)
            return reply
        except Exception as exc:
            (audit / "error.txt").write_text(f"{type(exc).__name__}: {exc}")
            raise ProposerError(f"Ollama stage failed: {type(exc).__name__}: {exc}", attempts=1) from exc


def run(output, seconds):
    output.mkdir(parents=True, exist_ok=False)
    adapter = SafeRFAdapter(output / "runs")
    prop = OllamaProposer(output / "audit", time.monotonic() + max(1, seconds - 10))
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
    qualified = bool(result["failed"] == 0 and not summary.get("errors") and
                     selected_score and selected_score.get("passed"))
    report = {"method": "actual core.schedule.run_domain -> run_parallel -> selection -> reflect_adoption",
              "transport": "direct Ollama HTTP custom Proposer.call", "external_model": MODEL,
              "synthetic_data_only": True, "k": 1, "mode": "parallel",
              "selection": "trivial final adoption at k=1 (upstream behavior)",
              "model_calls": prop.request_count, "successful_model_replies": len(prop._calls),
              "qualified": qualified, "selected_score": selected_score,
              "execution_count": adapter.execution_count,
              "workflow": result, "core_summary": summary, "independent_scores": scores,
              "usd": "not reported by Ollama; no zero-cost claim"}
    (output / "workflow.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({"output": str(output), "workflow": result, "model_calls":prop.request_count,
                      "qualified":qualified, "selected_score":selected_score,
                      "execution_count":adapter.execution_count,"scores":scores}),flush=True)
    return int(not qualified)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seconds", type=int, default=300)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 300:
        parser.error("--seconds must be 1..300")
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / "runs"):
        parser.error("Output must be under this repository runs/")
    if args.worker:
        return run(output, args.seconds)
    return supervise([sys.executable, __file__, "--worker", "--output", str(output),
                      "--seconds", str(args.seconds)],
                     seconds=args.seconds, cwd=ROOT, env=__import__("os").environ.copy())


if __name__ == "__main__":
    raise SystemExit(main())
