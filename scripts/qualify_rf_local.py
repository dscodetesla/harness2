#!/usr/bin/env python3
"""One local model-generated numerical RF solver, AST-gated before adapter execution."""
import argparse
import ast
import json
from pathlib import Path
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from harness2.benchmarks.rf_fpga import BASE_AGENTS_MD, RFFPGAAdapter, TASKS
from check_local_model import MODEL, NoRedirect, check_local_model

ALLOWED = (ast.Module, ast.FunctionDef, ast.arguments, ast.arg, ast.Assign, ast.Return,
           ast.Dict, ast.Subscript, ast.Constant, ast.BinOp, ast.Add, ast.Sub, ast.Mult,
           ast.Div, ast.UnaryOp, ast.USub, ast.UAdd, ast.Call, ast.Attribute, ast.Name,
           ast.Load, ast.Store, ast.Compare, ast.GtE, ast.Gt, ast.Lt, ast.LtE, ast.Eq)


def gate(source):
    tree = ast.parse(source)
    nodes = list(ast.walk(tree))
    if len(source) > 8000 or len(nodes) > 300:
        raise ValueError("Candidate exceeds numerical script limits")
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.FunctionDef):
        raise ValueError("Candidate must contain only def solve(data)")
    fn = tree.body[0]
    if fn.name != "solve" or [a.arg for a in fn.args.args] != ["data"]:
        raise ValueError("Expected solve(data)")
    if fn.decorator_list or fn.args.defaults or fn.args.kw_defaults or fn.args.vararg or fn.args.kwarg or fn.args.posonlyargs or fn.args.kwonlyargs:
        raise ValueError("No decorators/defaults/variadic arguments")
    if fn.returns or fn.args.args[0].annotation:
        raise ValueError("No annotations")
    for node in nodes:
        if not isinstance(node, ALLOWED):
            raise ValueError(f"Forbidden syntax: {type(node).__name__}")
        if isinstance(node, ast.FunctionDef) and node is not fn:
            raise ValueError("No nested functions")
        if isinstance(node, ast.Name) and (node.id.startswith("_") or node.id in ("eval", "exec", "open", "compile", "globals")):
            raise ValueError("Forbidden name")
        if isinstance(node, ast.Attribute) and not (
                isinstance(node.value, ast.Name) and node.value.id == "math" and node.attr == "log10"):
            raise ValueError("Only math.log10 attribute access permitted")
        if isinstance(node, ast.Call) and not (
                isinstance(node.func, ast.Name) and node.func.id == "round" or
                isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "math" and node.func.attr == "log10"):
            raise ValueError("Only round/math.log10 calls permitted")
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and len(node.value) > 100:
            raise ValueError("Oversized constant")
    return tree


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--retry-once", action="store_true", help="one correction for Boolean schema")
    args = parser.parse_args()
    evidence = check_local_model()
    root = ROOT / "runs/rf-local-qualification"
    if args.retry_once:
        root = root / "retry-1"
    if root.exists():
        raise SystemExit("Output exists; preserve prior evidence before another qualification")
    root.mkdir(parents=True)
    adapter = RFFPGAAdapter(root / "adapter")
    task = "rf-link-433-budget"
    baseline = adapter.execute(task, None, "baseline", timeout=5)
    baseline_score = adapter.score(baseline, task)
    prompt = (
        "Return ONLY Python source with one function def solve(data): returning a dict. "
        "No imports, markdown, file access, loops, helper functions, annotations or explanations. "
        "Available: math.log10 and round. Use assignments then return dict. "
        "Compute FSPL=20*log10(distance_km)+20*log10(freq_mhz)+32.44; "
        "prx=ptx_dbm+gtx_dbi+grx_dbi-sys_loss_db-FSPL; "
        "fade_margin=prx-rx_sens_dbm; link_viable=fade_margin>=min_margin_db. "
        "Round the three numeric results to 3 decimals. Keys: fspl_db, prx_dbm, fade_margin_db, link_viable. "
        "Read every value from data using the given keys. Example input: " +
        json.dumps(TASKS[task]["input"]))
    if args.retry_once:
        prompt += (" Correction from previous candidate: link_viable MUST be a Python bool. "
                   "Set link_viable = fade_margin_db >= data[\'min_margin_db\']; "
                   "never apply round() to a comparison or to link_viable.")
    (root / "prompt.txt").write_text(prompt)
    payload = {"model": MODEL, "stream": False, "messages": [{"role": "user", "content": prompt}],
               "options": {"num_ctx": 16384, "num_predict": 768, "temperature": 0}, "keep_alive": "5m"}
    request = urllib.request.Request("http://127.0.0.1:11434/api/chat",
        data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    start = time.monotonic()
    summary = {"scope": "single model candidate qualification; not Harness2 Propose-Probe-Compose",
               "model_evidence": evidence, "baseline": baseline_score,
               "model_inference_performed": True, "inference_calls": 1,
               "prompt_supplied_formulas": True}
    try:
        with opener.open(request, timeout=180) as response:
            result = json.load(response)
        (root / "response.json").write_text(json.dumps(result, indent=2))
        source = result["message"]["content"].strip()
        if source.startswith("```"):
            source = source.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        (root / "candidate.py").write_text(source + "\n")
        gate(source)
        summary["ast_gate"] = "passed"
        # Reviewed trusted I/O wrapper; only the gated numerical function is model-generated.
        harness = root / "candidate-harness"
        (harness / "scripts").mkdir(parents=True)
        (harness / "AGENTS.md").write_text(BASE_AGENTS_MD)
        wrapper = ("import json, math, sys, resource\n" +
                   "resource.setrlimit(resource.RLIMIT_AS, (268435456, 268435456))\n" +
                   "resource.setrlimit(resource.RLIMIT_CPU, (2, 2))\n" + source + "\n" +
                   "data = json.load(open(sys.argv[1], encoding='utf-8'))\n" +
                   "result = solve(data)\n" +
                   "with open(sys.argv[2], 'w', encoding='utf-8') as stream:\n" +
                   "    json.dump(result, stream)\n")
        (harness / "scripts/solve_rf_fpga.py").write_text(wrapper)
        candidate = adapter.execute(task, harness, "model-candidate", timeout=5)
        summary["candidate"] = adapter.score(candidate, task)
        got = json.loads((candidate / "result.json").read_text())
        summary["schema_passed"] = type(got.get("link_viable")) is bool
        summary["candidate"]["passed"] = (summary["candidate"]["passed"] and summary["schema_passed"])
    except Exception as exc:
        summary["error"] = f"{type(exc).__name__}: {exc}"
    summary["wall_seconds"] = round(time.monotonic() - start, 3)
    (root / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return 0 if summary.get("candidate", {}).get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
