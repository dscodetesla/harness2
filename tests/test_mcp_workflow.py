"""Real workflow routing tests; dry-run and mocks never invoke a model."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from harness2 import mcp_server as controller, mcp_workflow as workflow, routing_policy
from harness2.mcp_control_cli import dispatch


class MCPWorkflowTests(unittest.TestCase):
    def test_validation_rejects_shell_paths_and_unbounded_values(self):
        values = dict(profile="ollama_local", domain="data_entry_keyers", max_tasks=1,
                      k=1, mode="parallel", workers=1, seconds=300)
        for change in ({"domain": "../other"}, {"domain": "x;id"}, {"max_tasks": 6},
                       {"k": True}, {"workers": 0}, {"seconds": 3601}, {"mode": "both"},
                       {"profile": "arbitrary/model"}):
            with self.assertRaises(ValueError):
                workflow.validate(**{**values, **change})

    def test_named_profile_fixed_argv_and_secret_scrubbing(self):
        p = workflow.validate("ollama_local", "data_entry_keyers", 1, 2, "sequential", 1, 90)
        argv = workflow.command(p)
        self.assertEqual(argv[2], "harness2.cli.run_sweep")
        self.assertIn("--only-domains", argv)
        self.assertEqual(argv[argv.index("--max-tasks") + 1], "1")
        self.assertIn("--bases", workflow.command(p, "judge", True))
        self.assertEqual(workflow.command(p, "report")[2], "harness2.cli.report")
        with tempfile.TemporaryDirectory() as td:
            with patch.dict(os.environ, {"GITHUB_TOKEN": "must-not-inherit",
                                         "OPENCODE_CONFIG": "/host/private.json"}):
                env = workflow.environment(p, Path(td))
            self.assertNotIn("GITHUB_TOKEN", env)
            self.assertNotIn("OPENCODE_CONFIG", env)
            self.assertEqual(env["HARNESS2_SOLVER_MODEL"], "ollama-local/llama3.2-harness:3b")
            self.assertEqual(env["HARNESS2_RUNS_DIR"], td)

    def test_cloud_starts_require_explicit_consent_before_side_effects(self):
        with tempfile.TemporaryDirectory() as td, patch.object(routing_policy,"POLICY_PATH",Path(td)/"missing.json"), patch.object(controller, "_start_job") as launch:
            with self.assertRaisesRegex(ValueError, "Cloud"):
                controller.harness2_start_run(profile="ollama_glm_cloud")
            # No stored consent in this fixture; a default cloud request is denied.
            launch.assert_not_called()

    def test_rf_default_is_local_and_cloud_requires_explicit_true(self):
        with patch.object(controller, "_start_job", return_value={"run_id":"x"}) as launch, patch.object(controller, "rf_local_profile", return_value="ollama_local"):
            controller.harness2_start_rf_run(allow_cloud=False)
            self.assertEqual(launch.call_args.args[1]["profile"], "ollama_local")
            self.assertFalse(launch.call_args.args[1]["allow_cloud"])
            controller.harness2_start_rf_run(allow_cloud=True)
            self.assertEqual(launch.call_args.args[1]["profile"], "ollama_glm_cloud")
        with self.assertRaises(ValueError):
            controller.harness2_start_rf_run(allow_cloud="false")

    def test_rf_profile_configuration_cannot_enable_cloud_implicitly(self):
        import json
        with tempfile.TemporaryDirectory() as td, patch.object(controller, "RF_PROFILE_FILE", Path(td)/"rf.json"):
            self.assertEqual(controller.rf_local_profile(),"ollama_local")
            controller.RF_PROFILE_FILE.write_text(json.dumps({"profile":"ollama_gemma_local"}))
            self.assertEqual(controller.rf_local_profile(),"ollama_gemma_local")
            controller.RF_PROFILE_FILE.write_text(json.dumps({"profile":"ollama_glm_cloud"}))
            with self.assertRaises(ValueError):
                controller.rf_local_profile()

    def test_dry_run_uses_installed_real_jobbench_selection(self):
        with tempfile.TemporaryDirectory() as td, patch.object(controller, "RUNS", Path(td)):
            result = dispatch({"action": "plan_run", "arguments": {
                "domain": "data_entry_keyers", "max_tasks": 1, "profile":"ollama_local"}})
        self.assertEqual(result["tasks"], ["data_entry_keyers/task1"])
        self.assertEqual(result["execution_rollouts_per_task"], 4)
        self.assertFalse(result["cloud"])

    def test_start_real_run_passes_validated_job_to_persisted_manager(self):
        with patch.object(workflow, "plan", return_value={"tasks": ["domain/task"]}), \
             patch.object(workflow, "preflight", return_value={"local_only": True}), \
             patch.object(controller, "_start_job", return_value={"run_id": "id"}) as launch:
            result = controller.harness2_start_run(profile="ollama_local",seconds=120)
        self.assertEqual(result["run_id"], "id")
        self.assertEqual(launch.call_args.args[0], "refinement")
        self.assertEqual(launch.call_args.args[1]["parameters"]["profile"], "ollama_local")
        self.assertEqual(launch.call_args.args[2], 120)

    def test_judge_inherits_source_profile_and_refuses_cloud_without_consent(self):
        source = {"kind": "refinement", "state": "failed",
                  "parameters": {"profile": "ollama_glm_cloud", "k": 2, "mode": "sequential"}}
        with patch.object(controller, "harness2_run_status", return_value=source), \
             patch.object(controller, "_start_job", return_value={"state": "running"}) as launch:
            with self.assertRaises(ValueError):
                controller.harness2_start_judge("a" * 32,allow_cloud=False)
            controller.harness2_start_judge("a" * 32, bases=True, allow_cloud=True)
            self.assertEqual(launch.call_args.args[0], "judge")
            self.assertTrue(launch.call_args.args[1]["bases"])
            self.assertEqual(launch.call_args.args[1]["parameters"], source["parameters"])


    def test_results_budget_and_partial_json_are_reported_without_bridge_failure(self):
        import json
        with tempfile.TemporaryDirectory() as td, patch.object(controller, "RUNS", Path(td)):
            rid = "a" * 32
            directory = Path(td) / rid
            (directory / "workflow" / "task").mkdir(parents=True)
            controller._write(rid, {"run_id": rid, "kind": "refinement", "state": "failed"})
            (directory / "workflow" / "workflow.json").write_text(json.dumps({"large": "x" * 130000}))
            (directory / "workflow" / "task" / "summary.json").write_text('{"unfinished":')
            value = controller.harness2_results(rid)
            self.assertTrue(value["artifacts_truncated"])
            self.assertEqual(value["summaries"], [])
            self.assertLess(len(json.dumps(value).encode()), 256000)
            states = {item["state"] for item in value["artifact_manifest"]}
            self.assertEqual(states, {"omitted_size_budget", "unreadable_or_in_progress"})


    def test_status_qualification_requires_successful_independent_core_evidence(self):
        import json
        with tempfile.TemporaryDirectory() as td, patch.object(controller, "RUNS", Path(td)), \
             patch.object(controller.runpy, "run_path", return_value={"check_local_model": lambda **kw: {"local_only": True}}), patch.object(controller, "rf_local_profile", return_value="ollama_local"):
            rid = "b" * 32
            directory = Path(td) / rid
            (directory / "workflow").mkdir(parents=True)
            controller._write(rid, {"run_id": rid, "kind": "rf_refinement", "state": "succeeded"})
            proof = {"qualified": True, "external_model": "glm-5.3-flash:cloud",
                     "core_summary": {"status": "partial", "errors": []},
                     "selected_score": {"passed": True}}
            path = directory / "workflow" / "workflow.json"
            path.write_text(json.dumps(proof))
            self.assertFalse(controller.harness2_status()["model_refinement_qualified"])
            proof["core_summary"]["status"] = "ok"
            path.write_text(json.dumps(proof))
            status = controller.harness2_status()
            self.assertTrue(status["model_refinement_qualified"])
            self.assertFalse(status["local_model_refinement_qualified"])
            self.assertTrue(status["qualified_workflows"][0]["synthetic_only"])
            proof.update(local_only=True, external_model="llama3.2-harness:3b", heldout={"qualified":True,"passed":56})
            path.write_text(json.dumps(proof))
            self.assertTrue(controller.harness2_status()["local_model_refinement_qualified"])
            with patch.object(controller,"rf_local_profile",return_value="ollama_gemma_local"):
                self.assertFalse(controller.harness2_status()["local_model_refinement_qualified"])
                proof["external_model"]="gemma3-harness:4b"
                path.write_text(json.dumps(proof))
                self.assertTrue(controller.harness2_status()["local_model_refinement_qualified"])
            proof["external_model"]="llama3.2-harness:3b"
            proof["heldout"]={"qualified":False,"passed":40}
            path.write_text(json.dumps(proof))
            self.assertFalse(controller.harness2_status()["local_model_refinement_qualified"])


if __name__ == "__main__":
    unittest.main()
