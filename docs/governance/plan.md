# Plan (2026-11-24)

1. Keep `local/x99mg-integration` in `dscodetesla/harness2` as the zero-drift branch synchronized across `X99MG` and `dell-T3500` (with `main` clean at upstream `6868817`).
2. Configure egress firewall rules blocking `huggingface.co`, `hf.co`, and `github.com` before running any live Codex (`--substrate cx`) experiments.
3. Run a bounded single-task Ollama trial (`--bench jb --only-domains data_entry_keyers --max-tasks 1 --k 1`) and always compare against baseline via `harness2-judge --bases`.
4. Extend `harness2/benchmarks/rf_fpga.py` with live KiCad DRC / Vivado WNS / Friis RF tasks using deterministic CLI verifiers.
