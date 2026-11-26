"""Executor wiring must carry selected host guidance and the standalone MCP."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from harness2 import mcp_workflow as workflow
from harness2.mcp_control_cli import dispatch

class HostExecutorWiringTests(unittest.TestCase):
    def test_executor_receives_selected_context_and_local_mcp(self):
        parameters = workflow.validate("ollama_local", "data_entry_keyers", 1, 1, "parallel", 1, 60, "RF Wilkinson PCB")
        selected = {"context": "Source: /verified/RF/SKILL.md\nRF verification procedure", "skills": [{"name": "RF"}]}
        with tempfile.TemporaryDirectory() as directory, patch("harness2.host_capabilities.host_capabilities_plan", return_value=selected) as select:
            env = workflow.environment(parameters, Path(directory))
            config = json.loads(env["OPENCODE_CONFIG_CONTENT"])
            select.assert_called_once_with("RF Wilkinson PCB")
            server = config["mcp"]["host-engineering"]
            self.assertEqual(server["type"], "local")
            self.assertEqual(server["command"][-3:], ["-m", "harness2.host_capabilities", "serve"])
            self.assertTrue(server["enabled"])
            context = Path(config["instructions"][0]).read_text()
            self.assertIn("RF verification procedure", context)
            self.assertIn("references", context)
            self.assertEqual(json.loads((Path(directory) / "host-capability-plan.json").read_text()), selected)

    def test_preparation_is_inside_supervised_process(self):
        parameters = workflow.validate("ollama_local", "data_entry_keyers", 1, 1, "parallel", 1, 1, "CAD")
        with patch.object(workflow, "environment", side_effect=AssertionError("must not prepare in supervisor parent")):
            argv = workflow.supervised_command(parameters, Path("/tmp/run"))
        self.assertEqual(argv[1:4], ["-m", "harness2.mcp_workflow", "--execute"])
        self.assertEqual(json.loads(argv[4]), parameters)

    def test_controller_routes_query_and_rejects_nontext_or_oversized_context_query(self):
        for query in (False, "x"*1025, "RF\ninjected"):
            with self.assertRaises(ValueError):
                workflow.validate("ollama_local", "data_entry_keyers", 1, 1, "parallel", 1, 60, query)
        with patch.object(workflow, "plan", return_value={"ok": True}) as plan:
            result = dispatch({"action":"plan_run", "arguments":{"capability_query":"Android screen capture"}})
            self.assertTrue(result["ok"])
            self.assertEqual(plan.call_args.args[0]["capability_query"], "Android screen capture")

if __name__ == "__main__":
    unittest.main()
