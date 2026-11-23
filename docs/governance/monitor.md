# Monitor (2026-11-24)

- **Guarded Cluster Ports**:
  - `X99MG`: `:8443` (n8n), `:8765` (FastMCP HTTP), `:8790` (active Python svc), `:9900` (Hermes A2A), `:11434` (Ollama).
  - `dell-T3500`: `:8443` (n8n), `:8765` (FastMCP TLS), `:9922` (Hermes A2A), `:11434` (Ollama).
  - Reserved for optional `harness2-bridge`: `127.0.0.1:8795`.
- **Ollama Health (Verified 200 OK on both hosts)**: `deepseek-v4.1-flash:cloud`, `glm-5.3-flash:cloud`, `gemma3:4b`, `llama3.2:3b`.
- **Safety Gate**: Do not run live Codex rollouts without egress firewall rules blocking `hf.co` / `github.com`.
