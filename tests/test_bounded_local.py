# SPDX-License-Identifier: Apache-2.0
"""Supervision tests use sleeping Python processes, never a model."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "scripts/run_bounded_local.py"


@unittest.skipUnless(sys.platform == "linux", "Linux subreaper")
class BoundedLocalTests(unittest.TestCase):
    def check_cleanup(self, parent_exits):
        with tempfile.TemporaryDirectory() as tmp:
            pidfile = Path(tmp) / "child.pid"
            child = "import time; time.sleep(60)"
            worker = (
                "import subprocess,sys,time; from pathlib import Path; "
                f"p=subprocess.Popen([sys.executable,'-c',{child!r}],start_new_session=True); "
                f"Path({str(pidfile)!r}).write_text(str(p.pid)); "
                + ("sys.exit(0)" if parent_exits else "time.sleep(60)")
            )
            driver = (
                "import runpy,sys,os; "
                f"m=runpy.run_path({str(WRAPPER)!r}); "
                f"rc=m['supervise']([sys.executable,'-c',{worker!r}],"
                f"seconds=0.6,cwd={tmp!r},env=os.environ.copy()); "
                "raise SystemExit(rc)"
            )
            result = subprocess.run(
                [sys.executable, "-c", driver], capture_output=True, text=True, timeout=12)
            self.assertEqual(result.returncode, 0 if parent_exits else 124, result.stderr)
            pid = int(pidfile.read_text())
            self.assertFalse(Path(f"/proc/{pid}").exists(), f"detached child {pid} survived")

    def test_timeout_cleans_detached_child(self):
        self.check_cleanup(False)

    def test_normal_exit_cleans_orphaned_child(self):
        self.check_cleanup(True)


if __name__ == "__main__":
    unittest.main()
