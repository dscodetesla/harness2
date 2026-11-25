import json
import tempfile
import unittest
from pathlib import Path
from harness2.benchmarks.rf_fpga import RFFPGAAdapter, _expected

class RFSchemaTests(unittest.TestCase):
    def test_wrong_types_and_nonfinite_are_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            adapter = RFFPGAAdapter(root / 'runs')
            good = _expected('rf-link-433-budget')
            values = [('link_viable', 1), ('link_viable', 'false'),
                      ('fspl_db', str(good['fspl_db'])), ('prx_dbm', True),
                      ('fspl_db', float('nan')), ('fspl_db', float('inf'))]
            for key, value in values:
                with self.subTest(key=key, value=value):
                    (root / 'result.json').write_text(json.dumps({**good, key: value}))
                    self.assertFalse(adapter.score(root, 'rf-link-433-budget')['passed'])
            (root / 'result.json').write_text(json.dumps(good))
            self.assertTrue(adapter.score(root, 'rf-link-433-budget')['passed'])

    def test_non_object_is_rejected_without_exception(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            adapter = RFFPGAAdapter(root / 'runs')
            for data in [None, [], 'fspl_db', 42]:
                (root / 'result.json').write_text(json.dumps(data))
                self.assertFalse(adapter.score(root, 'rf-link-433-budget')['passed'])
