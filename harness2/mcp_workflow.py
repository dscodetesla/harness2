"""Fixed JobBench command/profile construction shared by MCP workers; no shell."""
from __future__ import annotations
import json
from pathlib import Path
import re
import runpy
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PROFILES = {
    "ollama_local": {"model": "llama3.2-harness:3b", "cloud": False, "context": 16384},
    "ollama_glm_cloud": {"model": "glm-5.3-flash:cloud", "cloud": True, "context": 131072},
}


def validate(profile, domain, max_tasks, k, mode, workers, seconds):
    if profile not in PROFILES:
        raise ValueError("profile must be ollama_local or ollama_glm_cloud")
    if not isinstance(domain, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", domain):
        raise ValueError("domain must be one JobBench domain slug")
    for name, value, lower, upper in (
        ("max_tasks", max_tasks, 1, 5), ("k", k, 1, 3),
        ("workers", workers, 1, 2), ("seconds", seconds, 1, 3600)):
        if type(value) is not int or not lower <= value <= upper:
            raise ValueError(f"{name} must be between {lower} and {upper}")
    if mode not in ("parallel", "sequential"):
        raise ValueError("mode must be parallel or sequential")
    return dict(profile=profile, domain=domain, max_tasks=max_tasks, k=k,
                mode=mode, workers=workers, seconds=seconds)


def environment(parameters, output: Path):
    profile = PROFILES[parameters["profile"]]
    model = profile["model"]
    # Host keys are unnecessary for the loopback Ollama service.
    from .config import scrub_env
    env = scrub_env()
    env.update({
        "HARNESS2_SOLVER_MODEL": "ollama-local/" + model,
        "HARNESS2_IMPROVER_MODEL": "ollama-local/" + model,
        "HARNESS2_JUDGE_MODEL": model,
        "HARNESS2_JUDGE_BASE_URL": "http://127.0.0.1:11434/v1",
        "HARNESS2_JUDGE_API_KEY": "ollama",
        "HARNESS2_RUNS_DIR": str(output.resolve()),
        "OPENCODE_DISABLE_MODELS_FETCH": "1",
        "OPENCODE_DISABLE_AUTOUPDATE": "1",
        "OPENCODE_DISABLE_EXTERNAL_SKILLS": "1",
        "OPENCODE_DISABLE_CLAUDE_CODE": "1",
        "OPENCODE_DISABLE_DEFAULT_PLUGINS": "1",
        "OPENCODE_CONFIG_CONTENT": json.dumps({
            "enabled_providers": ["ollama-local"],
            "provider": {"ollama-local": {
                "npm": "@ai-sdk/openai-compatible",
                "options": {"baseURL": "http://127.0.0.1:11434/v1", "apiKey": "ollama"},
                "models": {model: {"name": model,
                    "limit": {"context": profile["context"], "output": 4096}}}}},
            "agent": {"build": {"steps": 40}},
        }),
    })
    for name in ("OPENCODE_CONFIG", "OPENCODE_CONFIG_DIR", "OPENCODE_TUI_CONFIG",
                 "OPENCODE_MODELS_URL", "OPENCODE_MODELS_PATH"):
        env.pop(name, None)
    for variable, child in (
        ("XDG_CONFIG_HOME", "config"), ("XDG_DATA_HOME", "data"),
        ("XDG_STATE_HOME", "state"), ("OPENCODE_TEST_HOME", "home")):
        path = output / child
        path.mkdir(parents=True, exist_ok=True)
        env[variable] = str(path.resolve())
    return env


def command(parameters, action="refinement", bases=False):
    identity = ["--bench", "jb", "--substrate", "oc", "--k", str(parameters["k"]),
                "--mode", parameters["mode"]]
    if action == "refinement":
        return [sys.executable, "-m", "harness2.cli.run_sweep", *identity,
                "--only-domains", parameters["domain"], "--max-tasks",
                str(parameters["max_tasks"]), "--workers", str(parameters["workers"])]
    if action == "judge":
        return [sys.executable, "-m", "harness2.cli.judge", *identity,
                *(["--bases"] if bases else [])]
    if action == "report":
        return [sys.executable, "-m", "harness2.cli.report", *identity]
    raise ValueError("Unknown fixed workflow action")


def preflight(parameters):
    if parameters["profile"] == "ollama_local":
        check = runpy.run_path(str(ROOT / "scripts" / "check_local_model.py"))
        return check["check_local_model"](required_context=16384)
    return {"model": PROFILES[parameters["profile"]]["model"], "cloud": True,
            "service": "Ollama Cloud", "access_verified": False}


def plan(parameters, output: Path):
    result = subprocess.run(command(parameters) + ["--dry-run"],
        cwd=ROOT, env=environment(parameters, output),
        capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise ValueError("JobBench selection failed: " + (result.stderr or result.stdout)[-2000:])
    tasks = [line.strip().split()[-1] for line in result.stdout.splitlines()
             if re.match(r"^\s*\d+\s+" + re.escape(parameters["domain"]) + r"\s+", line)]
    if not tasks:
        raise ValueError("Selected domain has no installed tasks")
    return {"parameters": parameters, "tasks": tasks, "task_count": len(tasks),
        "execution_rollouts_per_task": 4 * parameters["k"],
        "improver_stages_per_task": 3 * parameters["k"],
        "cloud": PROFILES[parameters["profile"]]["cloud"],
        "external_service": "Ollama Cloud" if PROFILES[parameters["profile"]]["cloud"] else None,
        "data_sent": ["task inputs", "trajectories", "harness files", "deliverables"]
            if PROFILES[parameters["profile"]]["cloud"] else [],
        "wall_seconds_cap": parameters["seconds"],
        "usd_cap_enforced": False, "dry_run": result.stdout[-12000:]}
