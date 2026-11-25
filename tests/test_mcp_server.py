"""Controller lifecycle tests; no SDK or model inference required."""
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from harness2 import mcp_server as controller


class MCPControllerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.runs = Path(self.temporary.name)
        self.override = patch.object(controller, "RUNS", self.runs)
        self.override.start()
        self.addCleanup(self.override.stop)
        self.environment = patch.dict(os.environ, {"HARNESS2_MCP_RUNS_DIR": str(self.runs)})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def wait_terminal(self, run_id):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            job = controller.harness2_run_status(run_id)
            if job["state"] not in ("starting", "running", "cancelling"):
                return job
            time.sleep(0.05)
        self.fail("Worker failed to finish")

    def test_demo_result_survives_controller_reload(self):
        job = controller.harness2_start_demo(k=1)
        with self.assertRaisesRegex(ValueError, "already active"):
            controller.harness2_start_demo()
        terminal = self.wait_terminal(job["run_id"])
        self.assertEqual(terminal["state"], "succeeded", terminal)
        result = controller.harness2_results(job["run_id"])
        self.assertEqual(result["demo"]["done"], 2)
        self.assertEqual(result["demo"]["failed"], 0)
        self.assertEqual(result["job"]["exit_code"], 0)

    def test_cancel_and_reject_invalid_ids_or_pid_identity(self):
        for value in ("../other", "", "f" * 31):
            with self.assertRaises(ValueError):
                controller.harness2_run_status(value)
        job = controller.harness2_start_demo(k=2)
        response = controller.harness2_cancel(job["run_id"])
        self.assertEqual(response["state"], "cancelling")
        terminal = self.wait_terminal(job["run_id"])
        self.assertEqual(terminal["state"], "cancelled", terminal)
        # A stale PID/start tick must never be signalled.
        stale_id = "f" * 32
        (self.runs / stale_id).mkdir()
        controller._write(stale_id, {"run_id": stale_id, "state": "running",
            "pid": os.getpid(), "start_ticks": "incorrect"})
        stale = controller.harness2_cancel(stale_id)
        self.assertEqual(stale["state"], "interrupted")

    def test_timeout_is_terminal(self):
        job = controller.harness2_start_demo(k=2, seconds=1)
        terminal = self.wait_terminal(job["run_id"])
        self.assertEqual(terminal["state"], "timed_out", terminal)
        self.assertEqual(terminal["exit_code"], 124)

    def test_rejects_unbounded_arguments(self):
        for kwargs in ({"k": 0}, {"k": True}, {"seconds": 0}, {"seconds": 121}):
            with self.assertRaises(ValueError):
                controller.harness2_start_demo(**kwargs)


if __name__ == "__main__":
    unittest.main()
