"""Controller worker contracts; every native CLI delegation call is mocked."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from harness2 import delegation_worker as worker
from harness2 import mcp_server as controller


class DelegationWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run_id = "a" * 32
        self.directory = self.root / self.run_id
        self.directory.mkdir()
        self.job = {"kind": "agent_delegation", "task": "Compare two software designs",
                    "roles": ["planner", "reviewer"], "max_parallel": 2, "seconds": 40}
        self.save_job()
        self.runs = patch.object(controller, "RUNS", self.root)
        self.runs.start()
        self.addCleanup(self.runs.stop)

    def save_job(self):
        (self.directory / "job.json").write_text(json.dumps(self.job))

    def report(self):
        return json.loads((self.directory / "workflow/workflow.json").read_text())

    def manifest(self, state="completed"):
        return {"state": state, "inference_performed": True, "roles": [{
            "role": "planner", "route": "codex_chatgpt", "provider": "ChatGPT",
            "state": "completed", "exit_code": 0, "model": "selected-default",
            "reported_usage": {"input_tokens": 10, "output_tokens": 5},
            "output": "Analytical comparison; no tests were executed",
        }]}

    def test_completed_job_calls_fixed_directory_and_retains_raw_role_artifacts(self):
        manifest = self.manifest()
        def delegate(task, roles, **kwargs):
            output = Path(kwargs["outputDir"])
            (output / "planner").mkdir(parents=True)
            (output / "manifest.json").write_text(json.dumps(manifest))
            (output / "planner/stdout.log").write_text("raw fixture event")
            return manifest
        with patch.object(worker.agent_delegation, "run", side_effect=delegate) as run:
            code = worker.run_worker(self.run_id)
        self.assertEqual(code, 0)
        run.assert_called_once_with(self.job["task"], self.job["roles"],
            outputDir=str(self.directory / "delegation"), seconds=40, max_parallel=2)
        report = self.report()
        self.assertEqual(report["kind"], "agent_delegation")
        self.assertEqual(report["state"], "completed")
        self.assertEqual(report["method"], "nativeCLIroledelegation")
        self.assertTrue(report["inference_performed"])
        self.assertFalse(report["engineering_validation_performed"])
        self.assertEqual(report["roles"][0]["reported_usage"]["output_tokens"], 5)
        self.assertEqual(Path(report["roles"][0]["stdout_file"]).read_text(), "raw fixture event")
        self.assertEqual(json.loads(Path(report["manifest_path"]).read_text()), manifest)
        self.assertEqual(json.loads((self.directory / "job.json").read_text()), self.job)
        self.assertNotIn("qualified", report)
        self.assertNotIn("core_summary", report)

    def test_noncompleted_manifest_always_exits_nonzero(self):
        for state in ["partial", "failed", "timed_out", "cancelled", "running"]:
            with patch.object(worker.agent_delegation, "run", return_value=self.manifest(state)):
                self.assertEqual(worker.run_worker(self.run_id), 1)
            self.assertEqual(self.report()["state"], state)

    def test_report_bounds_redacts_secrets_and_preserves_reported_model(self):
        manifest = self.manifest("partial")
        record = manifest["roles"][0]
        record.update(output="fixture-secret-value " + "x" * 9000,
                      error="Bearer sensitive-fixture-token " + "y" * 2000,
                      reported_models=["actual-provider-model"],
                      reported_usage={"input_tokens": 12, "bad": "unknown", "infinite": float("inf")})
        with patch.dict(os.environ, {"OPENAI_API_KEY": "fixture-secret-value"}), \
                patch.object(worker.agent_delegation, "run", return_value=manifest):
            self.assertEqual(worker.run_worker(self.run_id), 1)
        report = self.report()
        self.assertLessEqual(len(report["roles"][0]["output_preview"]), 4000)
        self.assertLessEqual(len(report["roles"][0]["error"]), 1000)
        self.assertNotIn("fixture-secret-value", json.dumps(report))
        self.assertNotIn("sensitive-fixture-token", json.dumps(report))
        self.assertEqual(report["roles"][0]["reported_usage"], {"input_tokens": 12})
        self.assertEqual(report["roles"][0]["reported_models"], ["actual-provider-model"])

    def test_exception_writes_failure_report_with_partial_evidence(self):
        output = self.directory / "delegation"
        output.mkdir()
        (output / "manifest.json").write_text(json.dumps(self.manifest("running")))
        with patch.object(worker.agent_delegation, "run", side_effect=RuntimeError("Fixture execution failed")):
            self.assertEqual(worker.run_worker(self.run_id), 1)
        report = self.report()
        self.assertEqual(report["state"], "failed")
        self.assertTrue(report["inference_performed"])
        self.assertEqual(len(report["roles"]), 1)
        self.assertIn("RuntimeError", report["error"])
        self.assertFalse(report["engineering_validation_performed"])

    def test_wrong_kind_unknown_run_and_paths_never_delegate(self):
        with patch.object(worker.agent_delegation, "run") as run:
            for invalid in ["../../outside", "uuid-with-dashes", "b" * 32]:
                with self.assertRaises(ValueError):
                    worker.run_worker(invalid)
            self.job["kind"] = "demo"
            self.save_job()
            with self.assertRaisesRegex(ValueError, "not an agent_delegation"):
                worker.run_worker(self.run_id)
            run.assert_not_called()
        self.assertFalse((self.directory / "workflow").exists())

    def test_invalid_persisted_limits_and_roles_do_not_launch(self):
        baseline = self.job.copy()
        for change in [{"seconds": 0}, {"seconds": 601}, {"seconds": True},
                       {"max_parallel": 3}, {"task": ""}, {"task": 12},
                       {"roles": ["planner", "planner"]}, {"roles": ["shell"]},
                       {"roles": [{"path": "/bin/sh"}]}]:
            self.job = {**baseline, **change}
            self.save_job()
            with patch.object(worker.agent_delegation, "run") as run:
                self.assertEqual(worker.run_worker(self.run_id), 1)
                run.assert_not_called()
            self.assertEqual(self.report()["state"], "failed")

    def test_default_roles_and_parallel_are_forwarded_from_job(self):
        self.job.pop("roles")
        self.job.pop("max_parallel")
        self.save_job()
        with patch.object(worker.agent_delegation, "run", return_value=self.manifest()) as run:
            self.assertEqual(worker.run_worker(self.run_id), 0)
        self.assertIsNone(run.call_args.args[1])
        self.assertEqual(run.call_args.kwargs["max_parallel"], 2)

    def test_cli_accepts_only_run_id_and_uses_return_code(self):
        with patch.object(worker, "run_worker", return_value=1) as run:
            self.assertEqual(worker.main(["--run-id", self.run_id]), 1)
            run.assert_called_once_with(self.run_id)
        with patch.object(worker, "run_worker") as run, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                worker.main(["--run-id", self.run_id, "--task", "not permitted"])
            self.assertEqual(error.exception.code, 2)
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
