"""True-core RF workflow numerical safety tests; no model calls."""
import importlib.util
import io
import json
import time
from unittest.mock import patch
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("run_rf_workflow", ROOT / "scripts/run_rf_workflow.py")
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)


class RFWorkflowTests(unittest.TestCase):
    def test_surface_is_supported_by_actual_core_prompts(self):
        from harness2.core import prompts
        with tempfile.TemporaryDirectory() as temp:
            adapter = M.SafeRFAdapter(Path(temp))
            mission = prompts.propose(adapter.spec.prompts, "INV", adapter.substrate.surface(), k=1, index=1)
            self.assertTrue(mission.strip())

    def test_trusted_baseline_executes_and_scores(self):
        with tempfile.TemporaryDirectory() as temp:
            adapter = M.SafeRFAdapter(Path(temp))
            run = adapter.execute("rf-link-433-budget", None, "baseline")
            score = adapter.score(run, "rf-link-433-budget")
            self.assertEqual(score["score"], 0.5)
            self.assertFalse(score["passed"])
            self.assertEqual(adapter.execution_count, 1)

    def test_visible_numeric_feedback_rejects_wrong_solver_without_changing_baseline(self):
        with tempfile.TemporaryDirectory() as temp:
            adapter = M.SafeRFAdapter(Path(temp))
            adapter.training_feedback = True
            tree = {"AGENTS.md": M.BASE_AGENTS_MD, "scripts/solve_rf_fpga.py": M.PREFIX + M.BASE + M.SUFFIX}
            with self.assertRaisesRegex(ValueError, "Visible RF training checks"):
                adapter.validate_tree(tree)
            self.assertEqual(adapter.score(adapter.execute("rf-link-433-budget",None,"base"),"rf-link-433-budget")["score"],0.5)
            correct = M.BASE.replace(" - fspl", " - data['sys_loss_db'] - fspl")
            tree["scripts/solve_rf_fpga.py"] = M.PREFIX + correct + M.SUFFIX
            adapter.validate_tree(tree)

    def test_candidate_io_edits_rejected_before_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            adapter = M.SafeRFAdapter(Path(temp))
            harness = adapter.base_harness()
            solver = harness / "scripts/solve_rf_fpga.py"
            solver.write_text(solver.read_text().replace("import json, math, sys, resource", "import os"))
            with self.assertRaisesRegex(ValueError, "Trusted I/O"):
                adapter.execute("rf-link-433-budget", harness, "bad")
            self.assertEqual(adapter.execution_count, 0)

    def test_model_transport_requests_final_json_and_counts_failures(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            context = root / "context"
            context.mkdir()
            (context / "task.txt").write_text("Synthetic RF task")
            proposer = M.OllamaProposer(root / "audit", time.monotonic() + 10)
            class FakeOpener:
                def open(self, request, timeout):
                    payload = json.loads(request.data)
                    assert payload["think"] is False
                    assert payload["format"] == "json"
                    return io.BytesIO(json.dumps({"message": {"content": json.dumps({
                        "solver_source": M.BASE, "notes": "fixture transport"})}}).encode())
            with patch.object(M.urllib.request, "build_opener", return_value=FakeOpener()):
                reply = proposer.call("synthetic fixture", context, "inv1.a1")
            self.assertTrue(reply.ok)
            self.assertTrue((reply.workspace / "scripts/solve_rf_fpga.py").is_file())
            self.assertEqual(proposer.request_count, 1)
            with patch.object(M.urllib.request, "build_opener") as factory:
                factory.return_value.open.side_effect = OSError("offline")
                with self.assertRaises(M.ProposerError):
                    proposer.call("synthetic fixture", context, "dom1.a1")
            self.assertEqual(proposer.request_count, 2)

    def test_captured_model_safe_boolean_and_ternary_are_accepted(self):
        # Numerical idioms captured in the rejected cloud response; no synthesized fix.
        source = """def solve(data):
    fspl = 20 * math.log10(data[\'distance_km\']) + 20 * math.log10(data[\'freq_mhz\']) + 32.44
    prx = data[\'ptx_dbm\'] + data[\'gtx_dbi\'] + data[\'grx_dbm\' if False else \'grx_dbi\'] - data[\'sys_loss_db\'] - fspl
    margin = prx - data[\'rx_sens_dbm\']
    return {\'fspl_db\': round(fspl, 2), \'prx_dbm\': round(prx, 2), \'fade_margin_db\': round(margin, 2), \'link_viable\': bool(margin >= data[\'min_margin_db\'])}
"""
        M.numerical_source(M.PREFIX + source + M.SUFFIX)

    def test_untrusted_numerical_body_rejected(self):
        for source in ['def solve(data):\n    return open("bad")',
                       'def solve(data):\n    import os\n    return {}']:
            with self.subTest(source=source), self.assertRaises(ValueError):
                M.numerical_source(M.PREFIX + source + M.SUFFIX)


    def test_explicit_local_profile_uses_local_model_context_and_real_telemetry(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            context = root / "context"
            context.mkdir()
            (context / "task.txt").write_text("Synthetic RF task")
            with patch.object(M, "check_local_model", return_value={"configured_num_ctx": 16384, "local_only": True}) as preflight:
                proposer = M.OllamaProposer(root / "audit", time.monotonic() + 10, profile="ollama_local")
            preflight.assert_called_once_with(required_context=16384)
            seen = []
            class FakeLocal:
                def open(self, request, timeout):
                    if isinstance(request, str):
                        return io.BytesIO(json.dumps({"models": [{"model": "llama3.2-harness:3b", "context_length": 16384}]}).encode())
                    payload = json.loads(request.data)
                    seen.append(payload)
                    assert payload["model"] == "llama3.2-harness:3b"
                    assert payload["options"]["num_ctx"] == 16384
                    assert payload["options"]["num_predict"] <= 2048
                    return io.BytesIO(json.dumps({"done": True, "done_reason": "stop", "prompt_eval_count": 1234,
                        "eval_count": 234, "message": {"content": json.dumps({"solver_source": M.BASE, "notes": "local transport fixture"})}}).encode())
            with patch.object(M.urllib.request, "build_opener", return_value=FakeLocal()):
                reply = proposer.call("local synthetic fixture", context, "inv1.a1")
            self.assertTrue(reply.ok)
            self.assertEqual(reply.channel, "ollama_http_local")
            self.assertEqual(len(seen), 1)
            telemetry = json.loads((root / "audit/inv1.a1/telemetry.json").read_text())
            self.assertEqual(telemetry["model"], "llama3.2-harness:3b")
            self.assertEqual(telemetry["runtime_context_length"], 16384)
            self.assertEqual(telemetry["prompt_eval_count"], 1234)
            self.assertEqual(telemetry["done_reason"], "stop")
            self.assertTrue(telemetry["inference_performed"])

    def test_generation_token_cap_is_audited_and_not_accepted(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            context = root / "context"
            context.mkdir()
            proposer = M.OllamaProposer(root / "audit", time.monotonic() + 10)
            class Capped:
                def open(self, request, timeout):
                    if isinstance(request, str):
                        return io.BytesIO(b'{"models":[]}')
                    return io.BytesIO(json.dumps({"done": True, "done_reason": "length", "eval_count": 4096,
                        "message": {"content": "incomplete"}}).encode())
            with patch.object(M.urllib.request, "build_opener", return_value=Capped()):
                with self.assertRaisesRegex(M.ProposerError, "token cap"):
                    proposer.call("fixture", context, "inv1.a1")
            telemetry = json.loads((root / "audit/inv1.a1/telemetry.json").read_text())
            self.assertEqual(telemetry["done_reason"], "length")
            self.assertEqual(proposer.request_count, 1)
            self.assertEqual(len(proposer._calls), 0)

    def test_unknown_profile_is_rejected_without_fallback(self):
        with self.assertRaisesRegex(ValueError, "Unknown RF workflow profile"):
            M.OllamaProposer(Path("unused"), time.monotonic() + 10, profile="unknown")


    def test_local_context_excludes_wrapper_cloud_keeps_original_and_audit_matches(self):
        for profile in ("ollama_local", "ollama_glm_cloud"):
            with self.subTest(profile=profile), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                context = root / "context"
                context.mkdir()
                original = M.PREFIX + M.BASE + M.SUFFIX
                (context / "solver.py").write_text(original)
                (context / "task.txt").write_text("Actual synthetic task evidence retained")
                with patch.object(M, "check_local_model", return_value={"configured_num_ctx": 16384, "local_only": True}):
                    proposer = M.OllamaProposer(root / "audit", time.monotonic() + 10, profile=profile)
                captured = []
                class Opener:
                    def open(self, request, timeout):
                        if isinstance(request, str):
                            return io.BytesIO(json.dumps({"models": [{"model": proposer.model, "context_length": 16384}]}).encode())
                        payload = json.loads(request.data)
                        captured.append(payload)
                        answer = ("<experience>Actual fixture reflection</experience>" if "experience" in payload["messages"][-1]["content"].split("SYNTHETIC CONTEXT FILES:")[0]
                                  else json.dumps({"solver_source": M.BASE, "notes": "fixture"}))
                        return io.BytesIO(json.dumps({"done": True, "done_reason": "stop", "message": {"content": answer}}).encode())
                for label in ("inv1.a1", "experience.fixture"):
                    with patch.object(M.urllib.request, "build_opener", return_value=Opener()):
                        proposer.call("experience mission" if label.startswith("experience") else "edit mission", context, label)
                    payload = captured[-1]
                    self.assertEqual(json.loads((root / "audit" / label / "request.json").read_text()), payload)
                    text = payload["messages"][-1]["content"].split("SYNTHETIC CONTEXT FILES:\n", 1)[1].split("\n\n# FINAL TRANSPORT", 1)[0]
                    files = json.loads(text)
                    self.assertEqual(files["task.txt"], "Actual synthetic task evidence retained")
                    if profile == "ollama_local":
                        self.assertIn(M.BASE.strip(), files["solver.py"])
                        for forbidden in ("import json", "resource.setrlimit", "json.load", "sys.argv", "open("):
                            self.assertNotIn(forbidden, files["solver.py"])
                        self.assertIn("CONTEXT REPRESENTATION", files["solver.py"])
                        self.assertIn("sys_loss_db", payload["messages"][0]["content"])
                        if not label.startswith("experience"):
                            self.assertEqual(payload["format"]["required"], ["solver_source", "notes"])
                            self.assertFalse(payload["format"]["additionalProperties"])
                    else:
                        self.assertEqual(files["solver.py"], original)
                        if not label.startswith("experience"):
                            self.assertEqual(payload["format"], "json")

    def test_local_context_does_not_invent_source_for_unparseable_script(self):
        represented = M.local_numerical_context("def broken(")
        self.assertIn("No source was invented", represented)
        self.assertNotIn("def solve", represented)


    def test_compact_local_edit_mission_preserves_exact_actual_retry_feedback(self):
        feedback = 'Visible RF training checks failed: [{"input":{"sys_loss_db":2.5},"checks":{"prx_dbm":false,"link_viable":false},"got":{"link_viable":1}}]'
        original = ("Hypothetical upstream example: remove PostToolUse hook.\n"
                    "# YOUR PREVIOUS ATTEMPT WAS REJECTED\n\n" + feedback
                    + "\n\nFix it in `context/harness/` and reply again.")
        for label, goal in (("inv1.a2", "INV:"), ("dom1.a2", "DOM:"), ("agg1.a2", "AGG:")):
            compact = M.local_edit_mission(original, label)
            self.assertTrue(compact.startswith(goal))
            self.assertIn(feedback, compact)
            self.assertIn("sys_loss_db", compact)
            self.assertIn("strict Python Boolean", compact)
            self.assertNotIn("PostToolUse", compact)
            self.assertNotIn("Fix it in", compact)
            self.assertNotIn("def solve(data):", compact)

    def test_local_request_omits_uneditable_scaffold_examples_keeps_actual_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            context = root / "context"
            context.mkdir()
            for relative in M.LOCAL_UNEDITABLE_SCAFFOLDS:
                file = context / relative
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_text("Hypothetical PostToolUse hook and delegated role example")
            actual = {"task.md": "Compute actual RF task", "source/input.json": '{"sys_loss_db":2.5}',
                      "rollouts/base1.md": "[OBSERVATION] actual probe returncode0",
                      "deliverables/base1/result.json.txt": '{"prx_dbm":-69.71}'}
            for relative, content in actual.items():
                file = context / relative
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_text(content)
            with patch.object(M, "check_local_model", return_value={"configured_num_ctx": 16384}):
                proposer = M.OllamaProposer(root / "audit", time.monotonic() + 10, "ollama_local")
            captured = []
            class Opener:
                def open(self, request, timeout):
                    if isinstance(request, str):
                        return io.BytesIO(b'{"models":[]}')
                    payload = json.loads(request.data)
                    captured.append(payload)
                    return io.BytesIO(json.dumps({"message": {"content": json.dumps({"solver_source": M.BASE, "notes": "fixture"})}}).encode())
            feedback = "Forbidden syntax: Import"
            original = "Remove hypothetical PostToolUse hook.\n# YOUR PREVIOUS ATTEMPT WAS REJECTED\n\n" + feedback + "\n\nFix it in `context/harness/` and reply again."
            with patch.object(M.urllib.request, "build_opener", return_value=Opener()):
                proposer.call(original, context, "dom1.a2")
            prompt = captured[0]["messages"][-1]["content"]
            self.assertNotIn("PostToolUse", prompt)
            self.assertIn(feedback, prompt)
            files = json.loads(prompt.split("SYNTHETIC CONTEXT FILES:\n", 1)[1].split("\n\n# FINAL TRANSPORT", 1)[0])
            self.assertEqual(files, actual)
            audit = root / "audit/dom1.a2"
            self.assertEqual((audit / "upstream_mission.txt").read_text(), original)
            entries = json.loads((audit / "context_representations.json").read_text())
            self.assertEqual(set(entries), M.LOCAL_UNEDITABLE_SCAFFOLDS)
            self.assertTrue(all(item["representation"] == "omitted_uneditable_upstream_scaffold" and item["original_sha256"] for item in entries.values()))


if __name__ == "__main__":
    unittest.main()
