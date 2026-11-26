"""Independent deterministic held-out RF qualification; never changes generated source."""
from __future__ import annotations

import json
import math
import random
import subprocess
import sys

TOLERANCE_DB = 0.002
MAX_FAILURE_DETAILS = 8


def reference(data):
    """Full-precision free-space budget; round output fields only, never the predicate."""
    distance_m = data["distance_km"] * 1000.0
    frequency_hz = data["freq_mhz"] * 1_000_000.0
    # Algebraically equivalent to the task's 32.44 km/MHz convention, using SI units.
    attenuation = 20.0 * math.log10(distance_m * frequency_hz) - 147.56
    received = (data["ptx_dbm"] + data["gtx_dbi"] + data["grx_dbi"]
                - data["sys_loss_db"] - attenuation)
    margin = received - data["rx_sens_dbm"]
    return {"fspl_db": attenuation, "prx_dbm": received,
            "fade_margin_db": margin, "link_viable": margin >= data["min_margin_db"]}


def heldout_cases():
    cases = []
    for frequency in (433.92, 915.0, 5800.0):
        for distance in (0.1, 1.0, 15.0, 25.0):
            for loss in (0.0, 2.5, 11.0):
                cases.append({"task": "rf-link-433-budget", "freq_mhz": frequency,
                    "distance_km": distance, "ptx_dbm": 27.0, "gtx_dbi": 2.0,
                    "grx_dbi": 5.0, "sys_loss_db": loss,
                    "rx_sens_dbm": -110.0, "min_margin_db": 10.0})
    generator = random.Random(882173)
    for _ in range(16):
        cases.append({"task": "rf-link-433-budget",
            "freq_mhz": generator.uniform(300, 6000),
            "distance_km": generator.uniform(0.05, 40),
            "ptx_dbm": generator.uniform(-5, 30),
            "gtx_dbi": generator.uniform(-2, 8), "grx_dbi": generator.uniform(-2, 12),
            "sys_loss_db": generator.uniform(0, 15),
            "rx_sens_dbm": generator.uniform(-125, -85),
            "min_margin_db": generator.uniform(0, 20)})
    # Values straddle the predicate boundary by less than output rounding granularity.
    base = {"task": "rf-link-433-budget", "freq_mhz": 433.92, "distance_km": 15.0,
            "ptx_dbm": 30.0, "gtx_dbi": 3.0, "grx_dbi": 6.0,
            "sys_loss_db": 2.5, "rx_sens_dbm": -120.0, "min_margin_db": 10.0}
    boundary = reference(base)["fade_margin_db"]
    thresholds = (boundary - 0.0002, boundary + 0.0002,
                  (boundary + round(boundary, 3)) / 2.0, boundary + 0.0012)
    for threshold in thresholds:
        cases.append({**base, "min_margin_db": threshold})
    return cases


def _checks(got, expected):
    if not isinstance(got, dict):
        return {"object": False}
    checks = {}
    for key in ("fspl_db", "prx_dbm", "fade_margin_db"):
        value = got.get(key)
        checks[key] = (type(value) in (int, float) and math.isfinite(value)
                       and abs(value - expected[key]) <= TOLERANCE_DB)
    value = got.get("link_viable")
    checks["link_viable"] = type(value) is bool and value is expected["link_viable"]
    return checks


def validate_source(source, *, gate, cases=None):
    """None uses held-out cases; explicit 1..8 visible cases are a training suite."""
    if not isinstance(source, str) or not callable(gate):
        raise TypeError("source text and callable AST gate are required")
    suite = "heldout" if cases is None else "training"
    if cases is None:
        cases = heldout_cases()
    else:
        if not isinstance(cases, list) or not 1 <= len(cases) <= 8:
            raise ValueError("training cases must be a list containing 1..8 inputs")
        numeric_keys = {"freq_mhz", "distance_km", "ptx_dbm", "gtx_dbi", "grx_dbi",
                        "sys_loss_db", "rx_sens_dbm", "min_margin_db"}
        clean = []
        for case in cases:
            if (not isinstance(case, dict) or not numeric_keys <= set(case)
                    or set(case) - numeric_keys - {"task"}):
                raise ValueError("training case has missing or unsupported fields")
            if "task" in case and case["task"] != "rf-link-433-budget":
                raise ValueError("unsupported training task")
            if any(type(case[key]) not in (int, float) or not math.isfinite(case[key])
                   for key in numeric_keys):
                raise ValueError("training values must be finite native numbers")
            if not 0.001 <= case["freq_mhz"] <= 1000000 or not 0.000001 <= case["distance_km"] <= 100000:
                raise ValueError("training frequency/distance outside supported range")
            if case["sys_loss_db"] < 0 or any(abs(case[key]) > 1000 for key in numeric_keys - {"freq_mhz", "distance_km"}):
                raise ValueError("training dB values outside supported range")
            clean.append({**case, "task": "rf-link-433-budget"})
        cases = clean
    gate(source)
    prefix = ("import json, math, resource, sys\n"
              "resource.setrlimit(resource.RLIMIT_AS, (268435456, 268435456))\n"
              "resource.setrlimit(resource.RLIMIT_CPU, (2, 2))\n")
    suffix = ("\n_cases=json.load(sys.stdin)\n"
              "_results=[solve(_case) for _case in _cases]\n"
              "json.dump(_results,sys.stdout,allow_nan=False)\n")
    report = {"qualified": False, "suite": suite, "case_count": len(cases), "passed": 0,
              "failed": len(cases), "tolerance_db": TOLERANCE_DB,
              "oracle": "independent SI-unit free-space calculation with task constant",
              "failure_details": []}
    try:
        result = subprocess.run([sys.executable, "-I", "-c", prefix + source + suffix],
            input=json.dumps(cases), capture_output=True, text=True, timeout=5,
            env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}, check=False)
        report["returncode"] = result.returncode
        if result.returncode:
            report["error"] = "candidate_runtime_failure"
            report["stderr_tail"] = result.stderr[-1000:]
            return report
        if len(result.stdout.encode()) > 131072:
            report["error"] = "candidate_output_exceeded_128KiB"
            return report
        values = json.loads(result.stdout, parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError("Non-finite output")))
        if not isinstance(values, list) or len(values) != len(cases):
            report["error"] = "candidate_result_count_mismatch"
            return report
        failed = []
        for index, (data, got) in enumerate(zip(cases, values)):
            expected = reference(data)
            checks = _checks(got, expected)
            if not all(checks.values()):
                failed.append({"case": index, "checks": checks, "input": data,
                               "expected": expected, "got": got})
        report.update(qualified=not failed, passed=len(cases)-len(failed), failed=len(failed),
                      failure_details=failed[:MAX_FAILURE_DETAILS],
                      failure_details_truncated=len(failed) > MAX_FAILURE_DETAILS)
        return report
    except subprocess.TimeoutExpired:
        report["error"] = "candidate_timeout_5s"
    except (OSError, ValueError, TypeError) as exc:
        report["error"] = "candidate_invalid_output"
        report["error_type"] = type(exc).__name__
    return report
