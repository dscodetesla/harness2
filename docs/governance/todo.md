# TODO (2026-11-24)

- [x] Fix Codex JSONL parser (`d7294c2`) and upstream bugs #153, #156, #195, #219 (`4924405`).
- [x] Implement deterministic RF/FPGA `BenchmarkAdapter` (`harness2/benchmarks/rf_fpga.py`) + unit tests (`ace7b56`).
- [x] Complete `harness2-setup jb`, `harness2-check --bench jb`, `--dry-run`, and full 78/78 `unittest` suite on both `X99MG` and `dell-T3500`.
- [x] Synchronize all 12 governance records and push `local/x99mg-integration` to `https://github.com/dscodetesla/harness2`.
- [ ] Rotate GitHub PAT previously shared in chat.
- [ ] Configure egress firewall blocking `huggingface.co`, `hf.co`, `github.com` prior to live Codex rollouts.
- [ ] Execute first bounded 1-task Ollama rollout (`--only-domains data_entry_keyers --max-tasks 1 --k 1`) + `harness2-judge --bases`.
