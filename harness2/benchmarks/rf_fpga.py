# Copyright 2026 Dmytro (dscodetesla)
# Licensed under the Apache License, Version 2.0

"""Deterministic RF & FPGA R&D domain adapter for Harness2.

Provides two verifiable engineering tasks with an independent analytical/numerical
verifier (no paid LLM judge required):
  1. `rf-link-433-budget`: 433.92 MHz LoRa link budget (FSPL, Prx, fade margin).
  2. `fpga-fir-fixed-timing`: 16-tap fixed-point FIR bit-growth & static timing WNS.
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
import time
from pathlib import Path

from ..core import tree as harness_tree
from ..core.spec import BenchPrompts, BenchSpec, ChannelSpec
from ..core.tree import SurfaceSpec

RF_FPGA_SURFACE = SurfaceSpec(
    name="rf_fpga",
    always_on=("AGENTS.md",),
    always_on_max=12_000,
    always_on_cap_reason="keep engineering constraints concise",
    skill_dir="skills",
    skill_name_rule="must_match",
    trigger_hint="name `{name}` in AGENTS.md",
    autotrigger_file="AGENTS.md",
    trigger_line="Use skill `{name}` when {desc}.",
    subagent_requires_mode=False,
    plugin_dir=None,
    hooks_file=None,
)

TASKS: dict[str, dict] = {
    "rf-link-433-budget": {
        "domain": "rf-links",
        "prompt": (
            "Compute the 433.92 MHz LoRa link budget from input.json and write result.json "
            "with keys: fspl_db, prx_dbm, fade_margin_db, link_viable (bool). "
            "Use standard free-space path loss: FSPL(dB) = 20*log10(d_km) + 20*log10(f_mhz) + 32.44."
        ),
        "input": {
            "task": "rf-link-433-budget",
            "freq_mhz": 433.92,
            "distance_km": 15.0,
            "ptx_dbm": 30.0,
            "gtx_dbi": 3.0,
            "grx_dbi": 6.0,
            "sys_loss_db": 2.5,
            "rx_sens_dbm": -120.0,
            "min_margin_db": 10.0,
        },
    },
    "fpga-fir-fixed-timing": {
        "domain": "fpga-dsp",
        "prompt": (
            "Compute fixed-point accumulator width and static timing margin from input.json "
            "and write result.json with keys: l1_gain, guard_bits, accum_bits, wns_ns, timing_pass (bool). "
            "Assume input_bits + coeff_bits + ceil(log2(l1_gain)) for accumulator width, and "
            "WNS = (1000/fclk_mhz) - t_comb_ns - t_su_ns - t_skew_ns."
        ),
        "input": {
            "task": "fpga-fir-fixed-timing",
            "input_bits": 14,
            "coeff_bits": 16,
            "coeffs": [1, -2, 4, -8, 16, 32, 64, 128, 128, 64, 32, 16, -8, 4, -2, 1],
            "fclk_mhz": 200.0,
            "t_comb_ns": 4.15,
            "t_su_ns": 0.35,
            "t_skew_ns": 0.10,
        },
    },
}

BASE_AGENTS_MD = (
    "# RF / FPGA Engineering Harness\n\n"
    "Run `scripts/solve_rf_fpga.py input.json result.json` to compute engineering outputs.\n"
)

BASE_SOLVER_PY = """import json, math, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
out = {}
if data["task"] == "rf-link-433-budget":
    # Intentionally simplified baseline (omits sys_loss_db to demonstrate refinement)
    fspl = 20.0 * math.log10(data["distance_km"]) + 20.0 * math.log10(data["freq_mhz"]) + 32.44
    prx = data["ptx_dbm"] + data["gtx_dbi"] + data["grx_dbi"] - fspl
    margin = prx - data["rx_sens_dbm"]
    out = {
        "fspl_db": round(fspl, 3),
        "prx_dbm": round(prx, 3),
        "fade_margin_db": round(margin, 3),
        "link_viable": margin >= data["min_margin_db"],
    }
elif data["task"] == "fpga-fir-fixed-timing":
    # Intentionally simplified baseline (omits t_skew_ns to demonstrate refinement)
    l1 = sum(abs(c) for c in data["coeffs"])
    gb = math.ceil(math.log2(max(l1, 1)))
    acc = data["input_bits"] + data["coeff_bits"] + gb
    wns = (1000.0 / data["fclk_mhz"]) - data["t_comb_ns"] - data["t_su_ns"]
    out = {
        "l1_gain": l1,
        "guard_bits": gb,
        "accum_bits": acc,
        "wns_ns": round(wns, 4),
        "timing_pass": wns >= 0.0,
    }
with open(sys.argv[2], "w", encoding="utf-8") as f:
    json.dump(out, f, indent=2)
"""


def _expected(task_id: str) -> dict:
    d = TASKS[task_id]["input"]
    if task_id == "rf-link-433-budget":
        fspl = 20.0 * math.log10(d["distance_km"]) + 20.0 * math.log10(d["freq_mhz"]) + 32.44
        prx = d["ptx_dbm"] + d["gtx_dbi"] + d["grx_dbi"] - d["sys_loss_db"] - fspl
        margin = prx - d["rx_sens_dbm"]
        return {
            "fspl_db": round(fspl, 3),
            "prx_dbm": round(prx, 3),
            "fade_margin_db": round(margin, 3),
            "link_viable": margin >= d["min_margin_db"],
        }
    l1 = sum(abs(c) for c in d["coeffs"])
    gb = math.ceil(math.log2(max(l1, 1)))
    acc = d["input_bits"] + d["coeff_bits"] + gb
    wns = (1000.0 / d["fclk_mhz"]) - d["t_comb_ns"] - d["t_su_ns"] - d["t_skew_ns"]
    return {
        "l1_gain": l1,
        "guard_bits": gb,
        "accum_bits": acc,
        "wns_ns": round(wns, 4),
        "timing_pass": wns >= 0.0,
    }


class _LocalSubstrate:
    name = "rf_fpga"

    def surface(self) -> SurfaceSpec:
        return RF_FPGA_SURFACE


class RFFPGAAdapter:
    """Deterministic RF/FPGA domain adapter satisfying `BenchmarkAdapter`."""

    def __init__(self, runs_root: Path):
        self.runs_root = Path(runs_root).resolve()
        self.runs_root.mkdir(parents=True, exist_ok=True)
        self.substrate = _LocalSubstrate()
        self.spec = BenchSpec(
            name="rf_fpga",
            runs_root=self.runs_root,
            install_mode="workspace_agents_md",
            prompts=BenchPrompts(
                work="RF link-budget and FPGA fixed-point DSP engineering verification",
                domain_word="subsystem",
                inv_levers="enforce physical unit checks, loss accounting, and timing skew margins",
                dom_levers="add deterministic Friis/FSPL and static timing formulas to scripts/solve_rf_fpga.py",
                yardstick="physical accuracy within numerical tolerance and valid JSON schema",
                deliverable_word="engineering report",
            ),
            channels={
                "proposer": ChannelSpec("opencode", "ollama-local/glm-5.3-flash:cloud"),
                "selector": ChannelSpec("opencode", "ollama-local/glm-5.3-flash:cloud"),
            },
            domain_word="subsystem",
        )

    def tasks(self, split: str = "all") -> list[str]:
        return list(TASKS.keys())

    def domain_of(self, task_id: str) -> str:
        return TASKS[task_id]["domain"]

    def task_prompt(self, task_id: str) -> str:
        return TASKS[task_id]["prompt"]

    def task_files(self, task_id: str) -> Path | None:
        src_dir = self.runs_root / "_inputs" / task_id
        src_dir.mkdir(parents=True, exist_ok=True)
        inp = src_dir / "input.json"
        inp.write_text(json.dumps(TASKS[task_id]["input"], indent=2), encoding="utf-8")
        return src_dir

    def base_harness(self) -> Path:
        b = self.runs_root / "_base_harness"
        harness_tree.write_tree(
            RF_FPGA_SURFACE,
            {"AGENTS.md": BASE_AGENTS_MD, "scripts/solve_rf_fpga.py": BASE_SOLVER_PY},
            b,
            stubs=False,
        )
        return b

    def validate_tree(self, tree: dict[str, str]) -> None:
        harness_tree.validate(RF_FPGA_SURFACE, tree, allow_subagents=False)
        if "scripts/solve_rf_fpga.py" not in tree:
            raise ValueError("scripts/solve_rf_fpga.py is required in the RF/FPGA harness")

    def execute(
        self, task_id: str, harness_dir: Path | None, run_id: str, *, timeout: int | None = None
    ) -> Path:
        run_dir = self.runs_root / "rollouts" / task_id / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        hdir = Path(harness_dir) if harness_dir is not None else self.base_harness()
        solver = hdir / "scripts" / "solve_rf_fpga.py"
        inp_dir = self.task_files(task_id)
        assert inp_dir is not None
        inp_file = inp_dir / "input.json"
        out_file = run_dir / "result.json"

        t0 = time.monotonic()
        proc = subprocess.run(
            [sys.executable, str(solver), str(inp_file), str(out_file)],
            cwd=run_dir,
            capture_output=True,
            text=True,
            timeout=timeout or 30,
            check=False,
        )
        wall = time.monotonic() - t0
        meta = {
            "task_id": task_id,
            "run_id": run_id,
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "wall_s": round(wall, 4),
        }
        (run_dir / "trace.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        return run_dir

    def delivered(self, run_dir: Path) -> bool:
        return (Path(run_dir) / "result.json").is_file()

    def trajectory(self, run_dir: Path, *, obs_trunc: int = 50_000) -> str:
        trace_p = Path(run_dir) / "trace.json"
        if not trace_p.is_file():
            return "[ERROR] missing trace.json"
        meta = json.loads(trace_p.read_text(encoding="utf-8"))
        lines = [
            f"[ACTION] run scripts/solve_rf_fpga.py for {meta['task_id']}",
            f"[OBSERVATION] returncode={meta['returncode']} wall_s={meta['wall_s']}",
        ]
        if meta.get("stdout"):
            lines.append(f"[OBSERVATION] stdout: {meta['stdout'][:obs_trunc]}")
        if meta.get("stderr"):
            lines.append(f"[ERROR] stderr: {meta['stderr'][:obs_trunc]}")
        return "\n".join(lines)

    def deliverable_files(self, run_dir: Path) -> dict[str, str]:
        p = Path(run_dir) / "result.json"
        return {"result.json": p.read_text(encoding="utf-8")} if p.is_file() else {}

    def deliverable_text(self, run_dir: Path) -> str:
        p = Path(run_dir) / "result.json"
        return p.read_text(encoding="utf-8") if p.is_file() else ""

    def score(self, run_dir: Path, task_id: str) -> dict | None:
        p = Path(run_dir) / "result.json"
        if not p.is_file():
            return {"score": 0.0, "passed": False, "reason": "missing result.json"}
        try:
            got = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return {"score": 0.0, "passed": False, "reason": f"invalid json: {exc}"}
        if not isinstance(got, dict):
            return {"score": 0.0, "passed": False, "reason": "result must be a JSON object"}
        exp = _expected(task_id)
        checks: dict[str, bool] = {}
        for k, v in exp.items():
            if k not in got:
                checks[k] = False
            elif isinstance(v, bool):
                checks[k] = type(got[k]) is bool and got[k] is v
            elif isinstance(v, (int, float)):
                checks[k] = (type(got[k]) in (int, float) and math.isfinite(got[k])
                             and abs(got[k] - v) <= 0.05)
            else:
                checks[k] = got[k] == v
        ratio = sum(checks.values()) / max(len(checks), 1)
        return {
            "score": round(ratio, 4),
            "passed": all(checks.values()),
            "checks": checks,
            "expected": exp,
            "got": got,
        }
