# Monitor (2026-11-24)

- **Ports Guarded**: `:8443` (n8n), `:8765` (FastMCP), `:8790` (X99MG Python svc), `:9900/:9922` (Hermes A2A).
- **Ollama Health**: `127.0.0.1:11434` active on both `X99MG` and `dell-T3500` (`deepseek-v4.1-flash:cloud`, `glm-5.3-flash:cloud`, `gemma3:4b`, `llama3.2:3b`).
- **Safety Gate**: Do not run live Codex rollouts without egress firewall rules blocking `hf.co` / `github.com`.
