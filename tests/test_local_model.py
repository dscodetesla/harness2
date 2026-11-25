# SPDX-License-Identifier: Apache-2.0
"""Metadata fixtures only: no inference and no external HTTP calls."""
import copy
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "check_local_model", Path(__file__).resolve().parents[1] / "scripts/check_local_model.py")
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


class LocalModelTests(unittest.TestCase):
    def setUp(self):
        self.good = {"details": {"format": "gguf"},
                     "parameters": "num_ctx    16384\nstop \"token\"",
                     "capabilities": ["completion", "tools"],
                     "model_info": {"llama.context_length": 131072}}

    def test_explicit_local_context_accepted_without_claiming_runtime(self):
        result = M.validate_metadata(M.MODEL, self.good, 16384)
        self.assertEqual(result["configured_num_ctx"], 16384)
        self.assertIsNone(result["loaded_context_length"])
        self.assertFalse(result["inference_performed"])

    def test_architecture_max_does_not_replace_explicit_context(self):
        data = copy.deepcopy(self.good)
        data["parameters"] = 'stop "token"'
        with self.assertRaisesRegex(RuntimeError, "explicit num_ctx"):
            M.validate_metadata(M.MODEL, data, 16384)

    def test_low_configured_context_rejected(self):
        data = copy.deepcopy(self.good)
        data["parameters"] = "num_ctx 4096"
        with self.assertRaisesRegex(RuntimeError, "below required"):
            M.validate_metadata(M.MODEL, data, 16384)

    def test_remote_and_cloud_rejected(self):
        for field in ("remote_host", "remote_model"):
            data = {**self.good, field: "remote-value"}
            with self.subTest(field=field), self.assertRaisesRegex(RuntimeError, "Cloud/remote"):
                M.validate_metadata(M.MODEL, data, 16384)
        with self.assertRaisesRegex(RuntimeError, "Cloud/remote"):
            M.validate_metadata("llama3.2:cloud", self.good, 16384)

    def test_loaded_runtime_must_match_configured_minimum(self):
        for context in (4096, None):
            ps = {"models": [{"name": M.MODEL, "context_length": context}]}
            with self.subTest(context=context), self.assertRaisesRegex(RuntimeError, "Loaded runtime"):
                M.validate_metadata(M.MODEL, self.good, 16384, ps)
        ps = {"models": [{"name": M.MODEL, "context_length": 16384}]}
        self.assertEqual(M.validate_metadata(M.MODEL, self.good, 16384, ps)
                         ["loaded_context_length"], 16384)

    def test_missing_model_fails_before_other_metadata_requests(self):
        with patch.object(M, "_request", side_effect=RuntimeError("model not found")) as request:
            with self.assertRaisesRegex(RuntimeError, "not found"):
                M.check_local_model()
            request.assert_called_once_with("/api/show", {"model": M.MODEL})

    def test_api_contract_reads_only_metadata(self):
        with patch.object(M, "_request", side_effect=[self.good, {"models": []}]) as request:
            M.check_local_model()
            self.assertEqual([c.args[0] for c in request.call_args_list], ["/api/show", "/api/ps"])

    def test_no_tools_or_context_over_architecture_rejected(self):
        for changes in ({"capabilities": ["completion"]},
                        {"model_info": {"llama.context_length": 8192}}):
            with self.subTest(changes=changes), self.assertRaises(RuntimeError):
                M.validate_metadata(M.MODEL, {**self.good, **changes}, 16384)


if __name__ == "__main__":
    unittest.main()
