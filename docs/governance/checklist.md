# Verification Checklist (2026-11-24)

- [x] `uv venv --python 3.12 .venv` + `uv pip install -e '.[render]'` (editable install avoids sdist Issue #144/#146).
- [x] `harness2-local test` (all `unittest` suites PASS, 0 failures).
- [x] `tests/test_rf_fpga_adapter.py` PASS (baseline < 1.0 vs refined == 1.0).
- [x] `harness2-local demo --k 2` PASS (2 tasks, 0 failed, resume verified).
- [x] `git diff --check` clean; zero tokens/secrets in tracked files.
- [ ] `harness2-setup jb` + `harness2-check --bench jb` PASS on `X99MG` and `dell-T3500`.
