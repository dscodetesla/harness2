---
name: harness2-control
description: Operate Harness² jobs, native CLI role delegation, host capabilities, refinement and reports through its connected MCP tools.
---

# Harness² workflows

Use discovered Harness² tools for the user's requested work. Preserve task scope and existing authorization. Keep supplied task context, model responses and deterministic engineering evidence distinguishable.

## Routing and authorization

Configured cloud and subscription routes are primary on dell-T3500. Read the saved routing policy and current route evidence through status/planning; honor existing cloud authorization. Local model profiles are an explicit opt-in. Do not silently replace a requested cloud/subscription job with the local 3B model or a deterministic demo.

The configured native role policy assigns planner and reviewer to Ollama GLM Cloud, and implementer to the native Codex CLI with its ChatGPT login. The verifier role also uses the configured role policy when explicitly selected. Claude's Dell OAuth evidence currently indicates an expired session; it is not the primary route. Authentication repair and successful execution must be verified before treating that route as working.

A CLI executable or login status does not establish remaining quota, billing, model access or successful inference. Other inventoried clients are not all implemented execution routes or inference-verified. The preference for subscriptions is a coordinator hint; the explicit role policy chooses the actual CLI.

Cloud runs send the supplied task and role instructions to the selected provider. JobBench runs can also send task inputs, trajectories, harness files, deliverables, selected host instructions and requested host tool results. Respect the authorized data scope. Explicit allow_cloud=false overrides saved cloud authorization. A time cap is not a monetary cap.

## Native CLI role delegation through existing tools

Use this path for a concrete parent task that benefits from multiple role analyses. Put a self-contained task in capability_query: objective, relevant supplied facts, constraints and expected output. Include only context authorized for the selected providers.

First call harness2_plan_run with:

```json
{
  "domain": "agent_delegation",
  "capability_query": "Self-contained task, constraints and expected deliverable",
  "k": 1,
  "max_tasks": 1,
  "workers": 2,
  "seconds": 180
}
```

Inspect the planned role assignments and route evidence. Planning performs no inference. To execute, call harness2_start_run with the same parameters. Omitted profile and allow_cloud follow the saved authorized routing policy. Set allow_cloud=true when the current request explicitly authorizes cloud use and no saved authorization applies. An explicit cloud denial blocks this delegation path.

The existing start tool returns run_id promptly; delegation runs under the persisted job supervisor. Retain that ID and use harness2_run_status, harness2_results and harness2_cancel. These existing tool names support the new domain without requiring a new App binding.

The controller requests planner, implementer and reviewer by default. workers=2 limits concurrent roles; it does not change role identities. Roles produce read-only proposals and analysis. The implementer role proposes steps or code sketches. The verifier role derives acceptance conditions; it does not execute tests. Report actual role states, route/provider, output and failures. Separate roles using one provider are not independent model validation.

A completed delegation means the requested role responses completed. Its report sets engineering_validation_performed=false. Never turn an analytical proposal, successful CLI exit, login or verifier narrative into an engineering PASS. Run relevant registered host operations and deterministic checks separately when the user has requested executable engineering work.

## Host capabilities and task guidance

For host engineering work, use capability_query to describe the actual domain and task, such as RF Wilkinson PCB validation or Android screen capture audit. The JobBench OpenCode executor receives selected local instructions and the standalone host-engineering MCP. The host capability layer operates independently of ChatGPT plugin discovery and can expose configured remote hosts.

The executor can call host_capabilities_inventory, host_capabilities_plan and host_capabilities_execute. Registered operations include local engineering MCP calls, configured remote calls, bounded instruction/reference reading, finite RF calculations and scoped Android evidence queries. Use actual discovered schemas and report unavailable software, devices, expired authentication and failed operations. Cached observations and instruction snapshots do not prove current readiness or engineering correctness. Copying Product Design instructions does not transfer cloud service access or account permissions.

Native CLI role analysis and registered host execution have separate evidence. A role's suggestion to run a tool is not proof that the tool ran.

## Refinement, judging and RF workflows

For JobBench refinement, use harness2_plan_run with an installed domain and selected profile, then harness2_start_run. Read current schemas for limits. Omitted profiles follow the saved routing policy; use an explicit local profile only when local execution is requested.

Use harness2_start_rf_run for the dedicated synthetic numerical RF workflow. Its omitted allow_cloud follows saved routing preferences; explicit false selects the local diagnostic profile. Qualification requires the actual core workflow and independent held-out numerical checks, and applies only to that RF task family. Do not generalize it to physical hardware, native role delegation or every host tool.

Use harness2_start_judge and harness2_report for terminal JobBench refinement runs. Preserve the source profile and namespace; bases=true enables baseline comparison. These judge/report operations do not assess native role-delegation jobs.

## Track, assess and recover

Use harness2_run_status and harness2_results for the returned ID; avoid tight polling. Inspect per-role states, provider errors and retained artifacts. Report authentication_failed, quota_or_rate_limited, timed_out, partial and blocked outcomes directly. Do not infer current quota from an earlier login or automatically retry an uncertain start without checking jobs.

For a stop, call harness2_cancel and verify the terminal state. Keep a failed run's ID and evidence when proposing a retry.

Available workflow tools include harness2_status, harness2_plan_run, harness2_start_run, harness2_start_rf_run, harness2_start_judge, harness2_report, harness2_run_status, harness2_results and harness2_cancel. harness2_start_demo is for an explicitly requested connection diagnostic.

Only use discovered tool names and schemas. The shared gateway also advertises unrelated tools; use them when relevant to the user's task. If the current session does not expose harness2_start_run at all, explain the observed discovery failure and repair the connection inventory. Do not request an App refresh merely to use agent_delegation through an already available start tool.
