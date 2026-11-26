"""Role-scoped delegation through observed fixed CLI routes; no model-generated commands."""
from __future__ import annotations

import argparse
import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import threading
import time
import uuid
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CLI_NAMES = ("mods", "sgpt", "ollama", "aichat", "tgpt", "opencode", "claude",
             "hermes", "codex", "aider", "goose", "gemini", "openhands", "kilo",
             "llm", "agy", "antigravity")
EVIDENCE = ROOT.parent / "harness2-host-capabilities-private/evidence/agent-routing" / {
    "dell-t3500": "dell-inventory.json", "x99mg": "x99mg-inventory.json"
}.get(socket.gethostname().lower(), socket.gethostname().lower() + "-inventory.json")
POLICY = Path.home() / ".config/harness2/agent-roles.json"
ROUTES = {
    "ollama_cloud_glm": {"cli": "ollama", "provider": "Ollama Cloud",
                          "model": "glm-5.3-flash:cloud", "cloud": True},
    "codex_chatgpt": {"cli": "codex", "provider": "OpenAI ChatGPT CLI login",
                      "model": "CLI configured model", "cloud": True},
    "claude_subscription": {"cli": "claude", "provider": "Anthropic first-party CLI login",
                            "model": "CLI configured model", "cloud": True},
}
SCOPES = {
    "planner": "Analyze the task and give a concise implementation plan, assumptions and dependencies.",
    "implementer": "Propose concrete implementation steps or a minimal code sketch. Do not modify files or claim execution.",
    "reviewer": "Challenge the proposed task approach: identify failure modes, conflicting assumptions and missing evidence.",
    "verifier": "Derive checkable acceptance conditions from the supplied task. This is analysis only; do not claim tests or tool operations ran.",
}
MAX_ROLE_BYTES = 262144
_LOCK = threading.Lock()


def _now():
    return datetime.now(timezone.utc).isoformat()


def _atomic(path: Path, value):
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n")
    temporary.replace(path)


def _cli_dirs():
    return (Path.home() / ".local/bin", Path.home() / ".npm-global/bin",
            Path("/usr/local/bin"), Path("/usr/bin"), Path("/bin"))


def _resolve_cli(name, entry=None):
    if name not in CLI_NAMES:
        return None
    entry = entry or {}
    observed = entry.get("path")
    if observed:
        candidate = Path(observed)
        # Preserve the actual observed launcher, even when SSH has a minimal PATH.
        if (candidate.is_absolute() and candidate.name == name
                and candidate.parent in _cli_dirs() and candidate.is_file()
                and os.access(candidate, os.X_OK)):
            return str(candidate)
        return None  # Never transfer binary A's login/help evidence to binary B.
    if entry.get("_normalized_evidence"):
        return None
    found = shutil.which(name)
    if found:
        return found
    for directory in _cli_dirs():
        candidate = directory / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def _normalize_entry(entry, observed_at):
    record = dict(entry)
    alternate = "help_evidence" in entry
    if alternate:
        record["subcommand_help"] = {}
        record["help"] = {}
        launchers = []
        for evidence in entry.get("help_evidence", []):
            argv = evidence.get("argv", [])
            text = evidence.get("text", evidence.get("excerpt", ""))
            if isinstance(text, list):
                text = "\n".join(line for line in text if isinstance(line, str))
            help_record = {"exit_code": evidence.get("exit_code"), "text": text,
                           "source_was_truncated": evidence.get("source_was_truncated", False)}
            if len(argv) == 2 and argv[1] == "--help":
                record["help"] = help_record
                launchers.append(argv[0])
            elif len(argv) == 3 and argv[1:] == ["exec", "--help"]:
                record["subcommand_help"]["exec"] = help_record
                launchers.append(argv[0])
        record["path"] = launchers[0] if launchers and len(set(launchers)) == 1 else None
        auth = {}
        for evidence in entry.get("auth_status_probes", []):
            argv = evidence.get("argv", [])
            if not record["path"] or not argv or argv[0] != record["path"] or evidence.get("exit_code") != 0:
                continue
            status = evidence.get("status")
            if entry.get("name") == "claude" and isinstance(status, dict) and argv[1:3] == ["auth", "status"]:
                auth = {key: status[key] for key in ("loggedIn", "authMethod", "apiProvider", "subscriptionType") if key in status}
                auth.update(exit_code=0, observed_at=observed_at,
                    subscription_cli_login_verified=status.get("loggedIn") is True and status.get("authMethod") == "claude.ai")
            elif entry.get("name") == "codex" and status == "chatgpt_login_present" and argv[1:] == ["login", "status"]:
                auth = {"exit_code": 0, "chatgpt_login_verified": True, "observed_at": observed_at}
        record["auth_evidence"] = auth
        record["version"] = {"text": entry.get("version")}
    record["_normalized_evidence"] = True
    return record


def _evidence():
    try:
        payload = json.loads(EVIDENCE.read_text())
        if not isinstance(payload, dict) or payload.get("host") != socket.gethostname():
            return {}
        entries = payload.get("entries", payload.get("agents", []))
        return {entry["name"]: _normalize_entry(entry, payload.get("observed_at", payload.get("checked_at")))
                for entry in entries if isinstance(entry, dict) and entry.get("name") in CLI_NAMES}
    except (OSError, ValueError, TypeError, AttributeError):
        return {}


def _failure_class(diagnostic):
    diagnostic = diagnostic.lower()
    if any(term in diagnostic for term in ("quota", "usage limit", "rate limit", "insufficient_quota")):
        return "quota_or_rate_limited"
    if any(term in diagnostic for term in ("unauthorized", "not logged in", "login required",
            "invalid api key", "authentication failed", "failed to authenticate",
            "oauth session expired", "could not be refreshed")):
        return "authentication_failed"
    return "failed"


def _latest_execution_states():
    """Read at most twenty bounded local role records; advisory evidence never changes routing."""
    candidates = []
    base = ROOT / "runs/mcp"
    try:
        jobs = []
        with os.scandir(base) as entries:
            for index, entry in enumerate(entries):
                if index >= 1000:
                    break
                if entry.is_dir(follow_symlinks=False):
                    try:
                        jobs.append((entry.stat(follow_symlinks=False).st_mtime, Path(entry.path)))
                    except OSError:
                        continue
        for _, job in sorted(jobs, reverse=True)[:20]:
            for role in SCOPES:
                path = job / "delegation" / role / "result.json"
                try:
                    if path.resolve().is_relative_to(base.resolve()) and path.is_file():
                        candidates.append((path.stat().st_mtime, path))
                except OSError:
                    continue
    except OSError:
        return {}
    latest = {}
    valid_states = {"completed", "failed", "authentication_failed", "quota_or_rate_limited",
                    "timed_out", "output_limit", "blocked", "not_started_deadline"}
    for _, path in sorted(candidates, reverse=True)[:20]:
        try:
            with path.open("rb") as stream:
                raw = stream.read(131073)
            if len(raw) > 131072:
                continue
            record = json.loads(raw)
            if not isinstance(record, dict):
                continue
            route, state, finished = record.get("route"), record.get("state"), record.get("finished_at")
            if route not in ROUTES or state not in valid_states or not isinstance(finished, str) or len(finished) > 80:
                continue
            observed = datetime.fromisoformat(finished)
            if observed.tzinfo is None:
                continue
            if route in latest and observed <= datetime.fromisoformat(latest[route]["last_execution_finished_at"]):
                continue
            latest[route] = {
                "last_execution_state": state, "last_execution_finished_at": finished,
                "last_execution_error_class": (_failure_class(str(record.get("provider_error", ""))
                    + " " + str(record.get("stderr", ""))) if state == "failed"
                    else state if state != "completed" else None),
                "execution_evidence_path": str(path), "execution_evidence_advisory_only": True,
            }
        except (OSError, ValueError, TypeError):
            continue
    return latest


def _route_state(name, entries, latest=None):
    spec = ROUTES[name]
    entry = entries.get(spec["cli"], {})
    executable = _resolve_cli(spec["cli"], entry)
    auth = entry.get("auth_evidence", {})
    help_text = entry.get("help", {}).get("text", "")
    status = "executable_missing"
    eligible = False
    if executable:
        if name == "ollama_cloud_glm":
            eligible = True
            status = "authorized_cloud_route_ready_for_trial"
        elif name == "codex_chatgpt":
            exec_help = entry.get("subcommand_help", {}).get("exec", {})
            eligible = bool(auth.get("exit_code") == 0 and auth.get("chatgpt_login_verified") is True
                and exec_help.get("exit_code") == 0
                and all(flag in exec_help.get("text", "") for flag in
                        ("--sandbox", "--skip-git-repo-check", "--json", "--ignore-user-config", "--ephemeral")))
            status = "observed_chatgpt_login_and_exec_contract" if eligible else "auth_or_exec_contract_unverified"
        elif name == "claude_subscription":
            eligible = bool(auth.get("exit_code") == 0 and auth.get("loggedIn") is True
                and auth.get("authMethod") == "claude.ai" and auth.get("apiProvider") == "firstParty"
                and entry.get("help", {}).get("exit_code") == 0
                and all(flag in help_text for flag in ("--tools", "--strict-mcp-config", "--mcp-config", "--output-format", "--permission-mode", "--no-session-persistence")))
            status = "observed_first_party_cli_login_and_disabled_tools_contract" if eligible else "auth_or_exec_contract_unverified"
    return {**spec, **(latest or {}).get(name, {}), "route": name, "executable": executable, "ready_for_trial": eligible,
            "status": status, "actual_access_verified_this_run": False,
            "auth_observed_at": auth.get("observed_at"),
            "paid_plan_verified": auth.get("paid_plan_verified", False) if name != "ollama_cloud_glm" else None,
            "help_and_auth_evidence": str(EVIDENCE) if entry else None}


def inventory() -> dict[str, Any]:
    """Inventory all requested CLI clients; distinguish PATH, source checkout, auth and verified use."""
    entries = _evidence()
    latest = _latest_execution_states()
    clients = []
    for name in CLI_NAMES:
        known = entries.get(name, {})
        executable = _resolve_cli(name, known)
        source = known.get("source_checkout", {})
        clients.append({"cli": name, "executable": executable, "installed_on_path": bool(executable),
            "source_checkout_available": source.get("available") is True,
            "observed_version": known.get("version", {}).get("text") if isinstance(known.get("version"), dict) else known.get("version"),
            "auth_state": known.get("auth_state", "not_verified"),
            "subscription_login_verified": bool(known.get("auth_evidence", {}).get("chatgpt_login_verified")
                or known.get("auth_evidence", {}).get("subscription_cli_login_verified")),
            "runnable_route_implemented": any(spec["cli"] == name for spec in ROUTES.values())})
    return {"host": socket.gethostname(), "clients": clients,
        "routes": [_route_state(name, entries, latest) for name in ROUTES],
        "inference_performed": False, "installs_performed": False,
        "limits": "Installed CLI and login evidence do not establish task success, quota or billing"}


def _roles(roles):
    roles = ["planner", "reviewer"] if roles is None else roles
    if not isinstance(roles, list) or not roles or len(roles) > 4:
        raise ValueError("roles must contain 1..4 unique named roles")
    if any(not isinstance(role, str) or role not in SCOPES for role in roles):
        raise ValueError("Roles must be planner, implementer, reviewer or verifier")
    if len(set(roles)) != len(roles):
        raise ValueError("roles must be unique")
    return roles


def _policy():
    defaults = {role: "ollama_cloud_glm" for role in SCOPES}
    if not POLICY.is_file():
        return defaults
    payload = json.loads(POLICY.read_text())
    if not isinstance(payload, dict) or set(payload) != {"roles"} or not isinstance(payload["roles"], dict):
        raise ValueError("agent-roles.json must contain only roles mapping")
    for role, route in payload["roles"].items():
        if role not in SCOPES or not isinstance(route, str) or route not in ROUTES:
            raise ValueError("Role policy must use named roles and registered routes only")
        defaults[role] = route
    return defaults


def _task(task):
    if not isinstance(task, str) or not task.strip() or len(task.encode()) > 16000:
        raise ValueError("task must contain 1..16000 UTF-8 bytes")
    return task


def plan(task: str, roles: list[str] | None = None) -> dict[str, Any]:
    """Plan role-scoped CLI routes from a fixed registry and observed native auth/help evidence."""
    task, roles = _task(task), _roles(roles)
    policy, entries = _policy(), _evidence()
    latest = _latest_execution_states()
    assignments = [{"role": role, "scope": SCOPES[role],
                    **_route_state(policy[role], entries, latest)} for role in roles]
    return {"task": task, "task_id": "task_" + hashlib.sha256(task.encode()).hexdigest()[:16],
            "roles": assignments, "work_mode": "read_only_analysis",
            "provider_count": len({item["provider"] for item in assignments}),
            "route_count": len({item["route"] for item in assignments}),
            "statistical_independence_claimed": False,
            "max_parallel": 2, "default_route": "ollama_cloud_glm",
            "same_provider_roles_are_not_independent_models": True,
            "cloud_data": ["task text", "role-scoped prompts"], "inference_performed": False,
            "native_subscription_cli_only_with_observed_auth": True,
            "billing_or_quota_guaranteed": False}


def _argv(assignment, prompt, directory):
    executable, route = assignment["executable"], assignment["route"]
    if route == "ollama_cloud_glm":
        return [executable, "run", "--think=false", "--hidethinking", "--nowordwrap", ROUTES[route]["model"], prompt], "argv"
    if route == "codex_chatgpt":
        return [executable, "exec", "--ignore-user-config", "--sandbox", "read-only",
                "--json", "--ephemeral", "--skip-git-repo-check", "-"], "stdin"
    if route == "claude_subscription":
        return [executable, "--print", "--output-format", "json", "--permission-mode", "plan",
                "--tools", "", "--no-session-persistence", "--strict-mcp-config",
                "--mcp-config", '{"mcpServers":{}}'], "stdin"
    raise ValueError("Unknown fixed route")


def _stop(process):
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)


def _read(path, maximum=16000):
    try:
        with path.open("rb") as stream:
            data = stream.read(maximum + 1)
        return data[:maximum].decode(errors="replace"), len(data) > maximum
    except OSError:
        return "", False


def _run_role(assignment, task, output, deadline):
    role = assignment["role"]
    directory = output / role
    directory.mkdir(mode=0o700)
    prompt = ("PARENT_TASK_ID: " + assignment.get("parent_task_id", "task_" + hashlib.sha256(task.encode()).hexdigest()[:16])
        + "\nROLE: " + role + "\nSCOPE: " + assignment["scope"]
        + "\nRead-only analysis: do not use tools, inspect personal files, execute commands, "
          "change systems or contact anyone. Answer only from the supplied task. "
          "Keep your response under 600 words. Explicitly label assumptions and unverified claims. "
          "The verifier role is analytical and is not a deterministic test runner.\nTASK:\n" + task)
    (directory / "prompt.txt").write_text(prompt)
    record = {key: assignment.get(key) for key in ("role", "route", "provider", "model", "status", "auth_observed_at")}
    record.update(state="starting", started_at=_now(), prompt_path=str(directory / "prompt.txt"),
        parent_task_id=assignment.get("parent_task_id", "task_" + hashlib.sha256(task.encode()).hexdigest()[:16]),
        focus_constraints=["Supplied-task analysis only", "No workspace or device writes", "No unexecuted test success claims"])
    _atomic(directory / "result.json", record)
    if not assignment["ready_for_trial"]:
        record.update(state="blocked", error="Selected CLI route is not verified ready for a trial", inference_performed=False)
        _atomic(directory / "result.json", record)
        return record
    if time.monotonic() >= deadline:
        record.update(state="not_started_deadline", inference_performed=False)
        _atomic(directory / "result.json", record)
        return record
    argv, prompt_transport = _argv(assignment, prompt, directory)
    _atomic(directory / "request.json", {"argv": argv, "prompt_transport": prompt_transport,
                                        "scope": "read_only_analysis"})
    env = {key: os.environ[key] for key in ("PATH", "HOME", "LANG", "LC_ALL", "SSL_CERT_FILE", "SSL_CERT_DIR") if key in os.environ}
    env["PATH"] = os.pathsep.join(str(path) for path in _cli_dirs())
    env.update(OLLAMA_HOST="http://127.0.0.1:11434", OLLAMA_NOHISTORY="1", NO_COLOR="1", TERM="dumb")
    process = None
    reason = None
    with (directory / "stdout.log").open("wb") as stdout, (directory / "stderr.log").open("wb") as stderr, \
         (directory / "prompt.txt").open("rb") as stdin:
        try:
            process = subprocess.Popen(argv, cwd=directory, env=env,
                stdin=stdin if prompt_transport == "stdin" else subprocess.DEVNULL,
                stdout=stdout, stderr=stderr, start_new_session=True)
            record.update(state="running", pid=process.pid, inference_requested=True, inference_performed=None)
            _atomic(directory / "result.json", record)
            while process.poll() is None:
                if time.monotonic() >= deadline:
                    reason = "timed_out"
                    _stop(process)
                    break
                if stdout.tell() + stderr.tell() > MAX_ROLE_BYTES:
                    reason = "output_limit"
                    _stop(process)
                    break
                time.sleep(.05)
            code = process.wait(timeout=5)
            record.update(exit_code=code, state=reason or ("completed" if code == 0 else "failed"))
        except Exception as exc:
            if process is not None:
                _stop(process)
            record.update(state="failed", error=f"{type(exc).__name__}: {exc}", inference_requested=process is not None, inference_performed=None if process is not None else False)
    stdout_text, stdout_truncated = _read(directory / "stdout.log")
    stderr_text, stderr_truncated = _read(directory / "stderr.log", 3000)
    final, final_truncated = _read(directory / "final.txt")
    provider_success = record.get("exit_code") == 0
    provider_error = ""
    if assignment["route"] == "claude_subscription" and stdout_text:
        try:
            raw_json, _ = _read(directory / "stdout.log", MAX_ROLE_BYTES)
            payload = json.loads(raw_json)
            if not isinstance(payload, dict):
                raise ValueError("Expected Claude result object")
            provider_success = provider_success and payload.get("is_error") is not True
            final = str(payload.get("result", ""))
            if payload.get("is_error") is True:
                provider_error = final[:1000]
            record["reported_models"] = list(payload.get("modelUsage", {}))
        except (ValueError, TypeError):
            provider_success = False
            provider_error = "Claude result was not a complete JSON object"
    elif assignment["route"] == "codex_chatgpt":
        from .substrate.codex import final_message
        final = final_message(directory / "stdout.log")
        raw_events, _ = _read(directory / "stdout.log", MAX_ROLE_BYTES)
        for line in raw_events.splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if not isinstance(event, dict):
                continue
            if event.get("type") in ("error", "turn.failed"):
                provider_success = False
                error = event.get("error", event)
                provider_error = str(error.get("message", "Codex provider error"))[:1000] if isinstance(error, dict) else "Codex provider error"
            if event.get("type") == "turn.completed" and isinstance(event.get("usage"), dict):
                record["reported_usage"] = {key: value for key, value in event["usage"].items() if type(value) in (int, float)}
    else:
        final = final or stdout_text
    record.update(finished_at=_now(), output=final[:16000], stderr=stderr_text,
        output_truncated=stdout_truncated or final_truncated or len(final) > 16000,
        stderr_truncated=stderr_truncated, provider_response_success=provider_success,
        inference_performed=True if provider_success and final.strip() else (None if process is not None else False),
        analytical_response_only=True, engineering_validation_performed=False)
    if record["state"] == "completed" and (not provider_success or not final.strip()):
        record.update(state="failed", error=provider_error or "CLI completed without a successful nonempty model response")
    if record["state"] == "failed":
        record["state"] = _failure_class(provider_error + " " + stderr_text)
    if provider_error:
        record["provider_error"] = provider_error
    _atomic(directory / "result.json", record)
    return record


def run(task: str, roles: list[str] | None = None, outputDir: str | None = None,
        seconds: int = 180, max_parallel: int = 2) -> dict[str, Any]:
    """Run named read-only CLI role analyses, persist every result, and enforce one aggregate deadline."""
    if type(seconds) is not int or not 1 <= seconds <= 600:
        raise ValueError("seconds must be between 1 and 600")
    if type(max_parallel) is not int or not 1 <= max_parallel <= 2:
        raise ValueError("max_parallel must be 1 or 2")
    specification = plan(task, roles)
    output = (Path(outputDir).resolve() if outputDir else ROOT / "runs/agent-delegation" / uuid.uuid4().hex)
    approved = (ROOT / "runs").resolve()
    if not output.is_relative_to(approved):
        raise ValueError("outputDir must be under repository runs/")
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    (output / "task.txt").write_text(task)
    manifest = {"state": "running", "started_at": _now(), "output_dir": str(output),
        "seconds": seconds, "max_parallel": max_parallel, "plan": specification,
        "roles": [], "inference_performed": False}
    _atomic(output / "manifest.json", manifest)
    deadline = time.monotonic() + seconds
    with ThreadPoolExecutor(max_workers=max_parallel) as pool:
        futures = [pool.submit(_run_role, {**assignment, "parent_task_id": specification.get("task_id", "task_" + hashlib.sha256(task.encode()).hexdigest()[:16])}, task, output, deadline)
                   for assignment in specification["roles"]]
        results = [future.result() for future in futures]
    manifest.update(state="completed" if all(item["state"] == "completed" for item in results) else "partial",
        finished_at=_now(), roles=results,
        inference_performed=any(item.get("inference_performed") for item in results))
    _atomic(output / "manifest.json", manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("inventory")
    for action in ("plan", "run"):
        command = sub.add_parser(action)
        command.add_argument("task")
        command.add_argument("--roles", default="planner,reviewer")
        if action == "run":
            command.add_argument("--seconds", type=int, default=180)
            command.add_argument("--max-parallel", type=int, default=2)
            command.add_argument("--output-dir")
    args = parser.parse_args()
    try:
        if args.action == "inventory":
            result = inventory()
        elif args.action == "plan":
            result = plan(args.task, args.roles.split(","))
        else:
            result = run(args.task, args.roles.split(","), args.output_dir, args.seconds, args.max_parallel)
        print(json.dumps({"ok": True, "result": result}, allow_nan=False))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)[:1000]}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
