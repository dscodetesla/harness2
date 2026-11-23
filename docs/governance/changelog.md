# Changelog

## 2026-11-24 (`local/x99mg-integration`)
- Added deterministic RF/FPGA domain adapter `harness2/benchmarks/rf_fpga.py` and `tests/test_rf_fpga_adapter.py`.
- Added 12-file operational governance suite under `docs/governance/`.
- Added host Ollama/OpenCode templates (`opencode.x99mg.json`, `.env.x99mg.example`, `opencode.dell-t3500.json`, `.env.dell-t3500.example`).
- Synced `local/x99mg-integration` to `dscodetesla/harness2` and deployed to `dell-T3500`.

## 2026-11-23 (`4924405` & `d7294c2`)
- Fixed `SCRUB_ENV` (#219), `_write_rollout` asset dedup (#153), quoted YAML skill names (#156), multiline `_distil` parser (#195), and Codex JSONL pre-filter (`d7294c2`).
