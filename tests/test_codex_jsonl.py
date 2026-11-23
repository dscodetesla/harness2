# SPDX-License-Identifier: Apache-2.0
"""Codex JSONL event parsing must not depend on object key order or spacing."""

import json
import tempfile
import unittest
from pathlib import Path

from harness2.substrate.codex import final_message, parse_items, render_events


class CodexJsonlTests(unittest.TestCase):
    def test_valid_json_layouts_keep_deliverable(self):
        event = {"session_id": "s", "type": "item.completed", "item": {
            "id": "1", "type": "agent_message", "text": "done"}}
        layouts = [json.dumps(event), "{ " + json.dumps(event)[1:],
                   json.dumps({"item": event["item"], "type": event["type"]})]
        for line in layouts:
            with self.subTest(line=line), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "events.jsonl"
                path.write_text(line + "\n", encoding="utf-8")
                self.assertEqual(len(parse_items(path)), 1)
                self.assertEqual(final_message(path), "done")
                self.assertIn("[ASSISTANT] done", render_events(
                    path, obs_trunc=1000, max_chars=1000))

    def test_junk_ignored_and_item_updates_keep_order(self):
        first = {"type": "item.started", "item": {"id": "1",
                 "type": "command_execution", "status": "in_progress"}}
        second = {"type": "item.completed", "item": {"id": "2",
                  "type": "agent_message", "text": "done"}}
        updated = {"metadata": "m", "type": "item.completed", "item": {
            "id": "1", "type": "command_execution", "status": "completed",
            "aggregated_output": "ok", "exit_code": 0}}
        lines = ["diagnostic", "{bad", "[]", "null", '{"unrelated": 1}',
                 json.dumps(first), json.dumps(second), json.dumps(updated)]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            path.write_text("\n".join(lines), encoding="utf-8")
            self.assertEqual(parse_items(path), [updated, second])

    def test_timestamp_rollout_with_reordered_keys(self):
        event = {"payload": {"type": "agent_message", "text": "done"},
                 "timestamp": "2026-11-23T00:00:00Z", "type": "event_msg"}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            path.write_text(json.dumps(event), encoding="utf-8")
            self.assertEqual(parse_items(path), [event])
            self.assertEqual(final_message(path), "done")


if __name__ == "__main__":
    unittest.main()
