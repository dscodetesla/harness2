# Verification Checklist (2026-11-24)

- [x] `uv venv --python 3.12 .venv` + `uv pip install -e '.[render]'` on `X99MG` and `dell-T3500`.
- [x] `harness2-local test` PASS on `X99MG` (78/78 tests OK).
- [x] `tests/test_rf_fpga_adapter.py` + `tests/test_cluster_fixes.py` + `tests/test_codex_jsonl.py` + `tests/test_subprocess_env.py` PASS on both hosts.
- [x] `harness2-local demo --k 2` PASS on both hosts (2 tasks, 0 failed).
- [x] `harness2-setup jb` RC=0 (566/566 files) and `harness2-check --bench jb` (`Ready: jb/oc; 65 tasks`) PASS on both `X99MG` and `dell-T3500`.
- [x] `harness2 --bench jb --k 1 --mode parallel --max-tasks 1 --dry-run` PASS on both hosts.
- [x] `git diff --check` clean; zero tokens/secrets in tracked files.
