# Findings (2026-11-24)

1. **System Python Mismatch**: All 3 cluster hosts run Ubuntu 26.04.1 LTS with system Python 3.14.4, while `harness2` requires `>=3.12,<3.14`. Isolated `uv venv --python 3.12 .venv` (`CPython 3.12.14`) resolves this cleanly without touching system Python.
2. **Confirmed Bugs Fixed on `local/x99mg-integration`**:
   - Codex JSONL pre-filter (`harness2/substrate/codex.py`, `d7294c2`).
   - Issue #219 (`harness2/config.py`, `4924405`): extended `SCRUB_ENV` (`OPENROUTER_API_KEY`, `DEEPSEEK_API_KEY`, `GROQ_API_KEY`, `MISTRAL_API_KEY`, `HF_TOKEN`, `HUGGING_FACE_HUB_TOKEN`, `GITHUB_PERSONAL_ACCESS_TOKEN`, `TAILSCALE_API_KEY`, `N8N_API_KEY`) and `_PROVIDER_KEYS` (`openrouter`, `deepseek`), preserving `GOOGLE_APPLICATION_CREDENTIALS` required by Vertex AI ADC (`test_subprocess_env.py`).
   - Issue #153 (`harness2/core/context.py`, `4924405`): deduplicated `images/` and `raw/` asset names in `_write_rollout()`.
   - Issue #156 (`harness2/core/tree.py`, `4924405`): strip outer YAML quotes on `name:` in `_check_skills()`.
   - Issue #195 (`harness2/core/selection.py`, `4924405`): multiline/markdown-bullet experience parser and case-insensitive tags in `_distil()`.
3. **JobBench `--max-tasks` Scope Gotcha**: Verified via `--dry-run` on both hosts that `--max-tasks 1` caps tasks **per domain** (scheduling 35 tasks across 35 domains). Single-task trials must always include `--only-domains <domain>` (e.g. `--only-domains data_entry_keyers --max-tasks 1`).
4. **Host Port Map**: `X99MG` occupies `:8443` (n8n), `:8765` (FastMCP HTTP), `:8790` (active Python svc), `:11434` (Ollama). `dell-T3500` occupies `:8443` (n8n), `:8765` (FastMCP TLS), `:9922` (A2A), `:11434` (Ollama). Port `:8795` is reserved for optional `harness2-bridge`.
