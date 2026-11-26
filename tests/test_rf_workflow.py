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


if __name__ == "__main__":
    unittest.main()
