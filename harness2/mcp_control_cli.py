"""JSON-only action whitelist for an SDK-independent controller subprocess."""
from __future__ import annotations

import json
import sys
from . import mcp_server as controller

ACTIONS = {
    "status": (controller.harness2_status, set()),
    "start_demo": (controller.harness2_start_demo, {"k", "seconds"}),
    "run_status": (controller.harness2_run_status, {"run_id"}),
    "results": (controller.harness2_results, {"run_id"}),
    "cancel": (controller.harness2_cancel, {"run_id"}),
    "plan_run": (controller.harness2_plan_run, {"profile", "domain", "max_tasks", "k", "mode", "workers", "seconds", "capability_query"}),
    "start_run": (controller.harness2_start_run, {"profile", "domain", "max_tasks", "k", "mode", "workers", "seconds", "allow_cloud", "capability_query"}),
    "start_judge": (controller.harness2_start_judge, {"run_id", "bases", "seconds", "allow_cloud"}),
    "report": (controller.harness2_report, {"run_id"}),
    "start_rf_run": (controller.harness2_start_rf_run, {"seconds", "allow_cloud"}),
}
MAX_INPUT = 8192


def dispatch(request):
    if not isinstance(request, dict) or set(request) != {"action", "arguments"}:
        raise ValueError("Expected action and arguments only")
    action, arguments = request["action"], request["arguments"]
    if not isinstance(action, str) or action not in ACTIONS:
        raise ValueError("Unknown controller action")
    function, allowed = ACTIONS[action]
    if not isinstance(arguments, dict) or set(arguments) - allowed:
        raise ValueError("Invalid action arguments")
    if action in ("run_status", "results", "cancel"):
        if set(arguments) != {"run_id"} or not isinstance(arguments["run_id"], str):
            raise ValueError("run_id is required")
        controller._directory(arguments["run_id"])
    if action == "start_demo":
        k, seconds = arguments.get("k", 1), arguments.get("seconds", 60)
        if type(k) is not int or k not in (1, 2):
            raise ValueError("k must be 1 or 2")
        if type(seconds) is not int or not 1 <= seconds <= 120:
            raise ValueError("seconds must be between 1 and 120")
    return function(**arguments)


def main():
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT + 1)
        if len(raw) > MAX_INPUT:
            raise ValueError("Controller request exceeds 8192 bytes")
        result = dispatch(json.loads(raw))
        print(json.dumps({"ok": True, "result": result}, allow_nan=False))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": {
            "type": type(exc).__name__, "message": str(exc)[:1000]}}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
