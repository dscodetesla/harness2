"""Unit tests for the deterministic RF/FPGA domain adapter."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from harness2.benchmarks.rf_fpga import BASE_AGENTS_MD, RF_FPGA_SURFACE, RFFPGAAdapter
from harness2.core import tree as harness_tree
from harness2.core.spec import BenchmarkAdapter

REFINED_SOLVER_PY = """import json, math, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
out = {}
if data["task"] == "rf-link-433-budget":
    fspl = 20.0 * math.log10(data["distance_km"]) + 20.0 * math.log10(data["freq_mhz"]) + 32.44
    prx = data["ptx_dbm"] + data["gtx_dbi"] + data["grx_dbi"] - data["sys_loss_db"] - fspl
    margin = prx - data["rx_sens_dbm"]
    out = {
        "fspl_db": round(fspl, 3),
        "prx_dbm": round(prx, 3),
        "fade_margin_db": round(margin, 3),
        "link_viable": margin >= data["min_margin_db"],
    }
elif data["task"] == "fpga-fir-fixed-timing":
    l1 = sum(abs(c) for c in data["coeffs"])
    gb = math.ceil(math.log2(max(l1, 1)))
    acc = data["input_bits"] + data["coeff_bits"] + gb
    wns = (1000.0 / data["fclk_mhz"]) - data["t_comb_ns"] - data["t_su_ns"] - data["t_skew_ns"]
    out = {
        "l1_gain": l1,
        "guard_bits": gb,
        "accum_bits": acc,
        "wns_ns": round(wns, 4),
        "timing_pass": wns >= 0.0,
    }
with open(sys.argv[2], "w", encoding="utf-8") as f:
    json.dump(out, f, indent=2)
"""


class RFFPGAAdapterTests(unittest.TestCase):
    def test_adapter_satisfies_protocol_and_grades_baseline_vs_refined(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            adapter = RFFPGAAdapter(root / "runs")
            self.assertIsInstance(adapter, BenchmarkAdapter)
            self.assertEqual(adapter.tasks(), ["rf-link-433-budget", "fpga-fir-fixed-timing"])

            refined_dir = root / "refined_harness"
            refined_tree = {
                "AGENTS.md": BASE_AGENTS_MD,
                "scripts/solve_rf_fpga.py": REFINED_SOLVER_PY,
            }
            adapter.validate_tree(refined_tree)
            harness_tree.write_tree(RF_FPGA_SURFACE, refined_tree, refined_dir, stubs=False)

            for tid in adapter.tasks():
                base_run = adapter.execute(tid, None, f"base_{tid}")
                self.assertTrue(adapter.delivered(base_run))
                base_grade = adapter.score(base_run, tid)
                self.assertIsNotNone(base_grade)
                self.assertFalse(base_grade["passed"])
                self.assertLess(base_grade["score"], 1.0)

                ref_run = adapter.execute(tid, refined_dir, f"ref_{tid}")
                self.assertTrue(adapter.delivered(ref_run))
                ref_grade = adapter.score(ref_run, tid)
                self.assertIsNotNone(ref_grade)
                self.assertTrue(ref_grade["passed"])
                self.assertEqual(ref_grade["score"], 1.0)
                self.assertIn("[ACTION]", adapter.trajectory(ref_run))


if __name__ == "__main__":
    unittest.main()
