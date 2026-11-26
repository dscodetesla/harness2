# Real Harness² workflows through MCP

The controller now has10 tools: existing status/start_demo/run_status/results/cancel plus plan_run/start_run/start_judge/report/start_rf_run. A returned run_id identifies a durable job; run_status/results/cancel apply to all job kinds. At most one controller job is active. All executable commands use fixed argv, validated parameters and bounded supervisor cleanup.

## JobBench

1. Call harness2_plan_run(profile="ollama_local" or "ollama_glm_cloud", domain="data_entry_keyers", max_tasks=1, k=1, mode="parallel", workers=1, seconds=300). This calls the actual installed Harness² dry-run and returns exact tasks, model data disclosure and budgets; no inference.
2. Call harness2_start_run with the same arguments. ollama_glm_cloud additionally requires allow_cloud=true. Bounds: max_tasks1..5 per selected domain, k1..3, workers1..2, wall seconds1..3600. Mode is parallel or sequential.
3. Poll harness2_run_status(run_id), read harness2_results(run_id), or request harness2_cancel(run_id).
4. After terminal refinement, harness2_start_judge(run_id,bases=false,seconds=300,allow_cloud=...) starts actual selected-artifact judging with the source profile/namespace; bases=true judges baseline outputs. Judge calls may use cloud.
5. harness2_report(run_id) invokes the real cached report CLI without inference. Missing judged rows are reported by Harness²; no score is invented.

## Synthetic RF core

harness2_start_rf_run(seconds=300,allow_cloud=true) starts scripts/run_rf_workflow.py: a true model-backed core RF workflow. Model is fixed glm-5.3-flash:cloud. seconds1..300. It sends the synthetic task, trajectories, harness files and deliverables to Ollama Cloud. The script must be installed; the controller refuses missing scripts or absent explicit cloud consent. Results expose workflow.json plus summary.json and bounded log tail.

Cloud requests are time bounded; these controls do not enforce a monetary provider billing cap. plan_run returns usd_cap_enforced=false. Model access, success, independent verification and API expense must be assessed from the actual run evidence. A working controller does not imply every model/task combination is qualified.

Named profiles are isolated from host OpenCode config/skills/plugins; their model endpoint is fixed127.0.0.1:11434/v1. The Ollama service routes :cloud to its upstream provider. Known host credentials are scrubbed. This is not an OS or network sandbox.

The CAD gateway bridge and SDK-independent JSON controller whitelist expose these same typed actions. Existing app connections may cache old tool schemas and require Refresh/new chat after gateway deployment.

Validation:18 MCP tests passed6.450s, including real HTTP initialize/list10/demo lifecycle, actual JobBench dry-run, cloud gates and argv/environment constraints. No live model inference was performed by these tests.

## Actual model-backed MCP proof 2026-11-26

SDK MCP client -> typed CAD bridge -> JSON controller whitelist -> persisted worker -> core.schedule.run_domain -> results completed successfully. run_id107f99662b4843a2a2a80da78ca4a421, terminal succeeded/exit0, k1 parallel, core done1/failed0/errors[],4 numerical rollouts,5 actual GLM cloud requests including one validation retry and reflection. Independent base score0.5 -> selected score1.0; received power corrected by system loss2.5dB. INV rejected twice then safely inherited baseline; DOM and composition succeeded. Cost is not reported by Ollama and is not claimed zero. Evidence runs/mcp-rf-operational-20261126/result.json and runs/mcp/<run_id>/workflow/workflow.json. This qualification is synthetic RF433 + this cloud model only; local llama/vision/other real engineering workflows remain separate.

Status now derives qualified_workflows from terminal job + successful independent score + core statusok/errors[]; it retains local_model_refinement_qualified=false. Returned artifacts share a120KB serialized JSON budget with truncation/path manifest; partial/corrupt JSON is marked unreadable_or_in_progress rather than breaking the gateway.
