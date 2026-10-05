#!/usr/bin/env python3
"""Score two naive attribution rules on the held-out cases the shipped engine is scored on.

WHY THIS EXISTS. ``scripts/attribution_split.py`` publishes the shipped engine's held-out
figures (50.0% naming precision over 58 namings, 4.8% recall) and compares only Mercury's
own engines with each other. Nothing measured what a responder would get from the rule
Mercury is meant to replace. This script measures two such rules on exactly the same
held-out corpus, seed and commits, and writes ``attribution_baselines_summary.json``.

THE TWO BASELINES. Both see the same anomaly the shipped engine sees: the shipped
detector (3.0x step against the readings before it) runs on each case, and a baseline is
asked to name a change only on the cases where that detector found an onset. So the only
thing that differs between the three rows is the attribution rule. A case the detector
missed is named by nobody.

* Baseline A, ``blame_latest_deploy``: name the newest commit that landed at or before
  the onset, however long before it. No window, no file filter, no crowding gate. Every
  commit is treated as a deploy, as in the corpus.
* Baseline B, ``blame_every_deploy_in_window``: name every commit that landed in the
  shipped engine's window (75 minutes ending at the onset). No file filter, no crowding
  gate. It refuses only when that window is empty.

HOW A NAMING IS COUNTED. A naming is one commit named as the cause. A and the shipped
engine name at most one per case; B can name several, and each innocent one is a wrong
naming. Precision is correct namings over namings. Recall is the share of the 600
regressions where the commit that caused it is among the commits named. A refusal is an
anomaly the rule saw and named nothing for. ``cases_named`` and the share of named cases
whose named set contains the cause are reported beside them, because on that last measure
B is far ahead of the engine and the summary should say so.

WHAT THE NUMBERS ARE WORTH. The corpus is the published one: synthetic and
self-authored, built by ``scripts/correlation_trial.py`` from this repository's real
commits. Nothing here changes the corpus, its labels or the engine. The engine's row is
taken from ``attribution_split.figures`` so it is the published row, and a test holds it
to ``attribution_holdout_summary.json``.

Run::

    python scripts/naive_attribution_baselines.py           # score, write the summary
    python scripts/naive_attribution_baselines.py --check   # re-score and compare, what CI runs
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
for entry in (REPO_ROOT, REPO_ROOT / "scripts"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

import attribution_split as split  # noqa: E402
import correlation_trial as trial  # noqa: E402

from src.domain.incident_correlation import CorrelationVerdict, IncidentCorrelator  # noqa: E402

SUMMARY_PATH = REPO_ROOT / "attribution_baselines_summary.json"
MEASURED_BY_COMMAND = "python scripts/naive_attribution_baselines.py"

MERCURY = "mercury_" + split.SHIPPED_ENGINE
BASELINE_A = "baseline_a_blame_latest_deploy"
BASELINE_B = "baseline_b_blame_every_deploy_in_window"
METHODS = (MERCURY, BASELINE_A, BASELINE_B)

DESCRIPTIONS = {
    MERCURY: (
        "The shipped engine, unchanged: 75 minute window ending at the onset, runtime-path "
        "filter, names a change only when exactly one candidate landed in the window."
    ),
    BASELINE_A: (
        "Name the newest commit that landed at or before the onset, however long before. "
        "No window, no file filter, no crowding gate."
    ),
    BASELINE_B: (
        "Name every commit that landed in the 75 minutes ending at the onset. No file "
        "filter, no crowding gate. Refuses only when that window is empty."
    ),
}

ANOMALY_VERDICTS = (CorrelationVerdict.ANOMALY_ATTRIBUTED, CorrelationVerdict.ANOMALY_WITHOUT_ATTRIBUTION)


# ------------------------------------------------------------------ The rules


def blame_latest_deploy(onset: datetime, commits: list) -> list:
    """Baseline A: the newest commit at or before the onset, any distance back."""
    before = [c for c in commits if c.committed_at <= onset]
    return [max(before, key=lambda c: c.committed_at)] if before else []


def blame_every_deploy_in_window(onset: datetime, commits: list, window_minutes: int) -> list:
    """Baseline B: every commit in the window ending at the onset."""
    start = onset - timedelta(minutes=window_minutes)
    return sorted((c for c in commits if start <= c.committed_at <= onset), key=lambda c: c.committed_at)


def name_per_case(cases: list, commits: list, engine: IncidentCorrelator) -> dict[str, list[dict]]:
    """For each method, one row per case: the case index and the shas it named.

    ``named`` is None when the method was never asked, because the shipped detector saw
    no anomaly on that case, and an empty list when it saw one and named nothing.
    """
    rows: dict[str, list[dict]] = {m: [] for m in METHODS}
    window = engine.attribution_window_minutes
    for case in cases:
        answer = engine.correlate("corpus-service", case.to_series(), commits)
        seen = answer.verdict in ANOMALY_VERDICTS
        if seen and answer.onset_at is None:
            raise RuntimeError(f"case {case.index}: an anomaly with no onset")
        mercury = [answer.offending_commit.sha] if answer.offending_commit else []
        a = [c.sha for c in blame_latest_deploy(answer.onset_at, commits)] if seen else None
        b = [c.sha for c in blame_every_deploy_in_window(answer.onset_at, commits, window)] if seen else None
        for method, named in ((MERCURY, mercury if seen else None), (BASELINE_A, a), (BASELINE_B, b)):
            rows[method].append({"index": case.index, "stratum": case.stratum, "truth": case.truth,
                                 "causing_sha": case.causing_sha, "named": named})
    return rows


# ------------------------------------------------------------------- Scoring


def score(rows: list[dict]) -> dict:
    """The figures reported for one method on one corpus."""
    seen = [r for r in rows if r["named"] is not None]
    named_cases = [r for r in seen if r["named"]]
    regressions = [r for r in rows if r["truth"] == trial.TRUTH_REGRESSION]
    namings = sum(len(r["named"]) for r in named_cases)
    correct = sum(1 for r in named_cases for sha in r["named"] if sha == r["causing_sha"])
    wrong_by_truth = {
        truth: sum(1 for r in named_cases if r["truth"] == truth for sha in r["named"] if sha != r["causing_sha"])
        for truth in (trial.TRUTH_REGRESSION, trial.TRUTH_EXOGENOUS, trial.TRUTH_HEALTHY)
    }
    cause_named = sum(1 for r in regressions if r["named"] and r["causing_sha"] in r["named"])
    contains_cause = sum(1 for r in named_cases if r["causing_sha"] in r["named"])
    refusals = len(seen) - len(named_cases)
    return {
        "anomalies_seen": len(seen),
        "cases_named": len(named_cases),
        "namings_attempted": namings,
        "correct_namings": correct,
        "wrong_namings": namings - correct,
        "wrong_namings_on_regressions": wrong_by_truth[trial.TRUTH_REGRESSION],
        "wrong_namings_on_exogenous_spikes": wrong_by_truth[trial.TRUTH_EXOGENOUS],
        "wrong_namings_on_healthy_series": wrong_by_truth[trial.TRUTH_HEALTHY],
        "cases_with_an_innocent_change_named": sum(
            1 for r in named_cases if any(sha != r["causing_sha"] for sha in r["named"])),
        "naming_precision": round(correct / namings, 4) if namings else None,
        "naming_precision_95ci": split.wilson_interval(correct, namings),
        "naming_recall_on_regressions": round(cause_named / len(regressions), 4) if regressions else None,
        "naming_recall_95ci": split.wilson_interval(cause_named, len(regressions)),
        "regressions": len(regressions),
        "regressions_with_the_cause_named": cause_named,
        "named_cases_whose_named_set_contains_the_cause": contains_cause,
        "named_case_hit_rate": round(contains_cause / len(named_cases), 4) if named_cases else None,
        "mean_commits_named_per_named_case": (
            round(namings / len(named_cases), 2) if named_cases else None),
        "refusals": refusals,
        "refusal_rate_on_anomalies_seen": round(refusals / len(seen), 4) if seen else None,
    }


def versus_mercury(scores: dict[str, dict]) -> dict:
    """Wrong names avoided and right names given up, against each baseline."""
    engine = scores[MERCURY]
    out = {}
    for baseline in (BASELINE_A, BASELINE_B):
        other = scores[baseline]
        out[baseline] = {
            "wrong_namings_avoided": other["wrong_namings"] - engine["wrong_namings"],
            "correct_namings_given_up": other["correct_namings"] - engine["correct_namings"],
            "regressions_with_the_cause_named_given_up": (
                other["regressions_with_the_cause_named"] - engine["regressions_with_the_cause_named"]),
            "wrong_namings_on_exogenous_spikes_avoided": (
                other["wrong_namings_on_exogenous_spikes"] - engine["wrong_namings_on_exogenous_spikes"]),
        }
    return out


def case_digest(cases: list) -> str:
    """A fingerprint of the corpus: every case's index, stratum, truth, cause and reading time."""
    text = "\n".join(
        f"{c.index}|{c.stratum}|{c.truth}|{c.causing_sha}|{c.observed_at.isoformat()}" for c in cases)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def side_block(cases: list, commits: list) -> dict:
    engine = split.ENGINES[split.SHIPPED_ENGINE]["build"]()
    rows = name_per_case(cases, commits, engine)
    scores = {m: score(rows[m]) for m in METHODS}
    published = split.figures(cases, commits, split.ENGINES[split.SHIPPED_ENGINE]["build"]())
    return {
        "cases": len(cases),
        "case_digest_sha256": case_digest(cases),
        "anomaly_case_indices_digest_sha256": hashlib.sha256(",".join(
            str(r["index"]) for r in rows[MERCURY] if r["named"] is not None).encode("utf-8")).hexdigest(),
        "methods": scores,
        "versus_mercury": versus_mercury(scores),
        "mercury_published_row_agrees": (
            published["times_a_commit_was_named"] == scores[MERCURY]["namings_attempted"]
            and published["correct_namings"] == scores[MERCURY]["correct_namings"]
            and published["wrong_namings"] == scores[MERCURY]["wrong_namings"]
            and published["naming_precision"] == scores[MERCURY]["naming_precision"]
            and published["naming_recall_on_regressions"] == scores[MERCURY]["naming_recall_on_regressions"]
        ),
    }


#: The fields kept for each method in the delay-ceiling and seed-spread rows.
ROW_FIELDS = ("namings_attempted", "correct_namings", "wrong_namings", "naming_precision",
              "naming_recall_on_regressions", "refusals")


def delay_ceiling_rows(commits: list) -> dict:
    """The same three rules on the held-out corpora of attribution_split's delay-ceiling table."""
    floor = trial.PROPAGATION_DELAY_MINUTES[0]
    rows = []
    for ceiling in split.DELAY_CEILINGS_MINUTES:
        cases, held_out = split.held_out_corpus(commits, propagation_delay_minutes=(floor, float(ceiling)))
        engine = split.ENGINES[split.SHIPPED_ENGINE]["build"]()
        named = name_per_case(cases, held_out, engine)
        for method in METHODS:
            s = score(named[method])
            rows.append({"delay_ceiling_minutes": ceiling, "method": method,
                         **{k: s[k] for k in ROW_FIELDS}})
    return {
        "side": "held_out",
        "seed": split.HELD_OUT_SEED,
        "published_delay_minutes": list(trial.PROPAGATION_DELAY_MINUTES),
        "note": (
            "The held-out corpora of attribution_split.py's delay_ceiling_sensitivity block: "
            "same seed and commits, only the generator's delay ceiling moves. Baseline B keeps "
            "the shipped 75 minute window at every ceiling. Nothing was chosen from these rows."
        ),
        "rows": rows,
    }


def seed_spread(commits: list) -> dict:
    """The same three rules on attribution_split's 20 other held-out seeds."""
    per_method: dict[str, list[dict]] = {m: [] for m in METHODS}
    for seed in split.SPREAD_SEEDS:
        cases, held_out = split.held_out_corpus(commits, seed=seed)
        engine = split.ENGINES[split.SHIPPED_ENGINE]["build"]()
        named = name_per_case(cases, held_out, engine)
        for method in METHODS:
            s = score(named[method])
            per_method[method].append({"seed": seed, **{k: s[k] for k in ROW_FIELDS}})
    methods = {}
    for method, rows in per_method.items():
        methods[method] = {
            "mean_wrong_namings": round(statistics.mean(r["wrong_namings"] for r in rows), 2),
            "min_wrong_namings": min(r["wrong_namings"] for r in rows),
            "max_wrong_namings": max(r["wrong_namings"] for r in rows),
            "mean_correct_namings": round(statistics.mean(r["correct_namings"] for r in rows), 2),
            "mean_naming_precision": round(statistics.mean(
                r["naming_precision"] for r in rows if r["naming_precision"] is not None), 4),
            "rows": rows,
        }
    fewer_wrong = {
        baseline: sum(1 for m, b in zip(per_method[MERCURY], per_method[baseline])
                      if m["wrong_namings"] < b["wrong_namings"])
        for baseline in (BASELINE_A, BASELINE_B)
    }
    return {
        "seeds": [split.SPREAD_SEEDS[0], split.SPREAD_SEEDS[-1]],
        "note": "Held-out commits, attribution_split.py's 20 other seeds, the published delay ceiling.",
        "mercury_fewer_wrong_namings_than_baseline_on_seeds": fewer_wrong,
        "methods": methods,
    }


def build_summary() -> dict:
    commits, _ = trial.load_commit_stream()
    train_cases, train = split.train_corpus(commits)
    held_cases, held_out = split.held_out_corpus(commits)
    return {
        "measured_by_command": MEASURED_BY_COMMAND,
        "measured_at_utc": datetime.now(timezone.utc).isoformat(),
        "measured_on": platform.platform(),
        "python_version": platform.python_version(),
        "label": split.SYNTHETIC_LABEL,
        "corpus": (
            "The corpus scripts/attribution_split.py publishes: the same chronological split, "
            "the same generator, the same seeds and commits. Not changed by this script."
        ),
        "detector": (
            "Every method sees the anomalies the shipped detector sees (3.0x step against the "
            "readings before it), and a baseline is asked to name a change only where that "
            "detector found an onset. Only the attribution rule differs between methods."
        ),
        "counting": (
            "A naming is one commit named as the cause. Precision is correct namings over "
            "namings. Recall is the share of regressions whose causing commit is among those "
            "named. A refusal is an anomaly seen with nothing named."
        ),
        "shipped_engine": split.SHIPPED_ENGINE,
        "held_out_seed": split.HELD_OUT_SEED,
        "train_seed": split.TRAIN_SEED,
        "methods": [{"method": m, "description": DESCRIPTIONS[m]} for m in METHODS],
        "held_out": side_block(held_cases, held_out),
        "train": side_block(train_cases, train),
        "delay_ceiling_rows": delay_ceiling_rows(commits),
        "held_out_seed_spread": seed_spread(commits),
    }


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def print_report(summary: dict) -> None:
    print(f"Naive attribution baselines on the held-out split (seed {summary['held_out_seed']}). "
          f"{summary['label']}")
    for side in ("held_out", "train"):
        block = summary[side]
        print(f"  {side}: {block['cases']} cases")
        for method, s in block["methods"].items():
            print(f"    {method:<42} named {s['namings_attempted']:>4} ({s['cases_named']} cases)  "
                  f"correct {s['correct_namings']:>3}  wrong {s['wrong_namings']:>4}  "
                  f"precision {_pct(s['naming_precision'])}  recall {_pct(s['naming_recall_on_regressions'])}  "
                  f"refused {s['refusals']} of {s['anomalies_seen']}")
        for baseline, v in block["versus_mercury"].items():
            print(f"    against {baseline}: {v['wrong_namings_avoided']} wrong namings avoided, "
                  f"{v['correct_namings_given_up']} correct namings given up")
    print("  held-out by delay ceiling:")
    for r in summary["delay_ceiling_rows"]["rows"]:
        print(f"    ceiling {r['delay_ceiling_minutes']:>3}  {r['method']:<42} precision "
              f"{_pct(r['naming_precision'])} ({r['correct_namings']} of {r['namings_attempted']})  "
              f"wrong {r['wrong_namings']}  recall {_pct(r['naming_recall_on_regressions'])}")
    spread = summary["held_out_seed_spread"]
    print(f"  held-out seeds {spread['seeds'][0]} to {spread['seeds'][1]}:")
    for method, m in spread["methods"].items():
        print(f"    {method:<42} wrong namings mean {m['mean_wrong_namings']} "
              f"(range {m['min_wrong_namings']} to {m['max_wrong_namings']})  "
              f"correct mean {m['mean_correct_namings']}  precision mean {_pct(m['mean_naming_precision'])}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="re-score and compare against the recorded summary without writing it")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    summary = build_summary()
    if not (summary["held_out"]["mercury_published_row_agrees"] and summary["train"]["mercury_published_row_agrees"]):
        print("the engine row here disagrees with attribution_split.figures; nothing written")
        return 1
    if args.check:
        if not SUMMARY_PATH.exists():
            print(f"{SUMMARY_PATH.name} does not exist; run {MEASURED_BY_COMMAND} first")
            return 1
        recorded = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
        drifted = split.drifted_keys(recorded, summary)
        if drifted:
            print("the recorded baseline summary no longer matches a fresh run: " + ", ".join(drifted))
            return 1
        print(f"{SUMMARY_PATH.name} matches a fresh run in every field but the run metadata "
              f"({len(METHODS)} methods, {len(summary['delay_ceiling_rows']['rows'])} delay-ceiling rows, "
              f"{len(split.SPREAD_SEEDS)} spread seeds)")
        return 0

    if not args.no_write:
        SUMMARY_PATH.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print_report(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
