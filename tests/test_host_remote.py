"""Scoped multi-host transport contracts; mocks never contact SSH."""
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
from harness2 import host_remote as remote


class HostRemoteTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)
        self.addCleanup(patch.stopall)
        patch.object(remote, "HOST_HOME", self.home).start()
        config = self.home / ".config/harness2"
        (config / "ssh").mkdir(parents=True)
        self.registry = config / "hosts.json"
        patch.object(remote, "REGISTRY", self.registry).start()
        patch.dict(os.environ, {"HARNESS2_REMOTE_RECEIVE": "0"}).start()
        self.entry = {
            "id": "x99mg", "hostname": "X99MG", "ssh_host": "100.64.169.22",
            "ssh_user": "user", "ssh_port": 2222, "identity_file": str(config / "ssh/x99mg"),
            "known_hosts_file": str(config / "ssh/known_hosts"),
            "python": remote.PYTHON,
            "inventory_path": str(self.home / "src/harness2-host-capabilities-private/evidence/x99mg/inventory.json"),
        }
        for name in ("identity_file", "known_hosts_file"):
            path = Path(self.entry[name]); path.write_text("dummy"); path.chmod(0o600)
        self.write_registry()

    def write_registry(self):
        self.registry.write_text(json.dumps({"version": 1, "hosts": [self.entry]}))
        self.registry.chmod(0o600)

    def subprocess(self, argv, **kwargs):
        self.argv = argv
        self.kwargs = kwargs
        request = json.loads(kwargs["input"])
        kwargs["stdout"].write(json.dumps({
            "version": 1, "ok": True, "hostname": "X99MG",
            "operation": request["operation"], "result": {"host": "X99MG"},
        }).encode())
        return SimpleNamespace(returncode=0)

    def test_registered_call_fixed_argv_and_verified_identity(self):
        with patch.object(remote.subprocess, "run", side_effect=self.subprocess):
            reply = remote.call("x99mg", "inventory", {})
        self.assertTrue(reply["transport_verified"])
        self.assertEqual(reply["result"]["host"], "X99MG")
        self.assertEqual(self.argv[1:3], ["-p", "2222"])
        self.assertEqual(self.argv[-1], remote.RECEIVER)
        self.assertEqual(self.argv[-2], "user@100.64.169.22")
        self.assertIn("BatchMode=yes", self.argv)
        self.assertIn("StrictHostKeyChecking=yes", self.argv)
        self.assertIn("IdentitiesOnly=yes", self.argv)
        self.assertNotIn("shell", self.kwargs)
        self.assertEqual(self.kwargs["timeout"], 120)

    def test_unknown_host_and_invalid_operation_never_connect(self):
        with patch.object(remote.subprocess, "run") as run:
            for host, op, args in [("not-registered", "inventory", {}),
                                  ("x99mg", "shell", {"command": "id"}),
                                  ("x99mg", "inventory", {"extra": 1}),
                                  ("x99mg", "plan", {"query": "RF", "max_skills": 6}),
                                  ("x99mg", "execute", {"action": "remote_call"}),
                                  ("x99mg", "execute", {"action": "mcp_call", "command": "id"})]:
                with self.assertRaises(remote.HostRemoteError):
                    remote.call(host, op, args)
            run.assert_not_called()

    def test_remote_context_forbids_recursive_calls(self):
        with patch.dict(os.environ, {"HARNESS2_REMOTE_RECEIVE": "1"}), \
                patch.object(remote.subprocess, "run") as run:
            with self.assertRaisesRegex(remote.HostRemoteError, "recursion"):
                remote.call("x99mg", "inventory", {})
            run.assert_not_called()

    def test_registry_rejects_nonprivate_or_arbitrary_commands(self):
        self.registry.chmod(0o644)
        with self.assertRaises(remote.HostRemoteError):
            remote.host_catalog()
        self.entry["python"] = "/bin/sh"
        self.write_registry()
        with self.assertRaises(remote.HostRemoteError):
            remote.host_catalog()

    def test_registry_rejects_ssh_option_injection_and_external_paths(self):
        for field, value in [("ssh_host", "-oProxyCommand=id"), ("ssh_user", "user;id"),
                             ("identity_file", "/tmp/key"), ("inventory_path", "/etc/passwd")]:
            previous = self.entry[field]
            self.entry[field] = value; self.write_registry()
            with self.assertRaises(remote.HostRemoteError):
                remote.host_catalog()
            self.entry[field] = previous

    def test_registry_rejects_invalid_ports(self):
        for port in [0, -1, 65536, True, "2222"]:
            self.entry["ssh_port"] = port
            self.write_registry()
            with self.assertRaises(remote.HostRemoteError):
                remote.host_catalog()

    def test_catalog_reads_cache_without_claiming_live_readiness(self):
        path = Path(self.entry["inventory_path"]); path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"ok": True, "observed_at": "2026-11-26T00:00:00Z",
                                   "result": {"host": "X99MG", "skill_count": 113}}))
        with patch.object(remote.subprocess, "run") as run:
            record = remote.host_catalog()[0]
            run.assert_not_called()
        self.assertFalse(record["live_verified"])
        self.assertEqual(record["inventory_status"], "cached")
        self.assertEqual(record["inventory_observation_source"], "remote_reply")
        self.assertEqual(record["cached_inventory"]["skill_count"], 113)

    def test_catalog_missing_registry_is_empty_and_cache_mtime_is_labeled(self):
        path = Path(self.entry["inventory_path"]); path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"host": "X99MG"}))
        self.assertEqual(remote.host_catalog()[0]["inventory_observation_source"], "cache_file_mtime")
        self.registry.unlink()
        self.assertEqual(remote.host_catalog(), [])

    def test_request_and_response_bounds(self):
        with self.assertRaises(remote.HostRemoteError):
            remote.call("x99mg", "execute", {"action": "mcp_call", "parameters": {"x": "x" * 65536}})
        def oversized(argv, **kwargs):
            kwargs["stdout"].write(b"x" * (remote.MAX_RESPONSE + 1))
            return SimpleNamespace(returncode=0)
        with patch.object(remote.subprocess, "run", side_effect=oversized):
            with self.assertRaisesRegex(remote.HostRemoteError, "256 KiB"):
                remote.call("x99mg", "inventory", {})

    def test_transport_error_does_not_expose_stderr(self):
        with patch.object(remote.subprocess, "run", return_value=SimpleNamespace(returncode=255)):
            with self.assertRaises(remote.HostRemoteError) as error:
                remote.call("x99mg", "inventory", {})
        self.assertNotIn("SECRET", str(error.exception))

    def test_receiver_dispatches_fixed_api_and_rejects_recursion(self):
        request = {"version": 1, "operation": "execute", "arguments": {
            "action": "mcp_call", "parameters": {"server": "cad", "tool": "numerical_descriptive_statistics",
                                                "arguments": {"values": [1, 2, 3]}}}}
        with patch("harness2.host_capabilities.execute", return_value={"verified": True}) as execute:
            reply = remote.receive(json.dumps(request).encode())
        self.assertTrue(reply["ok"])
        execute.assert_called_once_with(**request["arguments"])
        request["arguments"]["action"] = "remote_call"
        with patch("harness2.host_capabilities.execute") as execute:
            reply = remote.receive(json.dumps(request).encode())
        self.assertFalse(reply["ok"])
        execute.assert_not_called()

    def test_receiver_errors_are_bounded_and_redacted(self):
        for raw in [b"x" * 65537, b"invalid", b'{"version":1,"operation":"shell","arguments":{}}']:
            reply = remote.receive(raw)
            self.assertFalse(reply["ok"])
            self.assertEqual(reply["error"], "Registered remote operation failed")
        request = {"version": 1, "operation": "inventory", "arguments": {}}
        with patch("harness2.host_capabilities.inventory", side_effect=RuntimeError("SECRET_TOKEN")):
            reply = remote.receive(json.dumps(request).encode())
        self.assertNotIn("SECRET", json.dumps(reply))


if __name__ == "__main__":
    unittest.main()
