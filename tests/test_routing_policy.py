"""Routing selection checks use temporary non-secret preference files only."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from harness2 import routing_policy as route


class RoutingPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "routing.json"
        patcher = patch.object(route, "POLICY_PATH", self.path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, **changes):
        self.path.write_text(json.dumps({**route.LEGACY, **changes}))

    def test_missing_file_keeps_legacy_local_default(self):
        self.assertEqual(route.selection(), {"profile": "ollama_local",
                         "allow_cloud": False, "source": "legacy_default"})
        self.assertFalse(route.policy()["configured"])

    def test_authorized_default_and_explicit_denial(self):
        self.write(default_profile="ollama_glm_cloud", cloud_authorized=True,
                   prefer_subscriptions=True, max_parallel=4)
        self.assertEqual(route.selection()["profile"], "ollama_glm_cloud")
        self.assertTrue(route.selection()["allow_cloud"])
        self.assertEqual(route.selection(allow_cloud=False)["profile"], "ollama_local")
        with self.assertRaises(ValueError):
            route.selection("ollama_glm_cloud", False)

    def test_explicit_true_selects_cloud_without_stored_authorization(self):
        self.assertEqual(route.selection(allow_cloud=True)["profile"], "ollama_glm_cloud")
        self.assertTrue(route.selection(allow_cloud=True)["allow_cloud"])
        self.assertEqual(route.selection("ollama_local", True)["profile"], "ollama_local")
        self.assertFalse(route.selection("ollama_local", True)["allow_cloud"])

    def test_explicit_cloud_with_omitted_consent_requires_saved_authorization(self):
        with self.assertRaises(ValueError):
            route.selection("ollama_glm_cloud")
        self.write(cloud_authorized=True)
        self.assertTrue(route.selection("ollama_glm_cloud")["allow_cloud"])

    def test_unauthorized_cloud_default_fails_closed(self):
        self.write(default_profile="ollama_glm_cloud")
        with self.assertRaises(ValueError):
            route.selection()
        self.assertEqual(route.selection(allow_cloud=False)["profile"], "ollama_local")

    def test_invalid_policy_is_not_silently_ignored(self):
        for raw in ["{", "[]", "null", json.dumps({**route.LEGACY, "extra": 1}),
                    json.dumps({"default_profile": "ollama_local"}), " " * 4097]:
            self.path.write_text(raw)
            with self.subTest(raw=raw[:80]), self.assertRaises(ValueError):
                route.policy()

    def test_duplicate_json_keys_are_rejected(self):
        self.path.write_text('{"default_profile":"ollama_glm_cloud","cloud_authorized":false,'
                             '"cloud_authorized":true,"prefer_subscriptions":true,"max_parallel":1}')
        with self.assertRaisesRegex(ValueError, "duplicate JSON keys"):
            route.policy()

    def test_symlink_and_dangling_symlink_are_rejected(self):
        target = Path(self.temp.name) / "real.json"
        target.write_text(json.dumps(route.LEGACY))
        self.path.symlink_to(target)
        with self.assertRaises(ValueError):
            route.policy()
        target.unlink()
        with self.assertRaises(ValueError):
            route.policy()

    def test_open_uses_nofollow_and_existing_access_error_is_not_default(self):
        self.write()
        real_open = os.open
        with patch.object(route.os, "open", wraps=real_open) as opened:
            route.policy()
            self.assertTrue(opened.call_args.args[1] & os.O_NOFOLLOW)
        with patch.object(route.os, "open", side_effect=PermissionError("denied")):
            with self.assertRaisesRegex(ValueError, "cannot be opened"):
                route.policy()

    def test_nonregular_file_is_rejected_without_blocking(self):
        os.mkfifo(self.path)
        with self.assertRaisesRegex(ValueError, "regular file"):
            route.policy()

    def test_schema_types_are_strict(self):
        invalid = [{"max_parallel": True}, {"max_parallel": 0}, {"max_parallel": 5},
                   {"max_parallel": 1.0}, {"cloud_authorized": 1},
                   {"prefer_subscriptions": 0}, {"default_profile": "arbitrary"},
                   {"default_profile": False}]
        for changes in invalid:
            self.write(**changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                route.policy()

    def test_explicit_input_types_are_strict(self):
        for profile, consent in [(False, None), ("arbitrary", None),
                                 (None, 1), (None, "true")]:
            with self.subTest(profile=profile, consent=consent), self.assertRaises(ValueError):
                route.selection(profile, consent)


if __name__ == "__main__":
    unittest.main()
