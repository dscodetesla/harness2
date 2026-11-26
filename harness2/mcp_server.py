"""Local stdio MCP adapter. Bounded named-profile Harness2 workflow jobs."""
from __future__ import annotations

import argparse
import fcntl
import importlib.metadata
import json
import os
from pathlib import Path
import re
import runpy
import signal
import subprocess
import sys
import time
import threading
import uuid
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUNS = Path(os.environ.get("HARNESS2_MCP_RUNS_DIR", ROOT / "runs" / "mcp")).resolve()
_PROCESSES: dict[str, subprocess.Popen] = {}


def _directory(run_id: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{32}", run_id):
        raise ValueError("run_id must be the ID returned by a harness2 start tool")
    return RUNS / run_id


def _read(run_id: str) -> dict[str, Any]:
    p = _directory(run_id) / "job.json"
    if not p.is_file():
        raise ValueError("Unknown run_id")
    return json.loads(p.read_text())


def _write(run_id: str, value: dict) -> None:
    directory = _directory(run_id)
    temporary = directory / f"job.{uuid.uuid4().hex}.tmp"
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(directory / "job.json")


def _identity(pid: int) -> tuple[str, str]:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
        parts = stat[stat.rfind(")") + 2:].split()
        if parts[0] == "Z":
            return "", ""
        return parts[19], Path(f"/proc/{pid}/cmdline").read_bytes().decode().replace("\0", " ")
    except (OSError, ValueError, IndexError):
        return "", ""


def _alive(job: dict) -> bool:
    ticks, command = _identity(job.get("pid", -1))
    return bool(ticks and ticks == job.get("start_ticks") and
                "--worker" in command and job["run_id"] in command)


def harness2_run_status(run_id: str) -> dict[str, Any]:
    """Get persisted state and exit code for a returned run ID."""
    job = _read(run_id)
    process = _PROCESSES.get(run_id)
    if process is not None and process.poll() is not None:
        _PROCESSES.pop(run_id, None)
    if (job["state"] in ("starting", "running", "cancelling") and not _alive(job)
            and not (job["state"] == "starting" and time.time() - job["created_at"] < 5)):
        job["state"] = "interrupted"
        job["error"] = "Worker absent; inspect run.log before retrying"
        _write(run_id, job)
    return job


def harness2_status() -> dict[str, Any]:
    """Read versions, model preflight, active jobs and scoped evidence-based qualifications; no inference."""
    check = runpy.run_path(str(ROOT / "scripts" / "check_local_model.py"))
    try:
        model = check["check_local_model"](required_context=16384)
    except Exception as exc:
        model = {"ready": False, "error": str(exc)}
    active = []
    qualified = []
    if RUNS.exists():
        for p in RUNS.glob("*/job.json"):
            job = harness2_run_status(p.parent.name)
            if job["state"] in ("starting", "running", "cancelling"):
                active.append(job["run_id"])
            if job.get("kind") == "rf_refinement" and job["state"] == "succeeded":
                proof = p.parent / "workflow" / "workflow.json"
                try:
                    if proof.stat().st_size > 200000:
                        continue
                    evidence = json.loads(proof.read_text())
                    core = evidence.get("core_summary", {})
                    if (evidence.get("qualified") is True and core.get("status") == "ok"
                            and not core.get("errors") and evidence.get("selected_score", {}).get("passed") is True):
                        qualified.append({"run_id": job["run_id"], "task": "rf-link-433-budget",
                            "model": evidence.get("external_model"), "synthetic_only": True})
                except (OSError, ValueError, UnicodeError):
                    pass
    return {"harness2": importlib.metadata.version("harness2"),
            "python": sys.version.split()[0], "model": model, "active_runs": active,
            "executable_profiles": ["deterministic_demo", "ollama_local", "ollama_glm_cloud"],
            "model_refinement_qualified": bool(qualified),
            "qualified_workflows": qualified[-20:], "local_model_refinement_qualified": False}


def harness2_start_demo(k: int = 1, seconds: int = 60) -> dict[str, Any]:
    """Start one bounded deterministic Harness² demo; does not call a model."""
    if type(k) is not int or k not in (1, 2):
        raise ValueError("k must be 1 or 2")
    if type(seconds) is not int or not 1 <= seconds <= 120:
        raise ValueError("seconds must be between 1 and 120")
    return _start_job("demo", {"k": k}, seconds)


def _start_job(kind: str, parameters: dict, seconds: int) -> dict[str, Any]:
    RUNS.mkdir(parents=True, exist_ok=True)
    with (RUNS / ".manager.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        for p in RUNS.glob("*/job.json"):
            if harness2_run_status(p.parent.name)["state"] in ("starting", "running", "cancelling"):
                raise ValueError("A job is already active; get its status or cancel it")
        run_id = uuid.uuid4().hex
        directory = _directory(run_id)
        directory.mkdir(mode=0o700)
        job = {"run_id": run_id, "state": "starting", **parameters, "kind": kind,
               "seconds": seconds, "created_at": time.time()}
        _write(run_id, job)
        with (directory / "run.log").open("ab") as log:
            process = subprocess.Popen(
                [sys.executable, "-m", "harness2.mcp_server", "--worker", run_id],
                cwd=ROOT, stdout=log, stderr=log, start_new_session=True)
        _PROCESSES[run_id] = process
        job.update(pid=process.pid, start_ticks=_identity(process.pid)[0], state="running")
        _write(run_id, job)
        return job


def harness2_plan_run(profile: str = "ollama_local", domain: str = "data_entry_keyers",
                      max_tasks: int = 1, k: int = 1, mode: str = "parallel",
                      workers: int = 1, seconds: int = 300, capability_query: str = "") -> dict[str, Any]:
    """Preview exact JobBench task stream and cloud data disclosure, without inference."""
    from . import mcp_workflow as workflow
    parameters = workflow.validate(profile, domain, max_tasks, k, mode, workers, seconds, capability_query)
    return workflow.plan(parameters, RUNS / "_plans" / profile)


def harness2_start_run(profile: str = "ollama_local", domain: str = "data_entry_keyers",
                       max_tasks: int = 1, k: int = 1, mode: str = "parallel",
                       workers: int = 1, seconds: int = 300,
                       allow_cloud: bool = False, capability_query: str = "") -> dict[str, Any]:
    """Start real bounded JobBench refinement. Cloud requires explicit allow_cloud."""
    from . import mcp_workflow as workflow
    if type(allow_cloud) is not bool:
        raise ValueError("allow_cloud must be boolean")
    parameters = workflow.validate(profile, domain, max_tasks, k, mode, workers, seconds, capability_query)
    if workflow.PROFILES[profile]["cloud"] and not allow_cloud:
        raise ValueError("Cloud sends task inputs, trajectories, harnesses and deliverables to Ollama Cloud; review plan_run and explicitly allow_cloud")
    plan = workflow.plan(parameters, RUNS / "_plans" / profile)
    evidence = workflow.preflight(parameters)
    return _start_job("refinement", {"parameters": parameters, "allow_cloud": allow_cloud,
                      "selection": plan["tasks"], "preflight": evidence}, seconds)


def harness2_start_judge(run_id: str, bases: bool = False, seconds: int = 300,
                         allow_cloud: bool = False) -> dict[str, Any]:
    """Judge one terminal refinement using its original profile/namespace; bases compares references."""
    from . import mcp_workflow as workflow
    source = harness2_run_status(run_id)
    if source.get("kind") != "refinement" or source["state"] in ("starting", "running", "cancelling"):
        raise ValueError("run_id must identify a terminal refinement job")
    if type(bases) is not bool or type(allow_cloud) is not bool:
        raise ValueError("bases and allow_cloud must be boolean")
    if type(seconds) is not int or not 1 <= seconds <= 3600:
        raise ValueError("seconds must be between 1 and 3600")
    if workflow.PROFILES[source["parameters"]["profile"]]["cloud"] and not allow_cloud:
        raise ValueError("Cloud judging sends deliverables to Ollama Cloud; explicitly allow_cloud")
    return _start_job("judge", {"source_run_id": run_id,
                      "parameters": source["parameters"], "bases": bases,
                      "allow_cloud": allow_cloud}, seconds)


def harness2_report(run_id: str) -> dict[str, Any]:
    """Render cached judged results for a terminal refinement; no model calls."""
    from . import mcp_workflow as workflow
    source = harness2_run_status(run_id)
    if source.get("kind") != "refinement" or source["state"] in ("starting", "running", "cancelling"):
        raise ValueError("run_id must identify a terminal refinement job")
    output = _directory(run_id) / "workflow"
    reply = subprocess.run(workflow.command(source["parameters"], "report"),
        cwd=ROOT, env=workflow.environment(source["parameters"], output),
        capture_output=True, text=True, timeout=30)
    return {"run_id": run_id, "exit_code": reply.returncode,
            "report": reply.stdout[-24000:], "error": reply.stderr[-2000:],
            "model_calls": False}


def harness2_start_rf_run(seconds: int = 300, allow_cloud: bool = False) -> dict[str, Any]:
    """Start true synthetic RF core workflow using GLM Ollama Cloud; explicit consent required."""
    if type(allow_cloud) is not bool or not allow_cloud:
        raise ValueError("RF workflow sends synthetic task, harness, trajectories and output to Ollama Cloud; explicitly allow_cloud")
    if type(seconds) is not int or not 1 <= seconds <= 300:
        raise ValueError("seconds must be between 1 and 300")
    script = ROOT / "scripts" / "run_rf_workflow.py"
    if not script.is_file():
        raise ValueError("RF workflow script is not installed")
    return _start_job("rf_refinement", {"allow_cloud": True}, seconds)


def harness2_results(run_id: str) -> dict[str, Any]:
    """Read bounded real workflow summaries, artifact manifest and log tail for a returned run ID."""
    job = harness2_run_status(run_id)
    directory = _directory(run_id)
    result = {"job": job}
    if job["state"] == "succeeded" and job.get("kind", "demo") == "demo":
        report = directory / "demo" / "demo.json"
        result["demo"] = json.loads(report.read_text()) if report.is_file() else None
    workflow_root = (_directory(job["source_run_id"]) / "workflow"
                     if job.get("source_run_id") else directory / "workflow")
    files = sorted(workflow_root.rglob("summary.json")) if workflow_root.is_dir() else []
    rf = workflow_root / "workflow.json"
    candidates = ([rf] if rf.is_file() else []) + files
    result["summaries"] = []
    result["artifact_manifest"] = []
    remaining = 120000
    for index, artifact in enumerate(candidates[:100]):
        entry = {"path": str(artifact.relative_to(workflow_root))}
        try:
            if artifact.stat().st_size > remaining:
                entry["state"] = "omitted_size_budget"
            elif index >= 20:
                entry["state"] = "omitted_count_budget"
            else:
                def reject_constant(value):
                    raise ValueError("Non-finite JSON value")
                data = json.loads(artifact.read_text(), parse_constant=reject_constant)
                size = len(json.dumps(data, ensure_ascii=True, allow_nan=False).encode())
                if size > remaining:
                    entry["state"] = "omitted_size_budget"
                else:
                    if artifact == rf:
                        result["rf_workflow"] = data
                    else:
                        result["summaries"].append({"path": entry["path"], "summary": data})
                    remaining -= size
                    entry["state"] = "included"
        except (OSError, ValueError, UnicodeError):
            entry["state"] = "unreadable_or_in_progress"
        result["artifact_manifest"].append(entry)
    result["artifact_count"] = len(candidates)
    result["artifacts_truncated"] = len(candidates) > 100 or any(
        item["state"] != "included" for item in result["artifact_manifest"])
    log = directory / "run.log"
    if log.is_file():
        with log.open("rb") as stream:
            stream.seek(max(0, log.stat().st_size - 4000))
            result["log_tail"] = stream.read().decode(errors="replace")
    return result


def harness2_cancel(run_id: str) -> dict[str, Any]:
    """Request cancellation only for this adapter's verified worker process."""
    job = harness2_run_status(run_id)
    if job["state"] not in ("starting", "running", "cancelling"):
        return job
    if not _alive(job):
        raise ValueError("Worker identity changed; refusing to signal it")
    (_directory(run_id) / "cancel.requested").touch()
    return {**job, "state": "cancelling"}


def _worker(run_id: str) -> int:
    directory = _directory(run_id)
    for _ in range(100):
        job = _read(run_id)
        if job.get("pid") == os.getpid():
            break
        time.sleep(0.05)
    else:
        return 1
    module = runpy.run_path(str(ROOT / "scripts" / "run_bounded_local.py"))
    supervisor = module["supervise"]
    stopped = threading.Event()
    def cancellation_watchdog():
        while not stopped.wait(0.05):
            if (directory / "cancel.requested").exists() and module["_children"]():
                os.kill(os.getpid(), signal.SIGTERM)
                return
    threading.Thread(target=cancellation_watchdog, daemon=True).start()
    try:
        kind = job.get("kind", "demo")
        if kind == "demo":
            argv = [sys.executable, "-m", "harness2.cli.demo", "--output",
                    str(directory / "demo"), "--k", str(job["k"])]
            environment = os.environ.copy()
        elif kind in ("refinement", "judge"):
            from . import mcp_workflow as workflow
            output = (_directory(job["source_run_id"]) / "workflow"
                      if kind == "judge" else directory / "workflow")
            argv = workflow.supervised_command(job["parameters"], output, kind, job.get("bases", False))
            environment = os.environ.copy()
        elif kind == "rf_refinement":
            argv = [sys.executable, str(ROOT / "scripts" / "run_rf_workflow.py"),
                    "--output", str(directory / "workflow"), "--seconds", str(job["seconds"])]
            environment = os.environ.copy()
        else:
            raise ValueError("Unknown persisted job kind")
        code = supervisor(argv, seconds=job["seconds"], cwd=ROOT, env=environment)
        state = ("cancelled" if (directory / "cancel.requested").exists()
                 else "timed_out" if code == 124 else "succeeded" if code == 0 else "failed")
        job.update(state=state, exit_code=code, finished_at=time.time())
    except Exception as exc:
        job.update(state="failed", error=str(exc), finished_at=time.time())
    stopped.set()
    _write(run_id, job)
    return 0


def _sdk_tool(function):
    """Keep actionable validation errors in MCP responses without internal tracebacks."""
    import functools
    from mcp.server.mcpserver.exceptions import ToolError
    @functools.wraps(function)
    def guarded(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except (ValueError, FileNotFoundError) as exc:
            raise ToolError(str(exc)) from exc
    return guarded


def serve() -> None:
    from mcp.server import MCPServer
    server = MCPServer("Harness2 local controller")
    for tool in (harness2_status, harness2_start_demo, harness2_run_status,
                 harness2_results, harness2_cancel, harness2_plan_run, harness2_start_run,
                 harness2_start_judge, harness2_report, harness2_start_rf_run):
        server.tool(structured_output=True)(_sdk_tool(tool))
    server.run()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker")
    args = parser.parse_args()
    if args.worker:
        raise SystemExit(_worker(args.worker))
    serve()
