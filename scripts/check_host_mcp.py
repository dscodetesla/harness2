#!/usr/bin/env python3
"""Reproduce OpenCode + standalone host MCP evidence without model inference."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from harness2 import config
from harness2 import mcp_workflow as workflow

EVIDENCE = ROOT / "docs/local/host-capability-evidence/dell"
TOOLS = {"host_capabilities_inventory", "host_capabilities_plan", "host_capabilities_execute"}
CALL = {"action": "mcp_call", "parameters": {
    "server": "cad", "tool": "numerical_descriptive_statistics",
    "arguments": {"values": [1, 2, 3, 4, 5]},
}}
LOG_BYTES = 16384


def redacted(text):
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
    for key, value in os.environ.items():
        if len(value) >= 8 and re.search("TOKEN|SECRET|PASSWORD|API_KEY|ACCESS_KEY", key, re.I):
            text = text.replace(value, "[redacted]")
    text = re.sub(r"(?i)(bearer\s+)[^\s\"']+", r"\1[redacted]", text)
    text = re.sub(r"(?i)([?&](?:token|key|secret)=)[^\s&]+", r"\1[redacted]", text)
    return text


def save(name, value):
    text = redacted(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))
    if len(text.encode()) > 65536:
        raise ValueError("Evidence exceeds 64 KiB")
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / name).write_text(text + "\n", encoding="utf-8")


def opencode_check(env):
    command = [str(config.BUN), "run", "--cwd",
               str(config.OPENCODE_DIR / "packages/opencode"),
               "--conditions=browser", "src/index.ts", "mcp", "list"]
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        process = subprocess.Popen(command, cwd=ROOT, env=env,
            stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, start_new_session=True)
        timed_out = False
        try:
            process.wait(timeout=60)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=10)
        def tail(stream):
            size = stream.tell()
            stream.seek(max(0, size - LOG_BYTES))
            return redacted(stream.read(LOG_BYTES).decode("utf-8", "replace")), size > LOG_BYTES
        out, out_truncated = tail(stdout)
        err, err_truncated = tail(stderr)
    connected = bool(re.search(r"host-engineering\s+connected", out))
    return {"command": command, "exit_code": process.returncode,
            "timed_out": timed_out, "stdout": out, "stderr": err,
            "stdout_truncated": out_truncated, "stderr_truncated": err_truncated,
            "host_engineering_connected": connected,
            "passed": process.returncode == 0 and connected and not timed_out,
            "inference_performed": False}


def data(reply):
    if reply.is_error:
        raise ValueError("Standalone MCP returned a tool error")
    if reply.structured_content is not None:
        return reply.structured_content
    return json.loads(reply.content[0].text)


async def standalone_check(server_config, env):
    from mcp.client import Client
    from mcp.client.stdio import StdioServerParameters, stdio_client

    command = server_config["command"]
    params = StdioServerParameters(
        command=command[0], args=command[1:], cwd=str(ROOT),
        env={**env, **server_config.get("environment", {})})
    with open(os.devnull, "w", encoding="utf-8") as errlog:
        async with asyncio.timeout(60):
            async with stdio_client(params, errlog=errlog) as streams:
                @asynccontextmanager
                async def transport():
                    yield streams
                async with Client(transport(), mode="legacy", cache=None) as client:
                    listing = await client.list_tools()
                    names = [tool.name for tool in listing.tools]
                    if set(names) != TOOLS or len(names) != 3:
                        raise ValueError("Standalone MCP tool list differs from expected three")
                    reply = await client.call_tool("host_capabilities_execute", CALL)
                    response = data(reply)
    result = response.get("result", {})
    if result.get("isError") is not False:
        raise ValueError("Underlying CAD tool did not report successful MCP execution")
    stats = result.get("structuredContent")
    if stats is None:
        stats = json.loads(result["content"][0]["text"])
    if stats.get("n") != 5 or stats.get("mean") != 3.0:
        raise ValueError("Numerical statistics did not match actual expected result")
    return {"passed": True, "plugin_required": False, "inference_performed": False,
            "command": command, "transport": "stdio", "tools": names,
            "call": {"tool": "host_capabilities_execute", "arguments": CALL},
            "response": response, "statistics": stats}


def main():
    evidence = {"checked_at": datetime.now(timezone.utc).isoformat(),
                "host": os.uname().nodename, "inference_performed": False,
                "chatgpt_plugin_required": False}
    opencode = {"passed": False, "inference_performed": False}
    standalone = {"passed": False, "inference_performed": False}
    try:
        with tempfile.TemporaryDirectory(prefix="harness2-host-mcp-proof-") as folder:
            parameters = workflow.validate(
                "ollama_local", "data_entry_keyers", 1, 1, "sequential", 1, 60,
                capability_query="CAD numerical statistics RF")
            env = workflow.environment(parameters, Path(folder))
            server = json.loads(env["OPENCODE_CONFIG_CONTENT"])["mcp"]["host-engineering"]
            evidence["configuration"] = {"query": parameters["capability_query"],
                "server_id": "host-engineering", "type": server["type"],
                "enabled": server["enabled"], "command": server["command"]}
            try:
                opencode = opencode_check(env)
            except Exception as error:
                opencode["error"] = type(error).__name__ + ": executor check failed"
            try:
                standalone = asyncio.run(standalone_check(server, env))
            except Exception as error:
                standalone["error"] = type(error).__name__ + ": standalone MCP check failed"
    except Exception as error:
        evidence["error"] = type(error).__name__ + ": workflow configuration failed"
    save("opencode-mcp-list.json", {**evidence, **opencode})
    save("standalone.json", {**evidence, **standalone})
    passed = bool(opencode.get("passed") and standalone.get("passed"))
    print(json.dumps({"passed": passed, "opencode_passed": opencode["passed"],
        "standalone_passed": standalone["passed"], "evidence_directory": str(EVIDENCE)}))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
