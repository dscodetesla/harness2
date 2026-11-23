# Findings (2026-11-24)

1. **System Python Mismatch**: All 3 cluster hosts run Ubuntu 26.04.1 LTS with system Python 3.14.4, while `harness2` requires `>=3.12,<3.14`. Isolated `uv venv --python 3.12 .venv` resolves this cleanly.
2. **Confirmed Bugs Fixed on `local/x99mg-integration`**:
   - Codex JSONL pre-filter (`harness2/substrate/codex.py`, commit `d7294c2`).
   - Issue #219: `SCRUB_ENV` lacked OpenRouter, DeepSeek, Groq, Mistral, HF, GitHub PAT, Tailscale, n8n tokens (`harness2/config.py`). Must preserve `GOOGLE_APPLICATION_CREDENTIALS` for Vertex AI ADC (`test_subprocess_env.py`).
   - Issue #153: `_write_rollout()` flattened duplicate `images/` and `raw/` basenames (`harness2/core/context.py`).
   - Issue #156: `_check_skills()` rejected quoted YAML `name:` values (`harness2/core/tree.py`).
   - Issue #195: `_distil()` dropped multiline/bullet experience values and matched tags case-sensitively (`harness2/core/selection.py`).
3. **Host Port Map**: On `X99MG`, `:8443` (n8n), `:8765` (FastMCP), `:8790` (active Python svc), `:11434` (Ollama). On `dell-T3500`, `:8443` (n8n), `:8765` (FastMCP TLS), `:9922` (A2A), `:11434` (Ollama). Reserved `:8795` for optional `harness2-bridge`.
