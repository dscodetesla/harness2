"""Five typed tools for the existing CAD FastMCP gateway; no SDK dependency here."""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path("/home/user/src/harness2")
COMMAND = [str(ROOT / ".venv-mcp/bin/python"), "-m", "harness2.mcp_control_cli"]
MAX_OUTPUT = 262144


def _call(action: str, arguments: dict) -> dict:
    payload = json.dumps({"action": action, "arguments": arguments}).encode()
    env = {key: os.environ[key] for key in ("PATH", "HOME", "LANG", "LC_ALL") if key in os.environ}
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        try:
            result = subprocess.run(COMMAND, input=payload, cwd=ROOT, env=env,
                                    stdout=out, stderr=err, timeout=45, check=False)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Harness2 controller timed out; check status before retrying start") from exc
        except OSError as exc:
            raise RuntimeError("Harness2 controller could not start") from exc
        out.seek(0)
        raw = out.read(MAX_OUTPUT + 1)
        if len(raw) > MAX_OUTPUT:
            raise RuntimeError("Harness2 controller output exceeds limit")
        try:
            envelope = json.loads(raw)
        except (ValueError, UnicodeError) as exc:
            raise RuntimeError("Harness2 controller returned invalid JSON") from exc
        if not isinstance(envelope, dict):
            raise RuntimeError("Harness2 controller returned invalid envelope")
        if result.returncode != 0 or envelope.get("ok") is not True:
            error = envelope.get("error", {})
            message = error.get("message", "Controller failed") if isinstance(error, dict) else "Controller failed"
            raise RuntimeError(f"Harness2: {str(message)[:1000]}")
        value = envelope.get("result")
        if not isinstance(value, dict):
            raise RuntimeError("Harness2 controller returned invalid result")
        return value


def harness2_status() -> dict:
    """Read Harness² versions, local model metadata and active demo jobs; no inference."""
    return _call("status", {})


def harness2_start_demo(k: int = 1, seconds: int = 60) -> dict:
    """Start one bounded deterministic Harness² demo; no model or cloud calls."""
    return _call("start_demo", {"k": k, "seconds": seconds})


def harness2_run_status(run_id: str) -> dict:
    """Read persisted state for the run_id returned by harness2_start_demo."""
    return _call("run_status", {"run_id": run_id})


def harness2_results(run_id: str) -> dict:
    """Read a bounded demo report and log tail for a returned run_id."""
    return _call("results", {"run_id": run_id})


def harness2_cancel(run_id: str) -> dict:
    """Request cancellation of this controller's verified demo worker."""
    return _call("cancel", {"run_id": run_id})



def harness2_plan_run(profile: str = "ollama_local", domain: str = "data_entry_keyers",
                      max_tasks: int = 1, k: int = 1, mode: str = "parallel",
                      workers: int = 1, seconds: int = 300) -> dict:
    """Preview exact real JobBench selection and cloud disclosure without inference."""
    return _call("plan_run", dict(profile=profile, domain=domain, max_tasks=max_tasks,
                 k=k, mode=mode, workers=workers, seconds=seconds))


def harness2_start_run(profile: str = "ollama_local", domain: str = "data_entry_keyers",
                       max_tasks: int = 1, k: int = 1, mode: str = "parallel",
                       workers: int = 1, seconds: int = 300, allow_cloud: bool = False) -> dict:
    """Start bounded real JobBench refinement; cloud requires explicit allow_cloud."""
    return _call("start_run", dict(profile=profile, domain=domain, max_tasks=max_tasks,
                 k=k, mode=mode, workers=workers, seconds=seconds, allow_cloud=allow_cloud))


def harness2_start_judge(run_id: str, bases: bool = False, seconds: int = 300,
                         allow_cloud: bool = False) -> dict:
    """Judge selected or baseline artifacts of a terminal real refinement run."""
    return _call("start_judge", dict(run_id=run_id, bases=bases, seconds=seconds, allow_cloud=allow_cloud))


def harness2_report(run_id: str) -> dict:
    """Render a cached real refinement score report without model calls."""
    return _call("report", dict(run_id=run_id))


def harness2_start_rf_run(seconds: int = 300, allow_cloud: bool = False) -> dict:
    """Start real synthetic RF core workflow; sends task/harness evidence to Ollama Cloud only with allow_cloud."""
    return _call("start_rf_run", dict(seconds=seconds, allow_cloud=allow_cloud))


def register_tools(mcp) -> None:
    for function in (harness2_status, harness2_start_demo, harness2_run_status,
                     harness2_results, harness2_cancel, harness2_plan_run, harness2_start_run,
                     harness2_start_judge, harness2_report, harness2_start_rf_run):
        mcp.tool()(function)
