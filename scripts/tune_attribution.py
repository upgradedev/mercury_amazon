#!/usr/bin/env python3
"""Choose the attribution engine's parameters on the TRAIN split, and only there.

Every setting below is scored on train corpora built from the 42 commits before the cut in
``scripts/attribution_split.py``. This script never builds, loads or scores the held-out
corpus. It imports ``scripts/attribution_train.py``, which defines the train side and not
the held-out builder or seed, and never imports ``attribution_split``;
``tests/unit/test_attribution_split.py`` imports this script in a fresh interpreter and
fails if ``attribution_split`` or anything defining the held-out builder is loaded. That
is an import-level boundary inside one repository, not a sandbox: nothing stops a future
edit from adding the import, except that test.

THE RULE, STATED IN THIS SCRIPT, WHICH PRODUCED THE CHOICE. The rule, the sweep and its
summary were committed together (5987fbe), so history cannot show the rule came first.
The chosen setting (75 minutes, gate 1, no scope) also has the highest pooled train
precision of all 36 settings, so a precision-first rule would have picked it too. Among the settings whose pooled train naming
precision is at least the shipped engine's and whose pooled train false-attribution rate on
exogenous spikes is no higher than the shipped engine's, pick the one with the highest pooled
train naming recall. Ties go to the narrower window, then the smaller gate, then no scope.
Precision is a floor rather than the objective because the product's rule is refusal first:
a setting that names more by being wrong more is not an improvement.

THE GRID.

* ``window``: attribution window in minutes, ending at the onset.
* ``gate``: name a change only when at most this many candidates are in the window.
* ``scope``: whether a commit whose recorded file list touches nothing the service is built
  from (``src/domain/change_scope.py``) is counted as a candidate.

What is not tuned, and why. The 3.0x anomaly threshold is left alone: it trades detection
against quiet on healthy series, which is a different question from attribution. Closeness
to the onset is not used as a ranking signal: the generator draws the propagation delay
uniformly from 1 to 75 minutes, so any gain from it would be fitted to that assumption.
The window is exposed to the same fit and was not protected from it: the chosen 75 minutes
equals that ceiling, and both sides of the split share the generator. The held-out figure
is therefore conditional on regressions showing within 75 minutes;
``scripts/attribution_split.py`` publishes how it moves at other ceilings.

The train figures come from three train seeds pooled, so one lucky draw cannot pick the
setting. The corpus is synthetic and self-authored; see ``scripts/correlation_trial.py``.

THE SCOPE FIGHTS THE LABELS, AND THAT IS MEASURED RATHER THAN FIXED. The generator draws a
regression's cause uniformly from every commit, including the 22 of 59 that changed only
tests, prose, CI or the Fire TV client. Under those labels a README edit is as likely to
raise the server's error rate as a change to ``src/``, so the scope is penalised whenever
the labelled cause is one of those. The labels are not changed. Instead, and on the train
side only, ``leak_sweep`` rebuilds the regression strata with the cause drawn from commits
inside the scope except for a share ``leak`` of cases that keep the original draw, and scores
the chosen window and gate with and without the scope. That variant encodes the authors'
assumption that a change outside the service rarely breaks it, so it is published as what
the scope would be worth under that assumption, never as a measured gain, and it played no
part in the choice above.

Run::

    python scripts/tune_attribution.py              # sweep, print, write the summary
    python scripts/tune_attribution.py --no-write   # sweep and print only
    python scripts/tune_attribution.py --check      # re-run and compare, what CI runs

``--check`` compares every field of ``attribution_tuning_summary.json`` except
``measured_at_utc``, so the record a test pins the shipped engine to is re-derived in CI.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
for entry in (REPO_ROOT, REPO_ROOT / "scripts"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

import correlation_trial as trial  # noqa: E402
from attribution_train import SYNTHETIC_LABEL, train_corpus  # noqa: E402

from src.domain.change_scope import MERCURY_SERVICE_SCOPE  # noqa: E402
from src.domain.incident_correlation import IncidentCorrelator  # noqa: E402

SUMMARY_PATH = REPO_ROOT / "attribution_tuning_summary.json"
TRAIN_SEEDS = (trial.DEFAULT_SEED, 20260909, 20260910)
WINDOWS = (45, 60, 75, 90, 120, 150)
GATES = (1, 2, 3)
SCOPES = (False, True)
SHIPPED = {"window": 60, "gate": 1, "scope": False}


def score(window: int, gate: int, scope: bool, corpora) -> dict:
    hits = named = regressions = false_exo = exogenous = refused = 0
    for cases, commits in corpora:
        correlator = IncidentCorrelator(
            attribution_window_minutes=window, max_commits_in_window=gate,
            service_scope=MERCURY_SERVICE_SCOPE if scope else None,
        )
        verdicts = trial.run_corpus(cases, commits, correlator)
        hits += sum(1 for v in verdicts if v.outcome == trial.HIT)
        named += sum(1 for v in verdicts if v.outcome in trial.NAMED_A_COMMIT)
        regressions += sum(1 for v in verdicts if v.truth == trial.TRUTH_REGRESSION)
        refused += sum(1 for v in verdicts if v.outcome in trial.REFUSED_TO_NAME)
        exogenous += sum(1 for v in verdicts if v.stratum == trial.STRATUM_EXOGENOUS)
        false_exo += sum(1 for v in verdicts
                         if v.stratum == trial.STRATUM_EXOGENOUS and v.outcome == trial.FALSE_ATTRIBUTION)
    return {
        "window": window, "gate": gate, "scope": scope,
        "precision": round(hits / named, 4) if named else None,
        "recall": round(hits / regressions, 4),
        "refusal_rate": round(refused / (refused + named), 4) if refused + named else None,
        "false_attribution_exogenous": round(false_exo / exogenous, 4),
        "namings": named, "hits": hits,
    }


def choose(rows: list[dict], shipped: dict) -> dict:
    eligible = [
        row for row in rows
        if row["precision"] is not None
        and row["precision"] >= shipped["precision"]
        and row["false_attribution_exogenous"] <= shipped["false_attribution_exogenous"]
    ]
    return max(eligible, key=lambda r: (r["recall"], -r["window"], -r["gate"], not r["scope"]))


LEAKS = (0.0, 0.1, 0.25, 0.5)


def scoped_variant(corpus, commits: list, seed: int, leak: float) -> list:
    """Train cases with regression causes drawn inside the scope, except a ``leak`` share.

    Uncaused strata are kept exactly as generated. Only the two regression strata are
    rebuilt, from the same generator, handed the in-scope commits instead of all of them.
    """
    in_scope = [c for c in commits if MERCURY_SERVICE_SCOPE.touches(c.paths) is not False]
    cases, _ = corpus
    rebuilt = []
    for stratum in (trial.STRATUM_FRESH, trial.STRATUM_LATE):
        original = [c for c in cases if c.stratum == stratum]
        scoped = trial._regression_cases(
            len(original), in_scope, seed, stratum, trial.DEFAULT_NOISE_SIGMA, original[0].index)
        keep = round(leak * len(original))
        rebuilt += original[:keep] + scoped[keep:]
    return rebuilt + [c for c in cases if c.truth != trial.TRUTH_REGRESSION]


def leak_sweep(chosen: dict, commits: list, corpora_seeds) -> list[dict]:
    rows = []
    for leak in LEAKS:
        variant = [(scoped_variant(corpus, corpus[1], seed, leak), corpus[1])
                   for corpus, seed in corpora_seeds]
        for scope in SCOPES:
            row = score(chosen["window"], chosen["gate"], scope, variant)
            row["leak"] = leak
            rows.append(row)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="re-run the sweep and compare against the recorded summary without writing it")
    parser.add_argument("--no-write", action="store_true", help="print the sweep without writing the summary")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    commits, _ = trial.load_commit_stream()
    corpora = [train_corpus(commits, seed=seed) for seed in TRAIN_SEEDS]
    rows = [score(w, g, s, corpora) for w in WINDOWS for g in GATES for s in SCOPES]
    shipped = next(r for r in rows if (r["window"], r["gate"], r["scope"]) ==
                   (SHIPPED["window"], SHIPPED["gate"], SHIPPED["scope"]))
    chosen = choose(rows, shipped)
    print(f"Train split only, seeds {TRAIN_SEEDS} pooled. {SYNTHETIC_LABEL}")
    print(f"{'window':>6} {'gate':>4} {'scope':>5} {'precision':>9} {'recall':>7} "
          f"{'refusal':>7} {'false_exo':>9} {'namings':>7}")
    for r in rows:
        mark = "  <- chosen" if r is chosen else ("  <- shipped before" if r is shipped else "")
        print(f"{r['window']:>6} {r['gate']:>4} {str(r['scope']):>5} {r['precision']!s:>9} "
              f"{r['recall']:>7} {r['refusal_rate']!s:>7} {r['false_attribution_exogenous']:>9} "
              f"{r['namings']:>7}{mark}")
    sweep_rows = leak_sweep(chosen, commits, list(zip(corpora, TRAIN_SEEDS)))
    print(f"Assumption variant (train only): causes drawn inside the scope except a leak share, "
          f"window {chosen['window']}, gate {chosen['gate']}")
    for r in sweep_rows:
        print(f"  leak {r['leak']:<4} scope {str(r['scope']):<5} precision {r['precision']} "
              f"recall {r['recall']} refusal {r['refusal_rate']} false_exo "
              f"{r['false_attribution_exogenous']} namings {r['namings']}")
    summary = {
        "measured_by_command": "python scripts/tune_attribution.py",
        "measured_at_utc": datetime.now(timezone.utc).isoformat(),
        "label": SYNTHETIC_LABEL,
        "split": "train only (commits before the cut in scripts/attribution_split.py)",
        "train_seeds": list(TRAIN_SEEDS),
        "rule": (
            "Highest pooled train recall among settings whose pooled train precision is at "
            "least the shipped engine's and whose false-attribution rate on exogenous spikes "
            "is no higher; ties to the narrower window, smaller gate, no scope."
        ),
        "shipped_before": shipped,
        "chosen": chosen,
        "sweep": rows,
        "scope_under_the_assumption_variant": {
            "note": (
                "Train side only. Regression causes drawn from commits inside the service "
                "scope except a 'leak' share that keeps the original draw. Encodes the "
                "authors' assumption; not a measured gain and not used for the choice."
            ),
            "rows": sweep_rows,
        },
    }
    if args.check:
        if not SUMMARY_PATH.exists():
            print(f"{SUMMARY_PATH.name} does not exist; run python scripts/tune_attribution.py first")
            return 1
        recorded = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
        # A JSON round trip so tuples and lists compare the way the file stores them.
        fresh = json.loads(json.dumps(summary))
        drifted = sorted(key for key in set(recorded) | set(fresh)
                         if key != "measured_at_utc" and recorded.get(key) != fresh.get(key))
        if drifted:
            print("the recorded tuning summary no longer matches a fresh sweep: " + ", ".join(drifted))
            return 1
        print(f"{SUMMARY_PATH.name} matches a fresh sweep in every field but measured_at_utc "
              f"({len(rows)} settings, chosen {chosen['window']}/{chosen['gate']}/{chosen['scope']})")
        return 0
    if not args.no_write:
        SUMMARY_PATH.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
