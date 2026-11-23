# TODO (2026-11-24)

- [x] Fix Codex JSONL parser (`d7294c2`) and upstream bugs #153, #156, #195, #219 (`4924405`).
- [x] Implement deterministic RF/FPGA `BenchmarkAdapter` (`harness2/benchmarks/rf_fpga.py`) + unit tests (`ace7b56`).
- [x] Complete `harness2-setup jb` + `harness2-check --bench jb` + `--dry-run` on `X99MG` and `dell-T3500`.
- [x] Sync `local/x99mg-integration` to `https://github.com/dscodetesla/harness2`.
- [ ] Configure egress firewall blocking `huggingface.co`, `hf.co`, `github.com` before any live Codex model rollout.
- [ ] Run first single-task Ollama rollout (`--only-domains data_entry_keyers --max-tasks 1 --k 1`) and grade with `harness2-judge --bases`.
