#!/usr/bin/env python3
"""Time the test suite the way the README says it is timed, and record the result.

The README's Quickstart carries the first number a reader ever checks: how long
``python -m pytest tests/ -q`` takes. It was prose. Three readers re-timed it on this
machine and every one of them landed 35 to 90 percent above the published ceiling,
which made it the one claim in this repository that did not reproduce. A number nobody
re-measures is a number that drifts the moment a test is added, and this suite grew by
several hundred tests after that figure was typed.

So the figure is measured by this script, recorded in ``suite_timing_summary.json``,
and compared against the README by ``tests/e2e/test_documentation_claims.py``. That is
the same arrangement ``benchmarks_summary.json`` and ``coverage_summary.json`` already
use, and for the same reason: measuring inside a test would mean running the suite
from inside the suite.

**A test-suite runtime is not a constant, and publishing it as one is what failed.**
So this script measures under two conditions it can name rather than under one it
cannot. The quiet runs are what a reader gets on an idle machine. The loaded run is
the same suite with ``--load`` background processes competing for CPU, started and
killed by this script, and it exists so the published range has a high end that was
measured rather than hoped for. The README publishes the whole span.

**A runtime measured over a red suite is not a runtime**, so this script refuses to
write one. That makes re-measuring a two-pass job whenever the suite changes size,
because the README no longer matches the record and the suite is red until it does:

    python scripts/time_test_suite.py --bootstrap   # 1. red suite allowed, marked
    # paste the range into the README, which turns the suite green again
    python scripts/time_test_suite.py               # 2. the record that gets published
    # paste that range into the README

The second pass is the one whose numbers ship. A bootstrap record says so in its own
``bootstrap`` field, so a reader can tell which one they are holding.

Usage:
    python scripts/time_test_suite.py               # 3 quiet runs, 1 loaded run, write
    python scripts/time_test_suite.py --runs 5      # 5 quiet runs
    python scripts/time_test_suite.py --load 0      # quiet runs only
    python scripts/time_test_suite.py --bootstrap   # allow a red suite, mark the record
    python scripts/time_test_suite.py --check       # measure and compare only
"""
from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SUMMARY_PATH = REPO_ROOT / "suite_timing_summary.json"

#: The command whose wall clock is published. Timed from immediately before the
#: subprocess starts to immediately after it exits, which is what a reader with a
#: stopwatch measures. Interpreter startup and collection are inside it.
COMMAND = ["-m", "pytest", "tests/", "-q"]

#: A busy loop with no allocation and no I/O, so a background worker competes for the
#: CPU and nothing else. Killed by the parent as soon as the timed run returns.
BUSY_LOOP = "x=0\nwhile True:\n    x=(x+1)%1000003\n"

DEFAULT_QUIET_RUNS = 3
DEFAULT_LOAD_WORKERS = 4


def machine_name() -> str:
    """The measurement machine, named so a reader can attribute a difference to hardware.

    ``platform.release()`` answers "10" on Windows 11, because the version API it reads
    kept the 10.0 major for compatibility. The build number is the honest discriminator:
    22000 and above is Windows 11. The raw ``platform.platform()`` string is kept in
    brackets so nothing here hides what the interpreter actually reported.
    """
    friendly = f"{platform.system()} {platform.release()}".strip()
    if platform.system() == "Windows":
        build = re.match(r"10\.0\.(\d+)", platform.version() or "")
        if build and int(build.group(1)) >= 22000:
            friendly = "Windows 11"
    return f"{friendly} ({platform.platform()}), CPython {platform.python_version()}"


def run_once(condition: str, workers: int, allow_red: bool = False) -> dict[str, object]:
    """One timed run of the published command, optionally against background load."""
    load: list[subprocess.Popen] = []
    for _ in range(workers):
        load.append(subprocess.Popen(
            [sys.executable, "-c", BUSY_LOOP],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        ))
    try:
        if load:
            time.sleep(1.0)  # let the workers reach the loop before the clock starts
        started = time.perf_counter()
        result = subprocess.run(
            [sys.executable, *COMMAND],
            capture_output=True, text=True, cwd=str(REPO_ROOT),
        )
        elapsed = time.perf_counter() - started
    finally:
        for worker in load:
            worker.kill()
        for worker in load:
            worker.wait()

    passed = re.search(r"(\d+) passed", result.stdout)
    skipped = re.search(r"(\d+) skipped", result.stdout)
    failed = re.search(r"(\d+) failed", result.stdout)
    if (result.returncode != 0 or failed) and not allow_red:
        sys.stderr.write(result.stdout[-4000:])
        raise SystemExit(
            f"the suite was not green on this run (exit {result.returncode}); "
            f"a runtime measured over a red suite is not a runtime. Use --bootstrap "
            f"only to break the deadlock where the suite is red because this record "
            f"is missing or stale, then re-run without it"
        )
    if not passed:
        sys.stderr.write(result.stdout[-4000:])
        raise SystemExit("pytest printed no passed count; nothing was measured")

    return {
        "condition": condition,
        "background_cpu_workers": workers,
        "seconds": round(elapsed, 2),
        "tests_passed": int(passed.group(1)),
        "tests_skipped": int(skipped.group(1)) if skipped else 0,
        "tests_failed": int(failed.group(1)) if failed else 0,
        "exit_code": result.returncode,
    }


def collected_count() -> int:
    """How many tests the suite holds, counted outside the timed window.

    The published range belongs to a particular suite. Recording the collected count
    beside it is what lets a test notice that the suite has grown since, which is the
    precise way the previous figure went stale.
    """
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-q", "--collect-only"],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    match = re.search(r"(\d+) tests? collected", result.stdout)
    if not match:
        sys.stderr.write(result.stdout[-4000:])
        raise SystemExit("pytest collected nothing; there is no suite to time")
    return int(match.group(1))


def previous_summary() -> dict[str, object] | None:
    """The headline of the record this run is about to replace.

    Kept so the file can show how its own numbers moved between measurement sessions
    instead of quietly re-rolling them. A figure that is replaced without a trace is
    indistinguishable from a figure that was chosen.
    """
    if not SUMMARY_PATH.exists():
        return None
    try:
        old = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return {
        field: old.get(field) for field in (
            "measured_at_utc", "bootstrap", "tests_collected",
            "quiet_min_seconds", "quiet_max_seconds",
            "loaded_min_seconds", "loaded_max_seconds",
        )
    }


def measure(quiet_runs: int, load_workers: int, allow_red: bool = False) -> dict[str, object]:
    collected = collected_count()
    previous = previous_summary()
    runs: list[dict[str, object]] = []
    for _ in range(quiet_runs):
        runs.append(run_once("quiet", 0, allow_red))
    if load_workers:
        runs.append(run_once("loaded", load_workers, allow_red))

    counts = {run["tests_passed"] for run in runs}
    if len(counts) != 1:
        raise SystemExit(f"the runs disagree on how many tests passed: {sorted(counts)}")

    quiet = [run["seconds"] for run in runs if run["condition"] == "quiet"]
    loaded = [run["seconds"] for run in runs if run["condition"] == "loaded"]
    everything = [run["seconds"] for run in runs]

    return {
        "schema": "mercury.suite_timing/1",
        "note": (
            "Wall clock around the pytest subprocess, from immediately before it starts "
            "to immediately after it exits, which is what a reader with a stopwatch "
            "measures. Quiet runs are on an otherwise idle machine. The loaded run is "
            "the same command with background CPU workers started and killed by the "
            "measuring script, so the published high end was measured rather than "
            "guessed. This figure moves with machine load and with the size of the "
            "suite; re-run this script after changing either."
        ),
        "measured_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "measured_by_command": "python scripts/time_test_suite.py",
        "equivalent_command": "python -m pytest tests/ -q",
        "machine": machine_name(),
        "python_version": platform.python_version(),
        "cpu_count": os.cpu_count(),
        "bootstrap": any(run["exit_code"] != 0 for run in runs),
        "tests_collected": collected,
        "tests_passed": runs[0]["tests_passed"],
        "tests_skipped": runs[0]["tests_skipped"],
        "runs": runs,
        "quiet_min_seconds": min(quiet) if quiet else None,
        "quiet_max_seconds": max(quiet) if quiet else None,
        "loaded_min_seconds": min(loaded) if loaded else None,
        "loaded_max_seconds": max(loaded) if loaded else None,
        "min_seconds": min(everything),
        "max_seconds": max(everything),
        "previous_measurement": previous,
    }


def _int_arg(flag: str, default: int) -> int:
    if flag in sys.argv:
        return int(sys.argv[sys.argv.index(flag) + 1])
    return default


def main() -> int:
    checking = "--check" in sys.argv
    measured = measure(
        _int_arg("--runs", DEFAULT_QUIET_RUNS),
        _int_arg("--load", DEFAULT_LOAD_WORKERS),
        allow_red="--bootstrap" in sys.argv,
    )
    if measured["bootstrap"]:
        print("  WARNING: measured over a red suite. This record is marked bootstrap "
              "and must be replaced by a run over a green one before it is published.")

    for run in measured["runs"]:
        print(f"  {run['condition']:<7} {run['seconds']:>7.2f} s "
              f"({run['background_cpu_workers']} background workers, "
              f"{run['tests_passed']} passed)")

    if checking:
        if not SUMMARY_PATH.exists():
            print("suite_timing_summary.json is missing; run this script without --check")
            return 1
        recorded = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
        if recorded.get("tests_collected") != measured["tests_collected"]:
            print(f"the suite has changed size: recorded {recorded.get('tests_collected')} tests, "
                  f"collected {measured['tests_collected']}. Re-run without --check")
            return 1
        low, high = recorded.get("min_seconds"), recorded.get("max_seconds")
        outside = [r["seconds"] for r in measured["runs"] if not low <= r["seconds"] <= high]
        if outside:
            print(f"runs outside the recorded {low} to {high} s range: {outside}")
            return 1
        print(f"every run fell inside the recorded {low} to {high} s range")
        return 0

    SUMMARY_PATH.write_text(json.dumps(measured, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {SUMMARY_PATH.name}: {measured['min_seconds']} to {measured['max_seconds']} s "
          f"over {len(measured['runs'])} runs of {measured['tests_collected']} tests "
          f"on {measured['machine']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
