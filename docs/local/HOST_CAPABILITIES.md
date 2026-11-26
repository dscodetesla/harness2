# Harness² host engineering capabilities

The JobBench/OpenCode executor can discover and execute registered local engineering
operations without a ChatGPT plugin. ChatGPT remains an optional control interface.
The separate synthetic RF verifier is a numerical core workflow; it does not run
all host tools.

## Components

- harness2.host_capabilities: inventory, task-scoped guidance and execution.
- harness2.host_mcp: fixed local CAD/EDA stdio adapters using MCP 2.x legacy mode
  for existing MCP 1.x servers. Camera and controller recursion are excluded.
- mcp_workflow.environment: configures the actual OpenCode local MCP and instruction
  file; preparation runs under the worker's deadline and cancellation supervisor.
- A private versioned source snapshot supplies workflow instructions and references.
  Public runtime code excludes private source instructions and host inventories.

## Install and inspect

Use Python 3.12 and the repository's optional MCP environment:

~~~sh
cd /home/user/src/harness2
UV_CACHE_DIR=/home/user/.cache/uv-harness2-mcp uv venv --python 3.12 .venv-mcp
UV_CACHE_DIR=/home/user/.cache/uv-harness2-mcp uv pip install --python .venv-mcp/bin/python -e '.[mcp]'
.venv-mcp/bin/python -m harness2.host_capabilities inventory
.venv-mcp/bin/python -m harness2.host_capabilities plan "RF Wilkinson PCB CAD drawing budget"
.venv-mcp/bin/python scripts/check_host_mcp.py
~~~

On these deployed hosts, capabilities/plugin_sources links to the sibling private
deployment repository. Its index pins source versions/releases/hashes and separates
instruction snapshots from App-only metadata. The runtime also discovers installed
skills in .hermes/skills, .agents/skills and .codex/skills. It deduplicates task
selection by name and prefers the pinned snapshot over installed copies.

The supplied snapshot has 16 source entries, 62 skill instructions and 113 files.
Three source entries contain App metadata without portable skill instructions.
These counts describe knowledge inputs, not 62 independently verified executables.

## Use

The standalone server command is:

~~~sh
.venv-mcp/bin/python -m harness2.host_capabilities serve
~~~

MCP tools: host_capabilities_inventory, host_capabilities_plan and
host_capabilities_execute. Plans include actual discovered tool schemas and
selected instructions, capped at three skills and 16 KB by default.
The MCP is local stdio and needs no ChatGPT App connection.

| Execution action | Contract |
| --- | --- |
| mcp_call | server (cad/eda), discovered tool, exact arguments object |
| read_instruction | Registered skill_path, relative reference; bounded text only |
| adb_devices | Query an existing loopback ADB server |
| adb_screen_capture_audit | Existing authorized serial, optional user_id; scoped read-only evidence |
| rf_link_budget | Finite numeric free-space calculation; not a field qualification |
| *_version | Fixed executable version probe |

~~~sh
.venv-mcp/bin/python -m harness2.host_capabilities execute mcp_call \
  --parameters '{"server":"cad","tool":"numerical_descriptive_statistics","arguments":{"values":[1,2,3,4,5]}}'
~~~

Through the Harness controller, pass capability_query to harness2_plan_run and
harness2_start_run. Name the actual engineering task; domain still identifies an
installed JobBench domain. A guidance query alone does not replace benchmark
inputs with a user's project.

The plain upstream CLI can opt into the same preparation wrapper:

~~~sh
.venv-mcp/bin/python -m harness2.mcp_workflow \
  --execute '{"profile":"ollama_local","domain":"data_entry_keyers","max_tasks":1,"k":1,"mode":"parallel","workers":1,"seconds":300,"capability_query":"RF PCB verification"}' \
  --output /home/user/src/harness2/runs/manual-host-workflow
~~~

This direct command requires an external supervisor when a deadline/cancellation
is required. Controller-managed jobs supply that supervisor.

## Evidence and limits

check_host_mcp.py checks OpenCode's actual MCP connection, the same standalone
server's tool inventory and a real CAD statistics call without inference.
check_engineering_operations.py --output PATH collects actual OpenSCAD, Scilab,
FreeCAD and EDA-registry results; inspect domain results, not collection exit code.

Completed MCP transport is separate from verified domain execution. Unknown
response schemas remain unverified. Tool discovery is not a completed FPGA build,
board validation or physical bench test. Missing executables/devices are reported.
An API smoke test can pass even when a standalone executable is absent from PATH.

Imported scripts are readable references and are never automatically executed.
Product Design cloud APIs, account permissions and ChatGPT sessions are not copied
by exporting a skill. Existing local tooling can use portable guidance.
Android collection neither starts ADB nor connects, roots, installs or records a
device; an already authorized device is required.

Cloud profiles may send selected instructions and requested tool results to their
configured provider, in addition to task/harness/trajectory data. Existing
authorization and privacy scope apply. A time cap is not a dollar cap.

## Multiple hosts

A private host registry at ~/.config/harness2/hosts.json supplies cached observations
and a scoped SSH transport. Inventory and planning read the cache without initiating
SSH; their remote readiness is explicitly a cached observation. Plan recommends
registered hosts with relevant verified tool versions missing locally. Confirm
current availability with a remote inventory call before an expensive operation.

~~~sh
.venv-mcp/bin/python -m harness2.host_capabilities execute remote_call \
  --parameters '{"host":"x99mg","operation":"inventory","arguments":{}}'
.venv-mcp/bin/python -m harness2.host_capabilities execute remote_call \
  --parameters '{"host":"x99mg","operation":"execute","arguments":{"action":"mcp_call","parameters":{"server":"cad","tool":"numerical_descriptive_statistics","arguments":{"values":[1,2,3,4,5]}}}}'
~~~

The deployed Dell-to-X99MG key uses a dedicated user-level OpenSSH receiver on
Tailnet port 2222, restricted to the fixed JSON receiver command. Tailscale SSH on
port 22 bypassed OpenSSH authorized-key restrictions, so it is not this transport.
It provides no general SSH shell. Host keys are pinned from the target host; strict
checking is enabled. Client private key material stays on Dell and is not tracked by Git.
Remote recursion and unregistered hosts are rejected. The receiver calls the same
registered operation layer used locally; copying a host name never grants access.

Long-running native EDA jobs retain their own job IDs. Use their registered status
and cancel operations; stopping the Harness controller alone is not evidence that
a separately submitted native job has stopped.

## Local RF inference

harness2_start_rf_run now performs real local inference by default when allow_cloud
is false. Explicit allow_cloud=true retains the configured cloud profile. The
standalone script accepts --profile ollama_local or ollama_glm_cloud; select it
explicitly when invoking outside the controller. The fixed local alias uses a
16384-token context and records actual request/response token and runtime metadata.

Metadata preflight does not itself run inference. Inspect model_runs in status for
actual persisted calls and their outcomes. Local numerical refinement qualification
is derived from successful core execution plus an independent 56-case RF suite,
not a hardcoded status or one successful process exit. Visible training feedback
uses two separately declared cases; held-out cases are never sent to the model.
Incorrect results keep exit code 1 and local qualification false.

For the small local model, edit missions are compact stage-specific adaptations:
real inputs, numerical function source and visible probe errors are retained;
uneditable scaffolding and unrelated policy examples are omitted. Original missions
and hashes of changed context representations are kept in each inference audit.
This does not qualify the model for the unabridged upstream prompts or all RF tasks.

The optional RF-only ollama_gemma_local profile uses the separately installed
Gemma3 4B alias. It needs completion for JSON/source generation, not native tool
calling; GGUF, loopback, remote-model rejection and context checks still apply.
Other local agent profiles retain their native-tools requirement. Select the RF
profile explicitly with a small per-host ~/.config/harness2/rf-profile.json
containing a profile field; cloud is not a permitted implicit local selection.
Status.rf_model identifies this RF selection separately from JobBench metadata.
Neither installed local model passed the recorded RF code-generation qualification;
see the private evaluation report. Successful model invocation is not numerical
qualification. No weights were retrained and no failing results were coerced.
