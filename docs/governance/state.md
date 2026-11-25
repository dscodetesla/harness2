# State (2026-11-24)

- **X99MG** (`/home/user/src/harness2`): `local/x99mg-integration` synced, `Python 3.12.14` `.venv`, **78/78 tests OK** (38.833 s), `harness2-setup jb` RC=0 (566/566 files), `harness2-check --bench jb` -> `Ready: jb/oc; 65 tasks`, `--dry-run` PASS, Ollama `/v1/models` 200 OK.
- **dell-T3500** (`/home/user/src/harness2`): `local/x99mg-integration` synced, `Python 3.12.14` `.venv`, **78/78 tests OK** (44.287 s), `harness2-setup jb` RC=0 (566/566 files), `harness2-check --bench jb` -> `Ready: jb/oc; 65 tasks`, `--dry-run` PASS, `demo --k 2` PASS, Ollama `/v1/models` 200 OK.
- **GitHub Fork**: `https://github.com/dscodetesla/harness2` (`local/x99mg-integration` synchronized; `main` clean at upstream `6868817`).
- **Paid API Calls**: 0 executed.

## Update 2026-11-25
X99MG: local llama3.2:3b tool-call probe PASS; two JobBench single-task sweeps returned base-failed / no deliverable (exit 2). Full refinement/judging remains unqualified. Added isolated local bounded supervisor with detached-worker cleanup, 80/80 tests PASS (39.798 s). Details: ../local/TRIAL_2026-11-25_UA.md. dell-T3500 remains at ccfa485; these changes have not been deployed there. No cloud model calls made in this step.
