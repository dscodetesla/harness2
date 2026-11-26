"""Ephemeral, fixed-target engineering MCP access, independent of ChatGPT plugins.

Requires the MCP 2.x optional environment. Each operation opens a legacy-protocol
stdio client to an existing local server, then closes it. No gateway is exposed.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import sys
from typing import Any

DEFAULT_TIMEOUT = 60.0
MAX_TIMEOUT = 120.0
MAX_TOOLS = 50
MAX_SCHEMA_BYTES = 32 * 1024
MAX_ARGUMENT_BYTES = 64 * 1024
MAX_RESULT_BYTES = 1024 * 1024
CAD_TOOLS = frozenset({
    "cad_environment_status", "cad_list_artifacts", "openscad_make_primitive",
    "numerical_descriptive_statistics", "scilab_batch_smoke_test",
    "freecad_python_api_smoke_test",
})
EDA_PREFIXES = ("eda_", "fpga_", "kicad_", "kicad10_", "vivado_", "vitis_")


class HostMCPError(ValueError):
    """A bounded public error; server stderr and credentials are never included."""


@dataclass(frozen=True)
class Server:
    interpreter: Path
    script: Path


_HOME = Path.home()
SERVERS = {
    "cad": Server(_HOME / "projects/cad-mcp-stack/.venv/bin/python3",
                  _HOME / "projects/cad-mcp-stack/server.py"),
    "eda": Server(_HOME / "projects/cad-mcp-stack/.venv/bin/python3",
                  _HOME / "projects/eda-fpga-mcp/server.py"),
}


def _target(server_id: str) -> Server:
    if not isinstance(server_id, str) or server_id not in SERVERS:
        raise HostMCPError("Unknown MCP server; choose cad or eda")
    target = SERVERS[server_id]
    if not target.script.is_file() or not target.interpreter.is_file():
        raise HostMCPError("Configured MCP server or interpreter is unavailable")
    return target


def _allowed(server_id: str, name: str) -> bool:
    if not isinstance(name, str):
        return False
    return (name in CAD_TOOLS if server_id == "cad"
            else server_id == "eda" and name.startswith(EDA_PREFIXES))


def _timeout(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise HostMCPError("Timeout must be a number from 0 to 120 seconds")
    if not math.isfinite(value) or not 0 < value <= MAX_TIMEOUT:
        raise HostMCPError("Timeout must be greater than 0 and at most 120 seconds")
    return float(value)


def _json_size(value: Any) -> int:
    try:
        return len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8"))
    except (ValueError, TypeError, RecursionError):
        raise HostMCPError("Expected finite JSON data") from None


def _wire(model: Any) -> dict:
    return model.model_dump(mode="json", by_alias=True, exclude_none=True)


@asynccontextmanager
async def _session(target: Server):
    try:
        from mcp.client import Client
        from mcp.client.stdio import StdioServerParameters, stdio_client
    except ImportError:
        raise HostMCPError("MCP 2.x client is unavailable; use the .venv-mcp environment") from None
    # Do not forward API tokens, proxy credentials, or arbitrary Python settings.
    env = {
        "HOME": str(_HOME),
        "PATH": str(_HOME / ".local/bin") + os.pathsep + "/usr/local/bin:/usr/bin:/bin",
        "LANG": "C.UTF-8", "QT_QPA_PLATFORM": "offscreen",
    }
    params = StdioServerParameters(
        command=str(target.interpreter), args=[str(target.script), "stdio"],
        cwd=str(target.script.parent), env=env,
    )
    # Suppress subprocess diagnostics rather than risking leaking credentials.
    # The context manager owns and terminates the ephemeral child.
    with open(os.devnull, "w", encoding="utf-8") as errlog:
        async with stdio_client(params, errlog=errlog) as streams:
            @asynccontextmanager
            async def transport():
                yield streams
            # Existing host servers speak SDK 1.30's initialize handshake.
            async with Client(transport(), mode="legacy", cache=None,
                              raise_exceptions=False) as client:
                yield client


async def _tools(client: Any, server_id: str) -> list[dict]:
    tools = []
    cursor = None
    seen_cursors = set()
    seen_names = set()
    scanned = 0
    while True:
        page = await client.list_tools(cursor=cursor)
        scanned += len(page.tools)
        if scanned > 500:
            raise HostMCPError("MCP discovery exceeded the source tool limit")
        for tool in page.tools:
            name = tool.name
            if not _allowed(server_id, name):
                continue
            data = _wire(tool)
            if name in seen_names:
                raise HostMCPError("MCP server returned duplicate tool names")
            if _json_size(data) > MAX_SCHEMA_BYTES:
                raise HostMCPError("MCP tool schema exceeds 32 KiB")
            if len(tools) >= MAX_TOOLS:
                raise HostMCPError("MCP discovery exceeds 50 allowed tools")
            seen_names.add(name)
            tools.append(data)
        cursor = getattr(page, "next_cursor", None) or getattr(page, "nextCursor", None)
        if not cursor:
            return tools
        if cursor in seen_cursors or len(seen_cursors) >= 10:
            raise HostMCPError("MCP discovery pagination did not terminate")
        seen_cursors.add(cursor)


async def _operation(server_id: str, tool_name: str | None,
                     arguments: dict | None, timeout: float) -> dict:
    target = _target(server_id)
    seconds = _timeout(timeout)
    try:
        async with asyncio.timeout(seconds):
            async with _session(target) as client:
                tools = await _tools(client, server_id)
                if tool_name is None:
                    return {"server": server_id, "transport": "stdio",
                            "tools": tools, "count": len(tools)}
                if tool_name not in {tool["name"] for tool in tools}:
                    raise HostMCPError("Tool is not currently advertised by the configured server")
                result = _wire(await client.call_tool(
                    tool_name, arguments, read_timeout_seconds=seconds))
                if _json_size(result) > MAX_RESULT_BYTES:
                    raise HostMCPError("MCP result exceeds 1 MiB")
                return {"server": server_id, "tool": tool_name, "result": result}
    except HostMCPError:
        raise
    except TimeoutError:
        raise HostMCPError("MCP operation deadline exceeded") from None
    except asyncio.CancelledError:
        raise
    except Exception:
        # Even exception group messages may embed subprocess stderr or secrets.
        raise HostMCPError("MCP operation failed; server unavailable or protocol error") from None


async def discover(server_id: str, *, timeout: float = DEFAULT_TIMEOUT) -> dict:
    """Return live tool schemas, including only actual server annotations.

    Discovery confirms protocol access and advertised operations, not successful
    execution of each underlying CAD/EDA application.
    """
    return await _operation(server_id, None, None, timeout)


async def execute(server_id: str, tool_name: str, arguments: dict,
                  *, timeout: float = DEFAULT_TIMEOUT) -> dict:
    """Call a currently advertised, allowed engineering operation.

    Arguments are validated by the server's actual tool schema. Tool errors
    remain visible as the MCP result's isError; domain result errors are not
    reinterpreted as success. Long builds use the EDA server's async job tools.
    """
    if not isinstance(server_id, str) or server_id not in SERVERS:
        raise HostMCPError("Unknown MCP server; choose cad or eda")
    if not _allowed(server_id, tool_name):
        raise HostMCPError("Tool is not allowed for the configured MCP server")
    if not isinstance(arguments, dict):
        raise HostMCPError("Tool arguments must be a JSON object")
    if _json_size(arguments) > MAX_ARGUMENT_BYTES:
        raise HostMCPError("MCP arguments exceed 64 KiB")
    return await _operation(server_id, tool_name, arguments, timeout)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("discover", "call"))
    parser.add_argument("server", choices=tuple(SERVERS))
    parser.add_argument("tool", nargs="?")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    options = parser.parse_args()
    try:
        if options.action == "discover":
            if options.tool is not None:
                raise HostMCPError("Discovery does not accept a tool name")
            result = asyncio.run(discover(options.server, timeout=options.timeout))
        else:
            if not options.tool:
                raise HostMCPError("Call requires a tool name and JSON arguments on stdin")
            raw = sys.stdin.buffer.read(MAX_ARGUMENT_BYTES + 1)
            if len(raw) > MAX_ARGUMENT_BYTES:
                raise HostMCPError("MCP arguments exceed 64 KiB")
            try:
                arguments = json.loads(raw)
            except (ValueError, UnicodeError):
                raise HostMCPError("Stdin must contain a JSON object") from None
            result = asyncio.run(execute(options.server, options.tool, arguments,
                                         timeout=options.timeout))
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 1 if result.get("result", {}).get("isError", False) else 0
    except HostMCPError as error:
        print(json.dumps({"error": str(error)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
