# Local MCP controller

The stdio server controls deterministic demos only. It does not expose a model refinement run.

Install from the repository root:
```bash
uv venv --python 3.12 .venv-mcp
uv pip install --python .venv-mcp/bin/python -e '.[render,mcp]'
```

Local MCP client configuration on dell-T3500:
```json
{"mcpServers":{"harness2":{"command":"/home/user/src/harness2/.venv-mcp/bin/python","args":["-m","harness2.mcp_server"]}}}
```

Tools: harness2_status, harness2_start_demo, harness2_run_status, harness2_results, harness2_cancel. Keep the run_id returned by start. Only one active demo is allowed. Jobs persist under runs/mcp and execute through the bounded supervisor. Results contain status, summary and bounded log tail.

This command is stdio. Web ChatGPT cannot connect to a host stdio command directly. A separately authenticated HTTPS MCP transport and account connection are still required. This step does not publish a network endpoint, install an account plugin or register a ChatGPT skill.
