# SPDX-License-Identifier: Apache-2.0
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("qualify_rf_local", ROOT / "scripts/qualify_rf_local.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class NumericalGateTests(unittest.TestCase):
    def test_numerical_solver_allowed(self):
        module.gate('def solve(data):\n    x = 20 * math.log10(data["freq_mhz"])\n    return {"fspl_db": round(x, 3)}')

    def test_files_imports_introspection_and_top_level_calls_rejected(self):
        cases = [
            'import os\ndef solve(data):\n    return {}',
            'def solve(data):\n    return open("/tmp/oops", "w")',
            'def solve(data):\n    return data.__class__',
            'def solve(data):\n    while True: pass',
            'def solve(data):\n    return {}\nsolve({})',
            'def solve(data=open("bad")):\n    return {}',
            '@open("bad")\ndef solve(data):\n    return {}',
        ]
        for source in cases:
            with self.subTest(source=source), self.assertRaises(ValueError):
                module.gate(source)


if __name__ == "__main__":
    unittest.main()
