# Optional authenticated loopback HTTP transport

`harness2.mcp_http` exposes the same five deterministic-demo tools as the stdio adapter over Streamable HTTP `/mcp`. It uses the installed `mcp==2.3.0` SDK. Model refinement is not executable through these tools.

This is an optional local transport. The existing secure OpenAI tunnel may consume the stdio adapter instead; HTTP is not required for that route. No HTTP service, firewall rule, public tunnel, or account plugin is created by this module.

From the repository root:
```bash
.venv-mcp/bin/python -m harness2.mcp_http --init-token
.venv-mcp/bin/python -m harness2.mcp_http --port 8796
```
The initialization command creates `~/.config/harness2/mcp-http.token` with mode0600, refuses to overwrite an existing file, and never prints the token value. `HARNESS2_MCP_HTTP_TOKEN_FILE` or `--token-file` selects another private token file; `HARNESS2_MCP_HTTP_TOKEN` permits a separately provisioned secret environment value. Never put token values in source, URLs, shell command arguments, reports or plugin archives.

The server binds only 127.0.0.1. Every HTTP request needs `Authorization: Bearer <token>`. Missing/wrong/duplicate authorization returns401. File loading rejects symlinks, nonregular files, different owner, and permissions other than0600. Loopback transport has DNS rebinding protection; an authenticated reverse proxy retaining its public Host header may set one exact `HARNESS2_MCP_ALLOWED_HOST=hostname[:port]`. This module does not implement OAuth account sign-in or register a ChatGPT connection; public transport/authentication must be supplied separately.

Test:
```bash
.venv-mcp/bin/python -m unittest discover -s tests -p test_mcp_http.py -v
```
The2 tests passed in2.884s: token-file permissions/overwrite protection; unauthenticated and wrong-token401; authenticated MCP initialize/tools-list5; actual bounded demo start/status/results with done2/failed0. Tests start a temporary loopback process and stop it afterward. No model inference or external service is called. Port8796 was free at initial inspection; tests use an ephemeral free port.
