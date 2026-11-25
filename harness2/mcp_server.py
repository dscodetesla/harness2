"""Local stdio MCP adapter. Only deterministic demo jobs are executable."""
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
        raise ValueError("run_id must be the ID returned by harness2_start_demo")
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
    """Read versions, local model preflight, and active demo jobs; no inference."""
    check = runpy.run_path(str(ROOT / "scripts" / "check_local_model.py"))
    try:
        model = check["check_local_model"](required_context=16384)
    except Exception as exc:
        model = {"ready": False, "error": str(exc)}
    active = []
    if RUNS.exists():
        for p in RUNS.glob("*/job.json"):
            job = harness2_run_status(p.parent.name)
            if job["state"] in ("starting", "running", "cancelling"):
                active.append(job["run_id"])
    return {"harness2": importlib.metadata.version("harness2"),
            "python": sys.version.split()[0], "model": model, "active_runs": active,
            "executable_profiles": ["deterministic_demo"],
            "model_refinement_qualified": False}


def harness2_start_demo(k: int = 1, seconds: int = 60) -> dict[str, Any]:
    """Start one bounded deterministic Harness² demo; does not call a model."""
    if type(k) is not int or k not in (1, 2):
        raise ValueError("k must be 1 or 2")
    if type(seconds) is not int or not 1 <= seconds <= 120:
        raise ValueError("seconds must be between 1 and 120")
    RUNS.mkdir(parents=True, exist_ok=True)
    with (RUNS / ".manager.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        for p in RUNS.glob("*/job.json"):
            if harness2_run_status(p.parent.name)["state"] in ("starting", "running", "cancelling"):
                raise ValueError("A demo is already active; get its status or cancel it")
        run_id = uuid.uuid4().hex
        directory = _directory(run_id)
        directory.mkdir(mode=0o700)
        job = {"run_id": run_id, "state": "starting", "k": k,
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


def harness2_results(run_id: str) -> dict[str, Any]:
    """Read terminal demo summary and a bounded log tail for a returned run ID."""
    job = harness2_run_status(run_id)
    directory = _directory(run_id)
    result = {"job": job}
    if job["state"] == "succeeded":
        report = directory / "demo" / "demo.json"
        result["demo"] = json.loads(report.read_text()) if report.is_file() else None
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
        code = supervisor(
            [sys.executable, "-m", "harness2.cli.demo", "--output",
             str(directory / "demo"), "--k", str(job["k"])],
            seconds=job["seconds"], cwd=ROOT, env=os.environ.copy())
        state = ("cancelled" if (directory / "cancel.requested").exists()
                 else "timed_out" if code == 124 else "succeeded" if code == 0 else "failed")
        job.update(state=state, exit_code=code, finished_at=time.time())
    except Exception as exc:
        job.update(state="failed", error=str(exc), finished_at=time.time())
    stopped.set()
    _write(run_id, job)
    return 0


def serve() -> None:
    from mcp.server import MCPServer
    server = MCPServer("Harness2 local controller")
    for tool in (harness2_status, harness2_start_demo, harness2_run_status,
                 harness2_results, harness2_cancel):
        server.tool(structured_output=True)(tool)
    server.run()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker")
    args = parser.parse_args()
    if args.worker:
        raise SystemExit(_worker(args.worker))
    serve()
