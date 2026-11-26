# State (2026-11-24)

- **X99MG** (`/home/user/src/harness2`): `local/x99mg-integration` synced, `Python 3.12.14` `.venv`, **78/78 tests OK** (38.833 s), `harness2-setup jb` RC=0 (566/566 files), `harness2-check --bench jb` -> `Ready: jb/oc; 65 tasks`, `--dry-run` PASS, Ollama `/v1/models` 200 OK.
- **dell-T3500** (`/home/user/src/harness2`): `local/x99mg-integration` synced, `Python 3.12.14` `.venv`, **78/78 tests OK** (44.287 s), `harness2-setup jb` RC=0 (566/566 files), `harness2-check --bench jb` -> `Ready: jb/oc; 65 tasks`, `--dry-run` PASS, `demo --k 2` PASS, Ollama `/v1/models` 200 OK.
- **GitHub Fork**: `https://github.com/dscodetesla/harness2` (`local/x99mg-integration` synchronized; `main` clean at upstream `6868817`).
- **Paid API Calls**: 0 executed.

## Update 2026-11-25
X99MG: local llama3.2:3b tool-call probe PASS; two JobBench single-task sweeps returned base-failed / no deliverable (exit 2). Full refinement/judging remains unqualified. Added isolated local bounded supervisor with detached-worker cleanup, 80/80 tests PASS (39.798 s). Details: ../local/TRIAL_2026-11-25_UA.md. dell-T3500 remains at ccfa485; these changes have not been deployed there. No cloud model calls made in this step.

## Context fix 2026-11-25
Confirmed Ollama truncation 10304–17027 ->2050 tokens in prior trials. New local alias llama3.2-harness:3b runtime context16384 verified; preflight integrated. 88/88 tests PASS (40.080 s). Re-trial now performs tool use but still no artifact; full model cycle not qualified. See ../local/CONTEXT_FIX_2026-11-25_UA.md. X99MG only.

## dell-T3500 sync 2026-11-25
Updated ccfa485 ->252f109. Created local llama3.2-harness:3b, inference probe OK, configured and loaded context16384 verified. 88/88 tests PASS (45.115 s). JobBench check Ready with explicit local profile; .env unchanged. Full model workflow remains unqualified. See ../local/DELL_SYNC_2026-11-25_UA.md.

## MCP and RF qualification 2026-11-25
On dell: local stdio MCP protocol PASS5 tools (demo success/results/cancel), RF schema verifier hardened with regressions. Local llama RF candidates failed strict validation (0.75 then0.50); full model refinement remains unqualified. d35afba synced to GitHub via verified bundle relay through X99MG; direct dell git push still stalls. See ../local/NEXT_STEP_2026-11-25_UA.md and MCP_LOCAL_SETUP.md. HTTPS/auth/account plugin not deployed.

## Private ChatGPT plugin 2026-11-26
Harness² Control v0.1.0 created USER/PRIVATE (plugins_6b079aff80f8819180d357b313bde00e); gateway extended11->16 tools through existing secure tunnel. 104/104 tests PASS; combined protocol status/demo/results/cancel PASS. Live tunnel ready/polls/direct existing CAD call PASS. New Harness2 tool names not yet available in current ChatGPT turn; direct Harness2 chat call pending plugin selection/connection. See ../local/WEB_PLUGIN_2026-11-26_UA.md. Model refinement remains unqualified.

## Operational controller 2026-11-26
Replaced demo-only scope with10Harness2tools: actualJobBench plan/refinement/judge/report, actual syntheticRF core workflow, state/results/cancel plus diagnosticdemo. Actual MCPsyntheticRF run107f99662b4843a2a2a80da78ca4a421 succeeded/core done1 failed0/score0.5->1.0/4rollouts5cloudcalls. Scope qualification syntheticRF only, local3B stillfailed. 118/118 testsPASS52.137s; combinedgateway21toolsPASS; privateplugin0.2.1 saved. ExistingChatGPTApp still caches old6tools: user mustRefresh MCPconnection and opennewchat; directnewtoolcall notverified. Details ../local/OPERATIONAL_2026-11-26_UA.md.


## 2026-11-26 — Host engineering capability integration

Added standalone local CAD/EDA MCP execution, source-pinned task guidance and a
bounded instruction/reference reader. Private skill snapshots and host inventories
are kept out of this public repository in a separate private deployment repository.
OpenCode executor configuration connects the host MCP without ChatGPT plugin
activation. Runtime checks exercised CAD statistics, OpenSCAD STL, Scilab, FreeCAD
API and EDA registry on Dell and X99MG. Named remote operations use a dedicated
user-level OpenSSH receiver on Tailnet port2222, not Tailscale SSH port22; private
key material is not committed. Cached host observations are distinct from live
transport/operation evidence. Native FPGA builds and physical tests remain NOT-RUN.
Startup context preparation now runs inside the cancellation/deadline supervisor;
an actual startup cancellation reached cancelled rather than interrupted.
