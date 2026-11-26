"""CLI delegation contracts and process lifecycle without model inference."""
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

from harness2 import agent_delegation as delegation


class AgentDelegationTests(unittest.TestCase):
    def assignment(self, role="planner", route="ollama_cloud_glm"):
        return {"role": role, "scope": "Synthetic read-only test", "route": route,
                "provider": "fixture", "model": "fixture", "executable": sys.executable,
                "ready_for_trial": True, "status": "fixture"}

    def test_inventory_has_all_requested_clients_and_never_assumes_auth(self):
        with patch.object(delegation.shutil, "which", return_value="/installed/cli"):
            state = delegation._route_state("codex_chatgpt", {})
            self.assertFalse(state["ready_for_trial"])
            state = delegation._route_state("claude_subscription", {})
            self.assertFalse(state["ready_for_trial"])
        self.assertEqual(len(delegation.CLI_NAMES), 17)

    def test_subscription_routes_require_actual_auth_and_help_contract(self):
        entries = {
            "codex": {"auth_evidence": {"exit_code": 0, "chatgpt_login_verified": True},
                "subcommand_help": {"exec": {"exit_code": 0, "text":
                    "--sandbox --skip-git-repo-check --json --ignore-user-config --ephemeral"}}},
            "claude": {"auth_evidence": {"exit_code": 0, "loggedIn": True,
                "authMethod": "claude.ai", "apiProvider": "firstParty"},
                "help": {"exit_code": 0, "text":
                    "--tools --strict-mcp-config --mcp-config --output-format --permission-mode --no-session-persistence"}},
        }
        with patch.object(delegation.shutil, "which", return_value="/installed/cli"):
            self.assertTrue(delegation._route_state("codex_chatgpt", entries)["ready_for_trial"])
            self.assertTrue(delegation._route_state("claude_subscription", entries)["ready_for_trial"])
            entries["codex"]["auth_evidence"]["chatgpt_login_verified"] = False
            self.assertFalse(delegation._route_state("codex_chatgpt", entries)["ready_for_trial"])

    def test_policy_accepts_only_named_roles_registered_routes(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(delegation, "POLICY", Path(temp) / "roles.json"):
            delegation.POLICY.write_text(json.dumps({"roles": {"reviewer": "codex_chatgpt"}}))
            self.assertEqual(delegation._policy()["reviewer"], "codex_chatgpt")
            delegation.POLICY.write_text(json.dumps({"roles": {"reviewer": "shell:rm"}}))
            with self.assertRaises(ValueError):
                delegation._policy()
        for roles in ([], ["planner", "planner"], ["shell"], [{}]):
            with self.assertRaises(ValueError):
                delegation._roles(roles)

    def test_fixed_native_routes_have_no_yolo_and_use_stdin_no_ambient_provider(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            codex, transport = delegation._argv(self.assignment(route="codex_chatgpt"), "prompt", path)
            self.assertEqual(transport, "stdin")
            self.assertIn("--ignore-user-config", codex)
            self.assertIn("read-only", codex)
            claude, transport = delegation._argv(self.assignment(route="claude_subscription"), "prompt", path)
            self.assertEqual(transport, "stdin")
            self.assertIn("--strict-mcp-config", claude)
            self.assertEqual(claude[claude.index("--tools") + 1], "")
            for argv in (codex, claude):
                self.assertFalse(any("yolo" in arg or "bypass" in arg for arg in argv))

    def test_run_persists_parallel_role_prompts_results_and_scrubs_environment(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            roles = [self.assignment(), self.assignment("reviewer")]
            specification = {"roles": roles}
            command = [sys.executable, "-c",
                "import os; assert 'OPENAI_API_KEY' not in os.environ; assert 'ANTHROPIC_BASE_URL' not in os.environ; print('Synthetic role response')"]
            with patch.object(delegation, "ROOT", root), \
                 patch.object(delegation, "plan", return_value=specification), \
                 patch.object(delegation, "_argv", return_value=(command, "argv")), \
                 patch.dict(os.environ, {"OPENAI_API_KEY": "fixture-not-a-secret", "ANTHROPIC_BASE_URL": "https://not-used.invalid"}):
                result = delegation.run("Synthetic arithmetic task", ["planner", "reviewer"],
                    str(root / "runs/job"), seconds=5, max_parallel=2)
            self.assertEqual(result["state"], "completed")
            self.assertEqual(len(result["roles"]), 2)
            for record in result["roles"]:
                self.assertEqual(record["exit_code"], 0)
                self.assertEqual(record["output"].strip(), "Synthetic role response")
                directory = Path(record["prompt_path"]).parent
                self.assertTrue((directory / "result.json").is_file())
                self.assertIn("ROLE:", (directory / "prompt.txt").read_text())
                self.assertFalse(record["engineering_validation_performed"])

    def test_aggregate_deadline_stops_process_group_without_retry(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            assignment = self.assignment()
            command = [sys.executable, "-c", "import time; time.sleep(60)"]
            with patch.object(delegation, "ROOT", root), \
                 patch.object(delegation, "plan", return_value={"roles": [assignment]}), \
                 patch.object(delegation, "_argv", return_value=(command, "argv")) as builder:
                result = delegation.run("Synthetic deadline", ["planner"],
                    str(root / "runs/job"), seconds=1, max_parallel=1)
            self.assertEqual(result["state"], "partial")
            self.assertEqual(result["roles"][0]["state"], "timed_out")
            builder.assert_called_once()

    def test_rejects_unbounded_values_paths_and_unverified_routes_before_spawn(self):
        with self.assertRaises(ValueError):
            delegation.run("task", seconds=0)
        with self.assertRaises(ValueError):
            delegation.run("task", max_parallel=3)
        with patch.object(delegation, "plan", return_value={"roles": []}):
            with self.assertRaises(ValueError):
                delegation.run("task", outputDir="/tmp/not-repository-runs")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            assignment = {**self.assignment(), "ready_for_trial": False}
            result = delegation._run_role(assignment, "task", root, 1e99)
            self.assertEqual(result["state"], "blocked")
            self.assertFalse(result["inference_performed"])


    def test_claude_and_codex_provider_errors_do_not_become_semantic_success(self):
        fixtures = [
            ("claude_subscription", {"is_error": True, "result": "Usage limit reached"}, "quota_or_rate_limited"),
            ("codex_chatgpt", {"type": "turn.failed", "error": {"message": "Authentication failed"}}, "authentication_failed"),
        ]
        for route, payload, expected in fixtures:
            with self.subTest(route=route), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                code = "print(" + repr(json.dumps(payload)) + ")"
                with patch.object(delegation, "_argv", return_value=([sys.executable, "-c", code], "argv")):
                    result = delegation._run_role(self.assignment(route=route), "synthetic", root, __import__("time").monotonic() + 5)
                self.assertEqual(result["state"], expected)
                self.assertFalse(result["provider_response_success"])
                self.assertIsNot(result["inference_performed"], True)

    def test_claude_expired_oauth_is_classified_without_retry_or_false_success(self):
        diagnostics = (
            "Failed to authenticate: OAuth session expired and could not be refreshed",
            "OAuth session expired",
            "OAuth token could not be refreshed",
        )
        for diagnostic in diagnostics:
            with self.subTest(diagnostic=diagnostic), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                code = "import sys; print(" + repr(diagnostic) + ", file=sys.stderr); sys.exit(1)"
                with patch.object(delegation, "_argv", return_value=([sys.executable, "-c", code], "argv")) as builder:
                    result = delegation._run_role(self.assignment(route="claude_subscription"),
                        "synthetic", root, __import__("time").monotonic() + 5)
                self.assertEqual(result["state"], "authentication_failed")
                self.assertFalse(result["provider_response_success"])
                self.assertIsNot(result["inference_performed"], True)
                builder.assert_called_once()

    def test_recent_execution_metadata_is_advisory_bounded_and_sanitized(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(delegation, "ROOT", Path(temp)):
            base = Path(temp) / "runs/mcp"
            records = [
                ("old", "2026-11-26T00:00:00+00:00", "completed"),
                ("new", "2026-11-26T01:00:00+00:00", "failed"),
            ]
            for job, finished, state in records:
                path = base / job / "delegation/reviewer/result.json"
                path.parent.mkdir(parents=True)
                path.write_text(json.dumps({"route": "claude_subscription", "state": state,
                    "finished_at": finished, "stderr": "Failed to authenticate: private diagnostic must not enter inventory"}))
            corrupt = base / "corrupt/delegation/planner/result.json"
            corrupt.parent.mkdir(parents=True)
            corrupt.write_text("{incomplete")
            oversized = base / "oversized/delegation/planner/result.json"
            oversized.parent.mkdir(parents=True)
            oversized.write_text(" " * 131073)
            latest = delegation._latest_execution_states()
            self.assertEqual(latest["claude_subscription"]["last_execution_state"], "failed")
            self.assertEqual(latest["claude_subscription"]["last_execution_error_class"], "authentication_failed")
            self.assertNotIn("private diagnostic", json.dumps(latest))
            with patch.object(delegation.shutil, "which", return_value="/installed/cli"):
                state = delegation._route_state("ollama_cloud_glm", {}, {
                    "ollama_cloud_glm": {"last_execution_state": "authentication_failed"}})
            self.assertTrue(state["ready_for_trial"])
            self.assertEqual(state["last_execution_state"], "authentication_failed")

    def test_existing_output_directory_cannot_overwrite_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            destination = root / "runs/existing"
            destination.mkdir(parents=True)
            (destination / "keep.txt").write_text("original")
            with patch.object(delegation, "ROOT", root), patch.object(delegation, "plan", return_value={"roles": []}):
                with self.assertRaises(FileExistsError):
                    delegation.run("synthetic", outputDir=str(destination))
            self.assertEqual((destination / "keep.txt").read_text(), "original")


if __name__ == "__main__":
    unittest.main()
