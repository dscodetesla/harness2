"""Host discovery, bounded context and explicit execution contracts."""
import json
import math
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

from harness2 import host_capabilities as host


class HostCapabilityTests(unittest.TestCase):
    def test_skill_discovery_deduplicates_and_excludes_archive(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            skill = home / ".hermes/skills/rf-budget"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("---\nname: rf-budget\ndescription: RF link budget evidence\n---\nProcedure")
            duplicate = home / ".agents/skills/rf-budget"
            duplicate.parent.mkdir(parents=True)
            duplicate.symlink_to(skill, target_is_directory=True)
            archived = home / ".codex/skills/.archive/old"
            archived.mkdir(parents=True)
            (archived / "SKILL.md").write_text("retired")
            records = host.discover_skills(home, home / "index.json")
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["name"], "rf-budget")
            self.assertFalse(records[0]["runnable"])
            self.assertEqual(records[0]["status"], "instructions_available")

    def test_index_separates_remote_missing_and_available_instructions(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            good = root / "rf/SKILL.md"
            good.parent.mkdir()
            good.write_text("---\nname: rf\ndescription: RF validation\n---\n")
            index = root / "index.json"
            index.write_text(json.dumps({"skills": [
                {"name": "good", "path": "rf/SKILL.md"},
                {"name": "remote", "path": "skill://remote/example"},
                {"name": "missing", "path": "missing/SKILL.md"},
                {"name": "outside", "path": "/etc/passwd"}]}))
            records = host.discover_skills(root / "empty-home", index)
            self.assertEqual({record["status"] for record in records}, {
                "instructions_available", "remote_reference_only",
                "instruction_missing", "instruction_path_outside_approved_roots"})

    def test_instruction_budget_is_utf8_bytes_and_caps_selected_skills(self):
        with tempfile.TemporaryDirectory() as td:
            file = Path(td) / "SKILL.md"
            file.write_text("Антена RF evidence\n" * 3000)
            records = [{"name": "rf", "description": "RF antenna", "path": str(file),
                        "status": "instructions_available", "domains": ["rf"]}]
            with patch.object(host, "discover_skills", return_value=records), \
                 patch.object(host, "_probe_many", return_value=[]), \
                 patch.object(host, "_mcp_registry", return_value=[]):
                result = host.host_capabilities_plan("RF antenna", 1, 1000)
            self.assertEqual(len(result["skills"]), 1)
            self.assertLessEqual(result["instruction_bytes"], 1000)
            self.assertTrue(result["skills"][0]["instructions_truncated"])

    def test_fixed_version_execution_rejects_parameters_and_unknown_commands(self):
        with patch.object(host, "_find_executable", return_value=None):
            self.assertEqual(host.host_capabilities_execute("adb_version")["status"], "unavailable")
        with self.assertRaises(ValueError):
            host.host_capabilities_execute("adb_version", {"serial": "device"})
        with self.assertRaises(ValueError):
            host.host_capabilities_execute("shell", {"command": "id"})

    def test_rf_computation_and_nonfinite_boolean_validation(self):
        inputs = dict(frequency_mhz=433.92, distance_km=15, tx_dbm=30,
                      tx_gain_dbi=3, rx_gain_dbi=6, loss_db=2.5, sensitivity_dbm=-120)
        result = host.host_capabilities_execute("rf_link_budget", inputs)
        self.assertAlmostEqual(result["received_dbm"], -72.20953, places=3)
        self.assertAlmostEqual(result["margin_db"], 47.79047, places=3)
        for bad in (True, float("nan"), float("inf"), 1e308):
            with self.assertRaises(ValueError):
                host.host_capabilities_execute("rf_link_budget", {**inputs, "tx_dbm": bad})

    def test_registered_mcp_delegate_preserves_server_tool_and_arguments(self):
        async def execute(server, tool, arguments, timeout):
            return {"server": server, "tool": tool, "result": {"isError": False, "arguments": arguments}}
        fake = types.SimpleNamespace(execute=execute)
        import sys
        with patch.dict(sys.modules, {"harness2.host_mcp": fake}), \
             patch("harness2.host_mcp", fake, create=True):
            value = host.host_capabilities_execute("mcp_call",
                {"server": "cad", "tool": "system_info", "arguments": {}})
        self.assertEqual(value["server"], "cad")
        self.assertEqual(value["tool"], "system_info")
        with self.assertRaises(ValueError):
            host.host_capabilities_execute("mcp_call", {"server": "arbitrary", "tool": "x", "arguments": {}})


    def test_domain_failure_is_not_transport_success(self):
        error = {"result": {"isError": False, "content": [{"type": "text", "text": '{"error":"OpenSCAD unavailable"}'}]}}
        result = host._mcp_execution_evidence(error, "openscad_make_primitive")
        self.assertTrue(result["transport_completed"])
        self.assertFalse(result["execution_verified"])
        self.assertEqual(result["operation_status"], "failed")
        unknown = {"result": {"isError": False, "content": [{"type": "text", "text": "{}"}]}}
        self.assertFalse(host._mcp_execution_evidence(unknown, "unknown")["execution_verified"])

    def test_read_instruction_is_scoped_bounded_and_rejects_escape_extensions(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            skill = root / "skill/SKILL.md"
            skill.parent.mkdir()
            skill.write_text("instructions")
            reference = skill.parent / "references/guide.md"
            reference.parent.mkdir()
            reference.write_text("evidence " * 4000)
            records = [{"name": "rf", "path": str(skill), "source": "installed", "status": "instructions_available"}]
            with patch.object(host, "discover_skills", return_value=records):
                result = host.host_capabilities_execute("read_instruction", {"skill_path": str(skill), "reference": "references/guide.md"})
                self.assertTrue(result["truncated"])
                self.assertLessEqual(len(result["text"].encode()), 16000)
                for ref in ("../../outside.md", ".env", "/etc/passwd", "references/secret.exe"):
                    with self.assertRaises(ValueError):
                        host.host_capabilities_execute("read_instruction", {"skill_path": str(skill), "reference": ref})
                (skill.parent / "linked.md").symlink_to(root / "outside.md")
                with self.assertRaises(ValueError):
                    host.host_capabilities_execute("read_instruction", {"skill_path": str(skill), "reference": "linked.md"})

    def test_plan_prefers_pinned_plugin_instructions_over_duplicate_name(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "SKILL.md"
            path.write_text("RF budget guidance")
            common = {"name": "rf-budget", "path": str(path), "description": "RF budget", "status": "instructions_available"}
            records = [{**common, "source": "installed"}, {**common, "source": "plugin_index"}]
            with patch.object(host, "discover_skills", return_value=records), patch.object(host, "_probe_many", return_value=[]), patch.object(host, "_mcp_registry", return_value=[]):
                plan = host.host_capabilities_plan("RF budget")
            self.assertEqual(len(plan["skills"]), 1)
            self.assertEqual(plan["skills"][0]["source"], "plugin_index")
            self.assertEqual(len(plan["alternative_instructions"]), 1)

    def test_native_cad_evidence_checks_domain_exit_and_passed_flag(self):
        for tool in ("scilab_batch_smoke_test", "freecad_python_api_smoke_test"):
            def reply(payload):
                return {"result": {"isError": False, "structuredContent": payload}}
            good = host._mcp_execution_evidence(reply({"exit_code":0,"passed":True}), tool)
            self.assertTrue(good["execution_verified"])
            for bad in ({"exit_code":1,"passed":True}, {"exit_code":0,"passed":False}):
                result = host._mcp_execution_evidence(reply(bad), tool)
                self.assertFalse(result["execution_verified"])
                self.assertEqual(result["operation_status"], "failed")

    def test_product_design_script_reference_is_readable_as_data(self):
        records = host.discover_skills()
        skill = next((item for item in records if item.get("name") == "image-to-code" and item.get("source") == "plugin_index"), None)
        if skill is None:
            self.skipTest("Private Product Design source snapshot is not deployed")
        reply = host.host_capabilities_execute("read_instruction", {
            "skill_path": skill["path"], "reference": "../../scripts/bootstrap-prototype.mjs"})
        self.assertEqual(reply["status"], "instruction_data")
        self.assertFalse(reply["runnable"])
        self.assertTrue(reply["path"].endswith("bootstrap-prototype.mjs"))
        self.assertTrue(reply["text"])

    def test_android_requires_already_authorized_device_and_valid_serial(self):
        with patch.object(host, "_adb_list", return_value={"status": "observed", "devices": [{"serial": "phone", "state": "unauthorized"}]}), patch.object(host, "_adb_shell") as shell:
            result = host.host_capabilities_execute("adb_screen_capture_audit", {"serial": "phone"})
            self.assertEqual(result["status"], "blocked")
            shell.assert_not_called()
        for serial in ("-s other", "phone;id", "phone\nreboot"):
            with self.assertRaises(ValueError):
                host.host_capabilities_execute("adb_screen_capture_audit", {"serial": serial})

    def test_android_audit_observations_remain_scoped_and_no_write_commands(self):
        def read(serial, command):
            self.assertEqual(serial, "phone")
            self.assertNotIn(command[0], ("screencap", "screenrecord", "install", "root", "connect"))
            self.assertNotIn("put", command)
            text = "mProjectionGrant=null" if command == ["dumpsys", "media_projection"] else "null"
            return {"status": "OBSERVED", "exit_code": 0, "stdout": text, "stderr": ""}
        with patch.object(host, "_adb_list", return_value={"status": "observed", "devices": [{"serial": "phone", "state": "device"}]}), patch.object(host, "_adb_shell", side_effect=read):
            result = host.host_capabilities_execute("adb_screen_capture_audit", {"serial": "phone", "user_id": 10})
        self.assertEqual(result["checks"]["media_projection"]["observation"], "NOT_OBSERVED_AT_QUERY_TIME")
        self.assertFalse(result["device_writes_performed"])
        self.assertIn("Other profiles are NOT_CHECKED", result["limitations"])


    def test_cached_remote_recommendation_does_not_probe_or_claim_live_readiness(self):
        catalog = [{"id": "x99mg", "hostname": "X99MG", "transport_configured": True,
                    "live_verified": False, "inventory_observed_at": "recorded-time",
                    "cached_inventory": {"ok": True, "result": {"tools": [
                        {"tool": "vivado", "status": "version_verified"},
                        {"tool": "kicad", "status": "version_verified"}]}}}]
        local = [{"tool": "vivado", "status": "unavailable"}]
        recommendations = host._remote_recommendations(["fpga"], local, catalog)
        self.assertEqual(len(recommendations), 1)
        self.assertEqual(recommendations[0]["tool"], "vivado")
        self.assertFalse(recommendations[0]["live_verified"])
        self.assertEqual(recommendations[0]["verification_recipe"]["parameters"]["arguments"]["action"], "vivado_version")

    def test_remote_call_registration_missing_transport_and_recursion_gates(self):
        with patch.object(host, "_remote_catalog", return_value=[]):
            with self.assertRaisesRegex(ValueError, "not configured"):
                host.host_capabilities_execute("remote_call", {"host": "unregistered", "operation": "inventory", "arguments": {}})
        catalog = [{"id": "x99mg", "transport_configured": False}]
        with patch.object(host, "_remote_catalog", return_value=catalog):
            result = host.host_capabilities_execute("remote_call", {"host": "x99mg", "operation": "inventory", "arguments": {}})
            self.assertEqual(result["status"], "blocked")
        with self.assertRaisesRegex(ValueError, "Recursive"):
            host.host_capabilities_execute("remote_call", {"host": "x99mg", "operation": "execute", "arguments": {"action": "remote_call", "parameters": {}}})
        with self.assertRaises(ValueError):
            host.host_capabilities_execute("remote_call", {"host": "x99mg", "operation": "shell", "arguments": {}})

    def test_remote_call_preserves_evidence_and_caps_oversized_result(self):
        import sys
        from unittest.mock import MagicMock
        remote = types.SimpleNamespace(call=MagicMock(return_value={"ok": True,
            "host": "x99mg", "operation": "inventory", "transport_verified": True,
            "transport": "ssh-forced-command", "result": {"large": "x" * 140000}}))
        with patch.object(host, "_remote_catalog", return_value=[{"id": "x99mg", "transport_configured": True}]), \
             patch.dict(sys.modules, {"harness2.host_remote": remote}), patch("harness2.host_remote", remote, create=True):
            result = host.host_capabilities_execute("remote_call", {"host": "x99mg", "operation": "inventory", "arguments": {}})
        remote.call.assert_called_once_with("x99mg", "inventory", {})
        self.assertTrue(result["result_omitted"])
        self.assertTrue(result["transport_verified"])
        self.assertNotIn("result", result)

    def test_no_optional_remote_module_yields_empty_catalog(self):
        import builtins
        original = builtins.__import__
        def optional_missing(name, globals=None, locals=None, fromlist=(), level=0):
            if "host_remote" in fromlist:
                raise ImportError("Optional remote adapter absent")
            return original(name, globals, locals, fromlist, level)
        with patch("builtins.__import__", side_effect=optional_missing):
            self.assertEqual(host._remote_catalog(), [])


if __name__ == "__main__":
    unittest.main()
