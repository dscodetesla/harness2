"""Bridge contract tests; fake subprocesses never execute models or jobs."""
import json
import subprocess
import unittest
from unittest.mock import patch
from integrations import cad_gateway_harness2 as bridge
from harness2 import mcp_control_cli as cli


class MCPBridgeTests(unittest.TestCase):
    def invoke(self, envelope, code=0):
        def fake(*args, **kwargs):
            self.assertEqual(args[0], bridge.COMMAND)
            self.assertEqual(kwargs["timeout"], 45)
            self.assertEqual(json.loads(kwargs["input"]), {"action": "status", "arguments": {}})
            self.assertNotIn("HARNESS2_MCP_RUNS_DIR", kwargs["env"])
            kwargs["stdout"].write(json.dumps(envelope).encode())
            return subprocess.CompletedProcess(args[0], code)
        return fake

    def test_fixed_command_and_success(self):
        with patch.object(bridge.subprocess, "run", self.invoke({"ok": True, "result": {"ready": True}})):
            self.assertEqual(bridge.harness2_status(), {"ready": True})

    def test_controller_error_propagates(self):
        with patch.object(bridge.subprocess, "run", self.invoke({"ok": False, "error": {"message": "Unknown run_id"}}, 1)):
            with self.assertRaisesRegex(RuntimeError, "Unknown run_id"):
                bridge.harness2_status()

    def test_timeout_clean_error(self):
        with patch.object(bridge.subprocess, "run", side_effect=subprocess.TimeoutExpired("fixed", 15)):
            with self.assertRaisesRegex(RuntimeError, "timed out"):
                bridge.harness2_status()

    def test_output_limit(self):
        def fake(*args, **kwargs):
            kwargs["stdout"].write(b"x" * (bridge.MAX_OUTPUT + 1))
            return subprocess.CompletedProcess(args[0], 0)
        with patch.object(bridge.subprocess, "run", fake):
            with self.assertRaisesRegex(RuntimeError, "exceeds limit"):
                bridge.harness2_status()

    def test_action_whitelist_rejects_before_dispatch(self):
        invalid = [
            {"action": "shell", "arguments": {}},
            {"action": "status", "arguments": {"command": "touch bad"}},
            {"action": "start_demo", "arguments": {"k": True}},
            {"action": "start_demo", "arguments": {"seconds": 121}},
            {"action": "results", "arguments": {"run_id": "../outside"}},
            {"action": "cancel", "arguments": {}},
        ]
        for request in invalid:
            with self.subTest(request=request), self.assertRaises(ValueError):
                cli.dispatch(request)

    def test_ten_tools_register_preserving_original_names(self):
        class FakeMCP:
            def __init__(self): self.names = []
            def tool(self): return lambda fn: self.names.append(fn.__name__)
        mcp = FakeMCP()
        bridge.register_tools(mcp)
        self.assertEqual(mcp.names, ["harness2_status", "harness2_start_demo", "harness2_run_status",
                                     "harness2_results", "harness2_cancel", "harness2_plan_run",
                                     "harness2_start_run", "harness2_start_judge", "harness2_report",
                                     "harness2_start_rf_run"])


if __name__ == "__main__":
    unittest.main()
