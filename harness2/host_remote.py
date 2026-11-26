"""Scoped SSH transport for registered engineering hosts; no arbitrary shell API."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import socket
import stat
import subprocess
import sys
import tempfile
import time

HOST_HOME = Path.home()
REGISTRY = HOST_HOME / ".config/harness2/hosts.json"
PYTHON = "/home/user/src/harness2/.venv-mcp/bin/python"
RECEIVER = PYTHON + " -m harness2.host_remote receive"
MAX_REQUEST = 65536
MAX_RESPONSE = 262144
FIELDS = {"id", "hostname", "ssh_host", "ssh_user", "identity_file",
          "known_hosts_file", "python", "inventory_path", "ssh_port"}


class HostRemoteError(ValueError):
    """Public error containing no raw SSH diagnostics or credentials."""


def _bytes(value):
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, RecursionError):
        raise HostRemoteError("Expected finite JSON data") from None


def _private_file(path):
    if path.is_symlink() or not path.is_file():
        raise HostRemoteError("Private transport configuration is unavailable")
    info = path.stat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise HostRemoteError("Private transport file must be owned by this user with mode 0600")


def _registry():
    if not REGISTRY.exists():
        return []
    _private_file(REGISTRY)
    if REGISTRY.stat().st_size > MAX_REQUEST:
        raise HostRemoteError("Host registry exceeds 64 KiB")
    try:
        data = json.loads(REGISTRY.read_text())
    except (OSError, ValueError):
        raise HostRemoteError("Host registry is invalid") from None
    if not isinstance(data, dict) or set(data) != {"version", "hosts"} or data["version"] != 1:
        raise HostRemoteError("Unsupported host registry format")
    if not isinstance(data["hosts"], list) or len(data["hosts"]) > 16:
        raise HostRemoteError("Host registry must contain at most 16 hosts")
    seen = set()
    for item in data["hosts"]:
        if not isinstance(item, dict) or set(item) != FIELDS or any(not isinstance(v, str) for k, v in item.items() if k != "ssh_port"):
            raise HostRemoteError("Host registry entry has invalid fields")
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", item["id"]) or item["id"] in seen:
            raise HostRemoteError("Host registry identifiers must be unique")
        seen.add(item["id"])
        if type(item["ssh_port"]) is not int or not 1 <= item["ssh_port"] <= 65535:
            raise HostRemoteError("Registered SSH port must be an integer from 1 to 65535")
        for key in ("hostname", "ssh_host", "ssh_user"):
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,252}", item[key]):
                raise HostRemoteError("Invalid registered SSH address or user")
        if item["python"] != PYTHON:
            raise HostRemoteError("Remote Python must use the fixed engineering receiver")
        for key in ("identity_file", "known_hosts_file"):
            path = Path(item[key])
            if not path.is_absolute() or not path.resolve().is_relative_to((HOST_HOME / ".config/harness2/ssh").resolve()):
                raise HostRemoteError("SSH transport files must be under the private transport directory")
        cache = Path(item["inventory_path"])
        approved = (HOST_HOME / "src/harness2-host-capabilities-private/evidence").resolve()
        if not cache.is_absolute() or not cache.resolve().is_relative_to(approved):
            raise HostRemoteError("Inventory cache must be under the private evidence directory")
    return data["hosts"]


def _request(operation, arguments):
    if not isinstance(arguments, dict):
        raise HostRemoteError("Remote arguments must be an object")
    if operation == "inventory":
        if arguments:
            raise HostRemoteError("Remote inventory takes no arguments")
    elif operation == "plan":
        if not {"query"} <= set(arguments) <= {"query", "max_skills", "budget_chars"}:
            raise HostRemoteError("Remote plan requires query and optional bounded selection limits")
        if not isinstance(arguments["query"], str) or not 1 <= len(arguments["query"].strip()) <= 2000:
            raise HostRemoteError("Remote query must contain 1..2000 characters")
        for key, lower, upper in (("max_skills", 1, 5), ("budget_chars", 1000, 16000)):
            if key in arguments and (type(arguments[key]) is not int or not lower <= arguments[key] <= upper):
                raise HostRemoteError("Remote selection limit is outside its supported range")
    elif operation == "execute":
        if not {"action"} <= set(arguments) <= {"action", "parameters"}:
            raise HostRemoteError("Remote execute requires action and optional parameters")
        if not isinstance(arguments["action"], str) or arguments["action"] == "remote_call":
            raise HostRemoteError("Remote recursion is forbidden")
        if not isinstance(arguments.get("parameters", {}), dict):
            raise HostRemoteError("Remote execute parameters must be an object")
    else:
        raise HostRemoteError("Unknown remote operation; choose inventory, plan or execute")
    request = {"version": 1, "operation": operation, "arguments": arguments}
    if len(_bytes(request)) > MAX_REQUEST:
        raise HostRemoteError("Remote request exceeds 64 KiB")
    return request


def host_catalog():
    """Return configuration and cached observations; never initiate SSH."""
    records = []
    for item in _registry():
        record = {"id": item["id"], "hostname": item["hostname"],
                  "transport_configured": all(Path(item[k]).is_file() for k in ("identity_file", "known_hosts_file")),
                  "live_verified": False, "inventory_status": "unavailable",
                  "inventory_path": item["inventory_path"]}
        path = Path(item["inventory_path"])
        try:
            if path.is_file() and path.stat().st_size <= MAX_RESPONSE:
                cache = json.loads(path.read_text())
                inventory = cache.get("result", cache)
                if isinstance(inventory, dict) and inventory.get("host") == item["hostname"]:
                    record.update(cached_inventory=inventory, inventory_status="cached",
                        inventory_observed_at=cache.get("observed_at") or datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
                        inventory_observation_source="remote_reply" if cache.get("observed_at") else "cache_file_mtime",
                        cache_is_live_readiness=False)
        except (OSError, ValueError, TypeError, AttributeError):
            record["inventory_status"] = "invalid_cache"
        records.append(record)
    return records


def call(host, operation, arguments):
    """Call only the fixed forced-command receiver on a configured host."""
    if os.environ.get("HARNESS2_REMOTE_RECEIVE") == "1":
        raise HostRemoteError("Remote recursion is forbidden")
    if not isinstance(host, str):
        raise HostRemoteError("Remote host must be a registered identifier")
    request = _request(operation, arguments)
    target = next((entry for entry in _registry() if entry["id"] == host), None)
    if target is None:
        raise HostRemoteError("Remote host is not registered")
    for key in ("identity_file", "known_hosts_file"):
        _private_file(Path(target[key]))
    argv = ["/usr/bin/ssh", "-p", str(target["ssh_port"]), "-T", "-F", "/dev/null",
            "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
            "-o", "IdentitiesOnly=yes", "-o", "ConnectTimeout=5",
            "-o", "ConnectionAttempts=1", "-o", "GlobalKnownHostsFile=/dev/null",
            "-o", "UserKnownHostsFile=" + target["known_hosts_file"],
            "-i", target["identity_file"], target["ssh_user"] + "@" + target["ssh_host"], RECEIVER]
    started = time.monotonic()
    try:
        with tempfile.TemporaryFile() as stdout:
            completed = subprocess.run(argv, input=_bytes(request), stdout=stdout,
                stderr=subprocess.DEVNULL, timeout=120, check=False,
                env={"HOME": str(HOST_HOME), "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"})
            if completed.returncode:
                raise HostRemoteError("Remote transport failed; check the registered connection and pinned host key")
            if stdout.tell() > MAX_RESPONSE:
                raise HostRemoteError("Remote response exceeds 256 KiB")
            stdout.seek(0)
            raw = stdout.read(MAX_RESPONSE + 1)
    except subprocess.TimeoutExpired:
        raise HostRemoteError("Remote operation deadline exceeded") from None
    except OSError:
        raise HostRemoteError("Remote transport is unavailable") from None
    try:
        reply = json.loads(raw)
    except (ValueError, UnicodeError):
        raise HostRemoteError("Remote receiver returned invalid JSON") from None
    if (not isinstance(reply, dict) or reply.get("version") != 1
            or reply.get("hostname") != target["hostname"] or reply.get("operation") != operation):
        raise HostRemoteError("Remote receiver identity or operation mismatch")
    if reply.get("ok") is not True or not isinstance(reply.get("result"), dict):
        raise HostRemoteError("Remote registered operation failed")
    return {"ok": True, "host": host, "operation": operation, "result": reply["result"],
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "transport": "ssh-forced-command", "transport_verified": True}


def receive(raw=None):
    """Accept exactly one bounded request; dispatch only the local host API."""
    raw = sys.stdin.buffer.read(MAX_REQUEST + 1) if raw is None else raw
    operation = None
    try:
        if len(raw) > MAX_REQUEST:
            raise HostRemoteError("Remote request exceeds 64 KiB")
        request = json.loads(raw)
        if not isinstance(request, dict) or set(request) != {"version", "operation", "arguments"} or request["version"] != 1:
            raise HostRemoteError("Invalid remote request envelope")
        operation = request["operation"]
        _request(operation, request["arguments"])
        os.environ["HARNESS2_REMOTE_RECEIVE"] = "1"
        from . import host_capabilities
        functions = {"inventory": host_capabilities.inventory,
                     "plan": host_capabilities.plan, "execute": host_capabilities.execute}
        result = functions[operation](**request["arguments"])
        reply = {"version": 1, "ok": True, "hostname": socket.gethostname(),
                 "operation": operation, "result": result}
        if len(_bytes(reply)) > MAX_RESPONSE:
            raise HostRemoteError("Remote response exceeds 256 KiB")
        return reply
    except Exception:
        return {"version": 1, "ok": False, "hostname": socket.gethostname(),
                "operation": operation if isinstance(operation, str) else None,
                "error": "Registered remote operation failed"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("receive", "catalog", "call"))
    parser.add_argument("host", nargs="?")
    parser.add_argument("operation", nargs="?")
    options = parser.parse_args()
    try:
        if options.action == "receive":
            reply = receive()
        elif options.action == "catalog":
            reply = {"hosts": host_catalog()}
        else:
            raw = sys.stdin.buffer.read(MAX_REQUEST + 1)
            if len(raw) > MAX_REQUEST:
                raise HostRemoteError("Remote request exceeds 64 KiB")
            reply = call(options.host, options.operation, json.loads(raw))
        print(json.dumps(reply, ensure_ascii=False, allow_nan=False))
        return 1 if reply.get("ok") is False else 0
    except (HostRemoteError, ValueError):
        print(json.dumps({"ok": False, "error": "Registered remote operation failed"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
