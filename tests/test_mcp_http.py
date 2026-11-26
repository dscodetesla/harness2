"""HTTP bearer/authentication and real MCP demo lifecycle; no model calls."""
import asyncio
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
try:
    import mcp
    from harness2.mcp_http import initialize_token, load_token
    HAS_MCP = True
except ImportError:
    HAS_MCP = False


@unittest.skipUnless(HAS_MCP, "Install the mcp optional dependency")
class MCPHTTPTests(unittest.TestCase):
    def test_token_permissions_and_no_cloud_environment(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "token"
            with patch.dict(os.environ, {}, clear=True):
                initialize_token(path)
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                self.assertGreaterEqual(len(load_token(path)), 32)
                path.chmod(0o644)
                with self.assertRaisesRegex(ValueError, "0600"):
                    load_token(path)
                with self.assertRaises(FileExistsError):
                    initialize_token(path)

    def test_http_401_and_mcp_demo_lifecycle(self):
        with tempfile.TemporaryDirectory() as td:
            directory = Path(td)
            token_file = directory / "token"
            initialize_token(token_file)
            token = token_file.read_text().strip()
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            env = {**os.environ, "HARNESS2_MCP_RUNS_DIR": str(directory / "jobs")}
            env.pop("HARNESS2_MCP_HTTP_TOKEN", None)
            process = subprocess.Popen(
                [sys.executable, "-m", "harness2.mcp_http", "--port", str(port),
                 "--token-file", str(token_file)],
                cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            url = f"http://127.0.0.1:{port}/mcp"
            try:
                deadline = time.monotonic() + 10
                while True:
                    try:
                        urllib.request.urlopen(url, timeout=1)
                    except urllib.error.HTTPError as exc:
                        self.assertEqual(exc.code, 401)
                        break
                    except urllib.error.URLError:
                        if process.poll() is not None:
                            self.fail(process.stderr.read().decode())
                        if time.monotonic() > deadline:
                            self.fail("HTTP server did not start")
                        time.sleep(.05)
                wrong = urllib.request.Request(url, headers={"Authorization": "Bearer invalid"})
                with self.assertRaises(urllib.error.HTTPError) as error:
                    urllib.request.urlopen(wrong, timeout=2)
                self.assertEqual(error.exception.code, 401)
                asyncio.run(self.protocol(url, token))
            finally:
                process.terminate()
                process.wait(timeout=10)
                process.stderr.close()

    async def protocol(self, url, token):
        import httpx2
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client
        async with httpx2.AsyncClient(headers={"Authorization": "Bearer " + token}) as http:
            async with streamable_http_client(url, http_client=http) as streams:
                async with ClientSession(streams[0], streams[1]) as client:
                    await client.initialize()
                    tools = await client.list_tools()
                    self.assertEqual(len(tools.tools), 10)
                    def data(reply):
                        self.assertFalse(reply.is_error, reply.content)
                        return reply.structured_content or json.loads(reply.content[0].text)
                    started = data(await client.call_tool("harness2_start_demo",
                                                        {"k": 1, "seconds": 60}))
                    run_id = started["run_id"]
                    for _ in range(150):
                        state = data(await client.call_tool("harness2_run_status",
                                                            {"run_id": run_id}))
                        if state["state"] not in ("starting", "running", "cancelling"):
                            break
                        await asyncio.sleep(.1)
                    self.assertEqual(state["state"], "succeeded", state)
                    result = data(await client.call_tool("harness2_results", {"run_id": run_id}))
                    self.assertEqual(result["demo"]["done"], 2)
                    self.assertEqual(result["demo"]["failed"], 0)


if __name__ == "__main__":
    unittest.main()
