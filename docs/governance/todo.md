# TODO (2026-11-24)

- [x] Fix Codex JSONL parser (`d7294c2`) and upstream bugs #153, #156, #195, #219 (`4924405`).
- [x] Implement deterministic RF/FPGA `BenchmarkAdapter` (`harness2/benchmarks/rf_fpga.py`) + unit tests.
- [x] Run `harness2-setup jb` and `harness2-check --bench jb` on `X99MG`.
- [ ] Sync `local/x99mg-integration` to `https://github.com/dscodetesla/harness2` and deploy + `harness2-setup jb` on `dell-T3500`.
- [ ] Configure egress firewall blocking `huggingface.co`, `hf.co`, `github.com` before any live Codex model rollout.
