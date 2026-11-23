"""Regression tests for cluster-adapted bug fixes (#153, #156, #195, #219)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from harness2 import config
from harness2.core import context, selection, tree


class ClusterFixesTests(unittest.TestCase):
    def test_scrub_env_blocks_extended_provider_and_cluster_tokens(self):
        env_in = {
            "PATH": "/usr/bin",
            "GOOGLE_APPLICATION_CREDENTIALS": "/adc.json",
            "OPENROUTER_API_KEY": "sk-or-secret",
            "DEEPSEEK_API_KEY": "sk-ds-secret",
            "HF_TOKEN": "hf_secret",
            "GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_secret",
            "TAILSCALE_API_KEY": "tskey-secret",
            "N8N_API_KEY": "n8n-secret",
        }
        scrubbed = config.scrub_env(env_in)
        self.assertEqual(
            scrubbed, {"PATH": "/usr/bin", "GOOGLE_APPLICATION_CREDENTIALS": "/adc.json"}
        )
        self.assertEqual(
            config.provider_keys("openrouter/google/gemini-2.5-flash"), ("OPENROUTER_API_KEY",)
        )
        self.assertEqual(config.provider_keys("deepseek/deepseek-chat"), ("DEEPSEEK_API_KEY",))
        kept = config.scrub_env(env_in, keep=config.provider_keys("openrouter/model"))
        self.assertEqual(kept["OPENROUTER_API_KEY"], "sk-or-secret")

    def test_skill_frontmatter_accepts_quoted_yaml_name(self):
        surface = tree.SurfaceSpec(
            name="oc",
            always_on=("AGENTS.md",),
            always_on_max=10000,
            always_on_cap_reason="cap",
            skill_dir="skills",
            skill_name_rule="must_match",
            trigger_hint="mention {name}",
            autotrigger_file="AGENTS.md",
            trigger_line="Use {name}: {desc}",
            subagent_requires_mode=False,
            plugin_dir=None,
            hooks_file=None,
        )
        t_double = {
            "AGENTS.md": "Use my-skill when needed.",
            "skills/my-skill/SKILL.md": '---\nname: "my-skill"\ndescription: Test skill\n---\nBody\n',
        }
        t_single = {
            "AGENTS.md": "Use my-skill when needed.",
            "skills/my-skill/SKILL.md": "---\nname: 'my-skill'\ndescription: Test skill\n---\nBody\n",
        }
        self.assertEqual(tree.validate(surface, t_double)["skills"], 1)
        self.assertEqual(tree.validate(surface, t_single)["skills"], 1)

    def test_write_rollout_preserves_duplicate_image_basenames(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            run_dir = tmp_path / "run1"
            (run_dir / "Q1").mkdir(parents=True)
            (run_dir / "Q2").mkdir(parents=True)
            img1 = run_dir / "Q1" / "chart.png"
            img2 = run_dir / "Q2" / "chart.png"
            img1.write_bytes(b"PNG-Q1")
            img2.write_bytes(b"PNG-Q2")

            adapter = SimpleNamespace(
                trajectory=lambda d, obs_trunc=None: "traj",
                deliverable_files=lambda d: {"report.md": "hello"},
                deliverable_images=lambda d: [img1, img2],
                deliverable_assets=lambda d: [img1, img2],
            )
            dest = tmp_path / "ctx"
            (dest / "rollouts").mkdir(parents=True)
            (dest / "deliverables").mkdir(parents=True)
            rv = SimpleNamespace(label="base", run_dir=run_dir)
            failure = context._write_rollout(dest, rv, adapter, trunc=1000, names_only=False)
            self.assertEqual(failure, "")
            imgs = sorted((dest / "deliverables" / "base" / "images").iterdir())
            raws = sorted((dest / "deliverables" / "base" / "raw").iterdir())
            self.assertEqual([p.name for p in imgs], ["Q1__chart.png", "Q2__chart.png"])
            self.assertEqual([p.name for p in raws], ["Q1__chart.png", "Q2__chart.png"])
            self.assertEqual(imgs[0].read_bytes(), b"PNG-Q1")
            self.assertEqual(imgs[1].read_bytes(), b"PNG-Q2")

    def test_distil_parses_multiline_and_markdown_bullet_experience(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "sel"
            root.mkdir()
            reply_text = (
                "<EXPERIENCE>\n"
                "- **cue**:\n"
                "  Multi-sheet financial workbook with formulas\n"
                "- **lesson**:\n"
                "  Always verify cached formula values\n"
                "  after saving openpyxl workbooks\n"
                "evidence:\n"
                "  Base rollout left blank cells; refined rollout populated values.\n"
                "confidence: high\n"
                "</EXPERIENCE>\n"
            )
            fake_prop = SimpleNamespace(
                call=lambda mission, r, tag: SimpleNamespace(text=reply_text, cost_usd=0.01)
            )
            sel = selection.Selection(
                task_id="t1", mode="agg", k=1, chosen_label="cand1", why="better output"
            )
            adapter = SimpleNamespace(spec=SimpleNamespace(name="demo", domain="acct"))
            out = selection._distil(
                "t1",
                sel,
                {},
                adapter=adapter,
                prop=fake_prop,
                root=root,
                bp=selection.BenchPrompts(work="accounting"),
            )
            self.assertEqual(out["cue"], "Multi-sheet financial workbook with formulas")
            self.assertEqual(
                out["lesson"],
                "Always verify cached formula values after saving openpyxl workbooks",
            )
            self.assertEqual(
                out["evidence"], "Base rollout left blank cells; refined rollout populated values."
            )
            self.assertEqual(out["confidence"], "high")


if __name__ == "__main__":
    unittest.main()
