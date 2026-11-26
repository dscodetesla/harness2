---
name: harness2-control
description: Operate Harness² refinement, judging, reports and synthetic RF workflows on dell-T3500 through its connected MCP tools.
---

# Harness² workflows

Use the connected harness2 tools to execute the requested workflow. Preserve the user's task scope and existing authorization. Do not substitute a deterministic demonstration for a real requested run.

## Inspect and plan
Call harness2_status. For JobBench, call harness2_plan_run with an installed domain and named profile. It resolves the actual task stream without inference. Explain the selected tasks, model service, recursion budget, expected rollouts and time limit. A plan is not an executed run.
Profiles are ollama_local and ollama_glm_cloud. The local 3B model has failed RF qualification; do not claim it is a validated engineering model.

## Execute
Use harness2_start_run for JobBench refinement. Supported parameters are profile, domain, max_tasks, k, mode, workers and seconds; discover exact schema ranges from the tool. Retain the returned run_id.
For the synthetic RF workflow use harness2_start_rf_run. This is actual core refinement with a numerical verifier, not the deterministic demo.
For cloud runs, before the first inference explain that task inputs, harness files, trajectories and deliverables go to Ollama Cloud. Set allow_cloud only when authorized. Authorization for a synthetic public test does not include private project files. A time cap is not a monetary cap; do not invent provider cost.

## Track, assess, report
Call harness2_run_status and harness2_results for the returned ID. Avoid tight polling. A successful process exit or core adoption alone does not prove engineering correctness; report independent verification and stage failures as well.
For JobBench assessment use harness2_start_judge with the source run_id and bases=true when comparing against baseline. Judge profile and namespace must match the source run. Use harness2_report to retrieve its report.
For a requested stop use harness2_cancel and verify the terminal state.

The available workflow tools are harness2_status, harness2_plan_run, harness2_start_run, harness2_start_rf_run, harness2_start_judge, harness2_report, harness2_run_status, harness2_results and harness2_cancel. harness2_start_demo is retained only for an explicitly requested connection diagnostic.
Only use discovered tool names and schemas. Never fabricate results or retry an uncertain start without checking jobs first. The shared gateway advertises unrelated CAD/camera tools; use them only for a relevant user request.
If ChatGPT exposes only the old CAD tools, this is a stale App tool inventory: the user must refresh the CAD CAE dell-T3500 MCP connection in ChatGPT Plugins and begin a new conversation. Changing prompt wording cannot load an absent tool. Do not claim the web integration is verified until a direct harness2 call works.
