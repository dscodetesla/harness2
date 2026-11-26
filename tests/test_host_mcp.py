"""Fixed-target MCP behavior tests; no host programs or network are required."""
import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from harness2 import host_mcp as bridge


class WireModel:
    def __init__(self, data):
        self.data = data
        self.name = data.get("name")

    def model_dump(self, **kwargs):
        return self.data.copy()


def tool(name, **extra):
    return WireModel({"name": name, "inputSchema": {"type": "object"}, **extra})


class HostMCPTests(unittest.IsolatedAsyncioTestCase):
    def session(self, client):
        @asynccontextmanager
        async def session(_):
            yield client
        return session

    def client(self, *tools):
        return SimpleNamespace(
            list_tools=AsyncMock(return_value=SimpleNamespace(tools=list(tools), next_cursor=None)),
            call_tool=AsyncMock(return_value=WireModel({
                "isError": False, "content": [{"type": "text", "text": "result"}],
                "structuredContent": {"n": 3, "mean": 2},
            })),
        )

    def patches(self, client):
        return (
            patch.object(bridge, "_target", return_value=object()),
            patch.object(bridge, "_session", self.session(client)),
        )

    async def test_cad_filter_preserves_actual_annotations(self):
        annotation = {"readOnlyHint": True, "destructiveHint": False}
        client = self.client(
            tool("cad_environment_status", annotations=annotation),
            tool("cad_list_artifacts"), tool("harness2_status"),
            tool("host_capabilities_execute"), tool("jooan_snapshot"),
            tool("camera_status"), tool("fpga_submit_rnd_job"),
        )
        p1, p2 = self.patches(client)
        with p1, p2:
            result = await bridge.discover("cad")
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["tools"][0]["annotations"], annotation)
        self.assertNotIn("annotations", result["tools"][1])
        client.call_tool.assert_not_awaited()

    async def test_eda_actual_tools_and_all_registered_jobs(self):
        names = ["eda_project_registry", "fpga_submit_rnd_job", "fpga_cancel_rnd_job",
                 "kicad_cli_probe", "kicad10_rnd_erc_demo", "vivado_batch_probe",
                 "vitis_installation_probe"]
        client = self.client(*(tool(name) for name in names), tool("harness2_status"),
                             tool("cad_environment_status"))
        p1, p2 = self.patches(client)
        with p1, p2:
            found = await bridge.discover("eda")
            result = await bridge.execute("eda", "fpga_cancel_rnd_job", {"job_id": "known"})
        self.assertEqual([item["name"] for item in found["tools"]], names)
        self.assertFalse(result["result"]["isError"])
        client.call_tool.assert_awaited_once_with(
            "fpga_cancel_rnd_job", {"job_id": "known"}, read_timeout_seconds=60.0)

    async def test_unknown_targets_and_cross_server_tools_never_spawn(self):
        with patch.object(bridge, "_session") as spawn:
            for server, name in [("remote", "fpga_submit_rnd_job"),
                                 ("cad", "harness2_status"), ("eda", "jooan_snapshot"),
                                 ("cad", "fpga_submit_rnd_job")]:
                with self.assertRaises(bridge.HostMCPError):
                    await bridge.execute(server, name, {})
            with self.assertRaises(bridge.HostMCPError):
                await bridge.discover("remote")
            spawn.assert_not_called()

    async def test_allowed_but_unadvertised_tool_cannot_execute(self):
        client = self.client(tool("eda_project_registry"))
        p1, p2 = self.patches(client)
        with p1, p2, self.assertRaisesRegex(bridge.HostMCPError, "not currently advertised"):
            await bridge.execute("eda", "fpga_nonexistent", {})
        client.call_tool.assert_not_awaited()

    async def test_deadline_cleans_up_session(self):
        closed = []
        client = self.client()
        client.list_tools.side_effect = lambda **_: asyncio.sleep(10)
        async def blocked(**_):
            await asyncio.sleep(10)
        client.list_tools.side_effect = blocked

        @asynccontextmanager
        async def session(_):
            try:
                yield client
            finally:
                closed.append(True)

        with patch.object(bridge, "_target", return_value=object()), \
                patch.object(bridge, "_session", session), \
                self.assertRaisesRegex(bridge.HostMCPError, "deadline"):
            await bridge.discover("cad", timeout=0.01)
        self.assertEqual(closed, [True])

    async def test_timeout_rejects_invalid_values(self):
        client = self.client()
        p1, p2 = self.patches(client)
        with p1, p2:
            for value in [0, -1, 121, float("inf"), float("nan"), True, "60"]:
                with self.assertRaises(bridge.HostMCPError):
                    await bridge.discover("cad", timeout=value)
        client.list_tools.assert_not_awaited()

    async def test_schema_and_count_bounds(self):
        client = self.client(tool("cad_environment_status", description="x" * 32768))
        p1, p2 = self.patches(client)
        with p1, p2, self.assertRaisesRegex(bridge.HostMCPError, "32 KiB"):
            await bridge.discover("cad")
        client = self.client(*(tool("eda_tool_" + str(i)) for i in range(51)))
        p1, p2 = self.patches(client)
        with p1, p2, self.assertRaisesRegex(bridge.HostMCPError, "50 allowed"):
            await bridge.discover("eda")

    async def test_pagination_duplicate_names_and_cycles_rejected(self):
        client = self.client()
        client.list_tools.side_effect = [
            SimpleNamespace(tools=[tool("cad_environment_status")], next_cursor="next"),
            SimpleNamespace(tools=[tool("cad_list_artifacts")], next_cursor=None),
        ]
        p1, p2 = self.patches(client)
        with p1, p2:
            result = await bridge.discover("cad")
        self.assertEqual(result["count"], 2)
        self.assertEqual(client.list_tools.await_args.kwargs, {"cursor": "next"})
        for duplicate in [True, False]:
            client = self.client()
            page = SimpleNamespace(
                tools=[tool("cad_environment_status")] if duplicate else [],
                next_cursor="loop")
            client.list_tools.return_value = page
            p1, p2 = self.patches(client)
            with p1, p2, self.assertRaises(bridge.HostMCPError):
                await bridge.discover("cad")

    async def test_errors_redacted_and_tool_errors_preserved(self):
        client = self.client(tool("cad_environment_status"))
        client.list_tools.side_effect = RuntimeError("SECRET_TOKEN server stderr")
        p1, p2 = self.patches(client)
        with p1, p2, self.assertRaises(bridge.HostMCPError) as error:
            await bridge.discover("cad")
        self.assertNotIn("SECRET_TOKEN", str(error.exception))
        client.list_tools.side_effect = None
        client.call_tool.return_value = WireModel({
            "isError": True, "content": [{"type": "text", "text": "Invalid dimensions"}],
        })
        p1, p2 = self.patches(client)
        with p1, p2:
            result = await bridge.execute("cad", "cad_environment_status", {})
        self.assertTrue(result["result"]["isError"])

    async def test_arguments_and_result_are_bounded(self):
        with patch.object(bridge, "_session") as spawn:
            for args in [[], {"x": float("nan")}, {"x": "a" * 65536}]:
                with self.assertRaises(bridge.HostMCPError):
                    await bridge.execute("cad", "cad_environment_status", args)
            spawn.assert_not_called()
        client = self.client(tool("cad_environment_status"))
        client.call_tool.return_value = WireModel({"text": "x" * (1024 * 1024)})
        p1, p2 = self.patches(client)
        with p1, p2, self.assertRaisesRegex(bridge.HostMCPError, "1 MiB"):
            await bridge.execute("cad", "cad_environment_status", {})


if __name__ == "__main__":
    unittest.main()
