"""Held-out qualification rejects model schema/math/overfit failures without inference."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from harness2.rf_validation import heldout_cases, reference, validate_source

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from qualify_rf_local import gate

CORRECT = """def solve(data):
    fspl = 20 * math.log10(data['distance_km']) + 20 * math.log10(data['freq_mhz']) + 32.44
    prx = data['ptx_dbm'] + data['gtx_dbi'] + data['grx_dbi'] - data['sys_loss_db'] - fspl
    margin = prx - data['rx_sens_dbm']
    return {'fspl_db': round(fspl, 3), 'prx_dbm': round(prx, 3), 'fade_margin_db': round(margin, 3), 'link_viable': margin >= data['min_margin_db']}
"""


class RFValidationTests(unittest.TestCase):
    def test_correct_general_solver_passes_all_cases(self):
        result = validate_source(CORRECT, gate=gate)
        self.assertTrue(result["qualified"], result)
        self.assertEqual(result["passed"], 56)

    def test_explicit_training_suite_keeps_strict_oracle(self):
        cases = heldout_cases()[:2]
        result = validate_source(CORRECT, gate=gate, cases=cases)
        self.assertEqual(result["suite"], "training")
        self.assertEqual(result["case_count"], 2)
        self.assertTrue(result["qualified"])
        heldout = validate_source(CORRECT, gate=gate)
        self.assertEqual(heldout["suite"], "heldout")
        self.assertEqual(heldout["case_count"], 56)
        wrong = CORRECT.replace("margin >= data[\'min_margin_db\']", "1")
        self.assertFalse(validate_source(wrong, gate=gate, cases=cases)["qualified"])

    def test_training_inputs_are_validated_before_execution(self):
        good = heldout_cases()[0]
        invalid = [[], [good] * 9, [None], [{**good, "distance_km": 0}],
                   [{**good, "freq_mhz": float("nan")}], [{**good, "ptx_dbm": True}],
                   [{**good, "extra": 1}], [{}], [{**good, "sys_loss_db": -1}]]
        with patch("harness2.rf_validation.subprocess.run") as run:
            for cases in invalid:
                with self.subTest(cases=cases), self.assertRaises(ValueError):
                    validate_source(CORRECT, gate=gate, cases=cases)
            run.assert_not_called()

    def test_boolean_number_rejected(self):
        source = CORRECT.replace("margin >= data['min_margin_db']", "1")
        result = validate_source(source, gate=gate)
        self.assertFalse(result["qualified"])
        self.assertTrue(any(not row["checks"]["link_viable"] for row in result["failure_details"]))

    def test_positive_fspl_sign_rejected(self):
        result = validate_source(CORRECT.replace("- fspl", "+ fspl"), gate=gate)
        self.assertFalse(result["qualified"])
        self.assertTrue(any(not row["checks"]["prx_dbm"] for row in result["failure_details"]))

    def test_original_case_hardcoding_rejected(self):
        source = """def solve(data):
    return {'fspl_db':108.710,'prx_dbm':-72.210,'fade_margin_db':47.790,'link_viable':True}
"""
        self.assertFalse(validate_source(source, gate=gate)["qualified"])

    def test_intermediate_rounding_cannot_hide_predicate_error(self):
        source = CORRECT.replace("margin = prx - data['rx_sens_dbm']",
                                 "margin = round(prx - data['rx_sens_dbm'], 3)")
        result = validate_source(source, gate=gate)
        self.assertFalse(result["qualified"])
        self.assertTrue(any(row["case"] >= 52 and not row["checks"]["link_viable"]
                            for row in result["failure_details"]))

    def test_cases_are_deterministic_and_both_viabilities_present(self):
        cases = heldout_cases()
        self.assertEqual(cases, heldout_cases())
        self.assertGreaterEqual(len(cases), 32)
        self.assertEqual({reference(case)["link_viable"] for case in cases}, {False, True})

    def test_gate_is_required_and_runs_before_execution(self):
        with self.assertRaises(TypeError):
            validate_source(CORRECT)
        def reject(source):
            raise ValueError("blocked")
        with patch("harness2.rf_validation.subprocess.run") as run:
            with self.assertRaisesRegex(ValueError, "blocked"):
                validate_source("import os", gate=reject)
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
