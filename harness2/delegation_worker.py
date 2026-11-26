"""Persisted CLI delegation worker for the controller's existing supervisor.

Only a controller run ID is accepted on argv. Tasks and role selection are read
from its job file; the parent supervisor owns cancellation and wall deadlines.
"""
from __future__ import annotations
import argparse
import json
import math
import os
from pathlib import Path
import re
import sys
import uuid
from typing import Any

from . import agent_delegation
from . import mcp_server as controller

ROLE_NAMES = frozenset(("planner", "implementer", "reviewer", "verifier"))


def _text(value: Any, limit: int) -> str:
    text = value if isinstance(value, str) else str(value)
    for key, secret in os.environ.items():
        if len(secret) >= 8 and re.search(r"TOKEN|SECRET|PASSWORD|API_KEY|ACCESS_KEY", key, re.I):
            text = text.replace(secret, "[redacted]")
    text = re.sub(r"(?i)(bearer\s+)[^\s\"']+", r"\1[redacted]", text)
    text = re.sub(r"\bsk-[A-Za-z0-9_-]{16,}", "[redacted]", text)
    return text[:limit]


def _usage(value: Any) -> dict:
    if not isinstance(value, dict):
        return {}
    return {_text(key, 100): item for key, item in list(value.items())[:30]
            if type(item) in (int, float) and math.isfinite(item)}


def _compact_report(directory: Path, manifest: dict, error: str | None = None) -> dict:
    output = directory / "delegation"
    records = manifest.get("roles", [])
    roles = []
    for record in records[:4] if isinstance(records, list) else []:
        if not isinstance(record, dict):
            continue
        role = record.get("role")
        item = {
            key: _text(record[key], 200) if record.get(key) is not None else None
            for key in ("role", "route", "provider", "state", "model")
        }
        item.update(
            exit_code=record.get("exit_code") if type(record.get("exit_code")) is int else None,
            reported_usage=_usage(record.get("reported_usage")),
            output_preview=_text(record.get("output", ""), 4000),
            error=_text(record.get("error") or record.get("provider_error") or "", 1000),
            stdout_file=str(output / role / "stdout.log") if isinstance(role, str) and role in ROLE_NAMES else None,
        )
        models = record.get("reported_models")
        if isinstance(models, list):
            item["reported_models"] = [_text(model, 200) for model in models[:8] if isinstance(model, str)]
        roles.append(item)
    inference = manifest.get("inference_performed")
    report = {
        "kind": "agent_delegation",
        "state": _text(manifest.get("state", "failed"), 100),
        "method": "nativeCLIroledelegation",
        "inference_performed": inference if type(inference) is bool else None,
        "roles": roles,
        "manifest_path": str(output / "manifest.json"),
        "engineering_validation_performed": False,
    }
    if error:
        report["error"] = _text(error, 1000)
    return report


def _save(directory: Path, report: dict) -> None:
    workflow = directory / "workflow"
    workflow.mkdir(exist_ok=True, mode=0o700)
    temporary = workflow / ("workflow." + uuid.uuid4().hex + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2) + "\n")
    temporary.chmod(0o600)
    temporary.replace(workflow / "workflow.json")


def _partial_manifest(directory: Path) -> dict:
    path = directory / "delegation/manifest.json"
    try:
        if path.is_file() and path.stat().st_size <= 262144:
            value = json.loads(path.read_text())
            if isinstance(value, dict):
                return value
    except (OSError, ValueError, UnicodeError):
        pass
    return {}


def run_worker(run_id: str) -> int:
    """Run one persisted agent_delegation job without changing controller state."""
    directory = controller._directory(run_id)
    job = controller._read(run_id)
    if job.get("kind") != "agent_delegation":
        raise ValueError("Persisted job is not an agent_delegation job")
    try:
        seconds = job.get("seconds")
        parallel = job.get("max_parallel", 2)
        if type(seconds) is not int or not 1 <= seconds <= 600:
            raise ValueError("Delegation seconds must be between 1 and 600")
        if type(parallel) is not int or not 1 <= parallel <= 2:
            raise ValueError("Delegation max_parallel must be 1 or 2")
        task = job.get("task")
        if not isinstance(task, str) or not task.strip() or len(task.encode()) > 16000:
            raise ValueError("Delegation task must contain 1..16000 UTF-8 bytes")
        roles = job.get("roles")
        if roles is not None and (
            not isinstance(roles, list) or not 1 <= len(roles) <= 4
            or any(not isinstance(role, str) or role not in ROLE_NAMES for role in roles)
            or len(set(roles)) != len(roles)
        ):
            raise ValueError("Delegation roles must be 1..4 unique named roles")
        manifest = agent_delegation.run(
            task, roles, outputDir=str(directory / "delegation"),
            seconds=seconds, max_parallel=parallel,
        )
        if not isinstance(manifest, dict):
            raise ValueError("Delegation returned an invalid manifest")
        report = _compact_report(directory, manifest)
    except Exception as error:
        manifest = _partial_manifest(directory)
        report = _compact_report(directory, {**manifest, "state": "failed"},
                                 type(error).__name__ + ": " + str(error))
        _save(directory, report)
        return 1
    _save(directory, report)
    return 0 if manifest.get("state") == "completed" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    options = parser.parse_args(argv)
    try:
        return run_worker(options.run_id)
    except (ValueError, OSError) as error:
        print(json.dumps({"error": _text(str(error), 1000)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
