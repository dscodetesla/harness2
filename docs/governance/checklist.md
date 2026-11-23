# Verification Checklist (2026-11-24)

- [x] `uv venv --python 3.12 .venv` (`CPython 3.12.14`) + `uv pip install -e '.[render]'` on `X99MG` and `dell-T3500`.
- [x] Full `unittest` suite: **78/78 tests OK** on `X99MG` (38.833 s) and **78/78 tests OK** on `dell-T3500` (44.287 s).
- [x] `harness2-local demo --k 2` PASS on both hosts (2 tasks, 0 failed, resume verified).
- [x] `harness2-setup jb` RC=0 (566/566 files) and `harness2-check --bench jb` (`Ready: jb/oc; 65 tasks`) PASS on both hosts.
- [x] `harness2 --bench jb --k 1 --mode parallel --max-tasks 1 --dry-run` PASS on both hosts (and 1-domain filter verified).
- [x] Ollama OpenAI-compatible API `http://127.0.0.1:11434/v1/models` returns 200 OK on both hosts.
- [x] `git diff --check` clean; zero tokens/secrets in tracked files or `.git/config`.
