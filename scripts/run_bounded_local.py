#!/usr/bin/env python3
"""Bounded local Ollama trial; Linux subreaper also owns detached worker descendants."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def _children():
    """Snapshot descendants, including orphans adopted by this subreaper."""
    parents = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text()
            parents[int(entry.name)] = int(stat[stat.rfind(")") + 2:].split()[1])
        except (OSError, ValueError, IndexError):
            continue
    found = {os.getpid()}
    while True:
        more = {pid for pid, parent in parents.items() if parent in found}
        if more <= found:
            return found - {os.getpid()}
        found |= more


def _signal_children(sig):
    for pid in _children():
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            pass


def _reap():
    while True:
        try:
            pid, _ = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return
        if pid == 0:
            return


def supervise(argv, *, seconds, cwd, env):
    """Own a process tree in this dedicated supervisor process; never use in a server."""
    if sys.platform != "linux":
        raise RuntimeError("Linux /proc and PR_SET_CHILD_SUBREAPER are required")
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "PR_SET_CHILD_SUBREAPER failed")
    interrupted = [False]
    old = {}
    for sig in (signal.SIGINT, signal.SIGTERM):
        old[sig] = signal.signal(sig, lambda *_: interrupted.__setitem__(0, True))
    process = subprocess.Popen(argv, cwd=cwd, env=env, start_new_session=True)
    deadline = time.monotonic() + seconds
    timed_out = False
    try:
        while process.poll() is None:
            if interrupted[0] or time.monotonic() >= deadline:
                timed_out = True
                break
            time.sleep(0.1)
        result = 124 if timed_out else process.returncode
    finally:
        # Cleanup also runs after a normal parent exit: detached workers may remain.
        _signal_children(signal.SIGTERM)
        until = time.monotonic() + 2
        while _children() and time.monotonic() < until:
            process.poll()
            _reap()
            time.sleep(0.05)
        until = time.monotonic() + 5
        while _children() and time.monotonic() < until:
            _signal_children(signal.SIGKILL)
            process.poll()
            _reap()
            time.sleep(0.05)
        remaining = _children()
        for sig, handler in old.items():
            signal.signal(sig, handler)
        if remaining:
            raise RuntimeError(f"Workers still present after cleanup: {sorted(remaining)}")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=int, default=300)
    parser.add_argument("--runs-dir", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 1800:
        parser.error("--seconds must be between 1 and 1800")
    from check_local_model import check_local_model
    evidence = check_local_model(required_context=16384)
    args.runs_dir.mkdir(parents=True, exist_ok=True)
    (args.runs_dir / "model-preflight.json").write_text(json.dumps(evidence, indent=2) + "\n")
    profile = {
        "enabled_providers": ["ollama-local"],
        "provider": {"ollama-local": {
            "npm": "@ai-sdk/openai-compatible",
            "options": {"baseURL": "http://127.0.0.1:11434/v1", "apiKey": "ollama"},
            "models": {"llama3.2-harness:3b": {"name": "Local Llama 3.2 3B",
                "limit": {"context": 16384, "output": 1024}}}}},
        "tools": {"*": False, "read": True, "write": True, "bash": True},
        "agent": {"build": {"steps": 6}}}
    env = {**os.environ,
        "HARNESS2_SOLVER_MODEL": "ollama-local/llama3.2-harness:3b",
        "HARNESS2_IMPROVER_MODEL": "ollama-local/llama3.2-harness:3b",
        "HARNESS2_JUDGE_MODEL": "llama3.2-harness:3b",
        "HARNESS2_JUDGE_BASE_URL": "http://127.0.0.1:11434/v1",
        "HARNESS2_JUDGE_API_KEY": "ollama",
        "HARNESS2_RUNS_DIR": str(args.runs_dir.resolve()),
        "OPENCODE_CONFIG_CONTENT": json.dumps(profile),
        "OPENCODE_DISABLE_MODELS_FETCH": "1",
        "OPENCODE_DISABLE_AUTOUPDATE": "1",
        "OPENCODE_DISABLE_EXTERNAL_SKILLS": "1",
        "OPENCODE_DISABLE_CLAUDE_CODE": "1",
        "OPENCODE_DISABLE_DEFAULT_PLUGINS": "1",
        "XDG_CONFIG_HOME": str(args.runs_dir.resolve() / "config"),
        "XDG_DATA_HOME": str(args.runs_dir.resolve() / "data"),
        "XDG_STATE_HOME": str(args.runs_dir.resolve() / "state"),
        "OPENCODE_TEST_HOME": str(args.runs_dir.resolve() / "home")}
    for name in ("OPENCODE_CONFIG", "OPENCODE_CONFIG_DIR", "OPENCODE_TUI_CONFIG",
                 "OPENCODE_MODELS_URL", "OPENCODE_MODELS_PATH"):
        env.pop(name, None)
    for name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "OPENCODE_TEST_HOME"):
        Path(env[name]).mkdir(parents=True, exist_ok=True)
    command = [sys.executable, "-m", "harness2.cli.run_sweep", "--bench", "jb",
        "--substrate", "oc", "--only-domains", "data_entry_keyers",
        "--max-tasks", "1", "--workers", "1", "--k", "1", "--mode", "parallel"]
    return supervise(command, seconds=args.seconds, cwd=ROOT, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
