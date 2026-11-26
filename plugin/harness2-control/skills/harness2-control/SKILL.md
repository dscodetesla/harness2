---
name: harness2-control
description: Inspect Harness² on dell-T3500, run bounded deterministic demonstrations, retrieve results and cancel a run using its private MCP tools.
---

# Harness² control

Use the connected MCP tools for a requested Harness² operation.
1. Call harness2_status. Report model configuration separately from model readiness. A loaded_context_length of null means the model is not loaded; it is not proof of a context error.
2. For a requested demonstration, call harness2_start_demo with k=1 and seconds=60 unless the user requests another supported setting. This starts deterministic Python executions without model inference.
3. Retain the returned run_id. Call harness2_run_status to inspect progress, then harness2_results for terminal evidence. Avoid tight polling; wait for a useful interval or return the run ID when the user only asked to start.
4. For a requested stop, call harness2_cancel with that run_id. Verify cancelled or another terminal state before saying the run stopped.
5. Report the observed state, exit code and done/failed counts. A transport success alone does not mean task success.

The available tools are harness2_status, harness2_start_demo, harness2_run_status, harness2_results and harness2_cancel. Tool namespaces depend on the connected host; use the discovered names.

Only one demo may be active. Supported k is 1 or 2; time limit is 1–120 seconds. Invalid IDs, missing runs, unavailable host or active-run conflicts should be reported directly. Do not invent a successful result or repeat an uncertain start before checking status.

The shared engineering gateway also advertises existing CAD/camera tools. For Harness² tasks, use the five harness2 tools; other operations require a relevant user request.

Current scope: deterministic demonstrations and environment inspection. Local 3B model RF candidates failed strict validation; model-backed Harness² refinement is not qualified and is not exposed by these tools. This plugin cannot modify the ChatGPT base model or platform instructions. It does not silently adopt generated harness changes.
