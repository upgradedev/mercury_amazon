"""The naive baselines have to be scored on the engine's own held-out cases.

These tests hold ``scripts/naive_attribution_baselines.py`` to what its comparison rests
on: the recorded summary is what the committed rules produce, every rule is asked about
exactly the cases the shipped engine is scored on, the engine's row is the published one,
and the two rules do what their names say.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
for entry in (REPO_ROOT, REPO_ROOT / "scripts"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

import attribution_split as split  # noqa: E402
import correlation_trial as trial  # noqa: E402
import naive_attribution_baselines as baselines  # noqa: E402

from src.domain.incident_correlation import CommitRef  # noqa: E402

SUMMARY = json.loads((REPO_ROOT / "attribution_baselines_summary.json").read_text(encoding="utf-8"))
HOLDOUT = json.loads((REPO_ROOT / "attribution_holdout_summary.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def held_out():
    commits, _ = trial.load_commit_stream()
    return split.held_out_corpus(commits)


def test_the_recorded_baseline_summary_matches_a_fresh_run():
    result = subprocess.run(
        [sys.executable, "scripts/naive_attribution_baselines.py", "--check"],
        capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=600,
    )
    assert result.returncode == 0, result.stdout[-1500:]


def test_every_rule_is_scored_on_the_engines_held_out_case_ids(held_out):
    cases, commits = held_out
    rows = baselines.name_per_case(cases, commits, split.ENGINES[split.SHIPPED_ENGINE]["build"]())
    expected = [c.index for c in cases]
    for method in baselines.METHODS:
        assert [r["index"] for r in rows[method]] == expected
    # The same anomalies are put to every rule: the cases the shipped engine saw one on.
    verdicts = trial.run_corpus(cases, commits, split.ENGINES[split.SHIPPED_ENGINE]["build"]())
    seen_by_engine = [v.index for v in verdicts
                      if v.outcome in trial.NAMED_A_COMMIT + trial.REFUSED_TO_NAME
                      or v.outcome == trial.FALSE_ANOMALY]
    for method in baselines.METHODS:
        assert [r["index"] for r in rows[method] if r["named"] is not None] == seen_by_engine
    # And the corpus the summary was recorded on is this one.
    assert SUMMARY["held_out"]["case_digest_sha256"] == baselines.case_digest(cases)
    assert SUMMARY["held_out_seed"] == split.HELD_OUT_SEED == HOLDOUT["split"]["held_out_seed"]


def test_the_engine_row_is_the_published_held_out_row_and_it_has_not_moved():
    published = next(e for e in HOLDOUT["engines"] if e["engine"] == HOLDOUT["shipped_engine"])["held_out"]
    engine = SUMMARY["held_out"]["methods"][baselines.MERCURY]
    assert HOLDOUT["shipped_engine"] == SUMMARY["shipped_engine"] == split.SHIPPED_ENGINE
    assert engine["namings_attempted"] == published["times_a_commit_was_named"]
    assert engine["correct_namings"] == published["correct_namings"]
    assert engine["wrong_namings"] == published["wrong_namings"]
    assert engine["naming_precision"] == published["naming_precision"]
    assert engine["naming_precision_95ci"] == published["naming_precision_95ci"]
    assert engine["naming_recall_on_regressions"] == published["naming_recall_on_regressions"]
    assert engine["anomalies_seen"] == published["anomalies_seen"]
    assert engine["refusals"] == published["refused_no_candidate"] + published["refused_window_too_crowded"]
    # The figure the board prints. This comparison must not move it.
    assert (published["naming_precision"], published["correct_namings"],
            published["times_a_commit_was_named"]) == (0.5, 29, 58)
    for side in ("held_out", "train"):
        assert SUMMARY[side]["mercury_published_row_agrees"] is True


def test_the_two_rules_do_what_their_names_say():
    onset = datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)

    def commit(sha: str, minutes_before: float) -> CommitRef:
        return CommitRef(sha=sha, message=sha, author="a", committed_at=onset - timedelta(minutes=minutes_before))

    stream = [commit("old", 300), commit("edge", 75), commit("near", 10), commit("at", 0), commit("after", -5)]
    assert [c.sha for c in baselines.blame_latest_deploy(onset, stream)] == ["at"]
    assert [c.sha for c in baselines.blame_latest_deploy(onset, stream[:1])] == ["old"]
    assert baselines.blame_latest_deploy(onset, stream[-1:]) == []
    assert [c.sha for c in baselines.blame_every_deploy_in_window(onset, stream, 75)] == ["edge", "near", "at"]
    assert baselines.blame_every_deploy_in_window(onset, stream[:1], 75) == []


def test_wrong_names_avoided_are_the_difference_of_the_recorded_rows():
    rows = SUMMARY["held_out"]["methods"]
    engine = rows[baselines.MERCURY]
    for baseline in (baselines.BASELINE_A, baselines.BASELINE_B):
        versus = SUMMARY["held_out"]["versus_mercury"][baseline]
        assert versus["wrong_namings_avoided"] == rows[baseline]["wrong_namings"] - engine["wrong_namings"]
        assert versus["correct_namings_given_up"] == rows[baseline]["correct_namings"] - engine["correct_namings"]
        for r in (rows[baseline], engine):
            assert r["correct_namings"] + r["wrong_namings"] == r["namings_attempted"]
            assert r["refusals"] + r["cases_named"] == r["anomalies_seen"]


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _ci(row: dict) -> str:
    low, high = row["naming_precision_95ci"]
    return f"95% CI {_pct(low)} to {_pct(high)}"


def test_the_documents_quote_the_recorded_baseline_figures():
    evidence = " ".join((REPO_ROOT / "docs" / "EVIDENCE.md").read_text(encoding="utf-8").split())
    readme = " ".join((REPO_ROOT / "README.md").read_text(encoding="utf-8").split())
    rows = SUMMARY["held_out"]["methods"]
    m, a, b = (rows[k] for k in baselines.METHODS)
    assert (f"| Wrong namings (an innocent change named) | **{m['wrong_namings']}** | "
            f"{a['wrong_namings']} | {b['wrong_namings']} |") in evidence
    assert (f"| Naming precision | **{_pct(m['naming_precision'])}** ({_ci(m)}) | "
            f"{_pct(a['naming_precision'])} ({_ci(a)}) | {_pct(b['naming_precision'])} ({_ci(b)}) |") in evidence
    assert (f"| Naming recall on regressions | {_pct(m['naming_recall_on_regressions'])} "
            f"({m['regressions_with_the_cause_named']} of 600) | {_pct(a['naming_recall_on_regressions'])} "
            f"({a['regressions_with_the_cause_named']} of 600) | **{_pct(b['naming_recall_on_regressions'])}** "
            f"({b['regressions_with_the_cause_named']} of 600) |") in evidence
    assert f"| Refusals | {m['refusals']} | {a['refusals']} | {b['refusals']} |" in evidence
    for baseline, avoided in SUMMARY["held_out"]["versus_mercury"].items():
        assert f"{avoided['wrong_namings_avoided']} fewer" in evidence
        assert f"gives up {avoided['correct_namings_given_up']}" in evidence
    rows_by = {(r["delay_ceiling_minutes"], r["method"]): r for r in SUMMARY["delay_ceiling_rows"]["rows"]}
    for ceiling in split.DELAY_CEILINGS_MINUTES:
        cells = [f"{_pct(r['naming_precision'])} ({r['correct_namings']} of {r['namings_attempted']}), "
                 f"{r['wrong_namings']}" for r in (rows_by[(ceiling, k)] for k in baselines.METHODS)]
        if ceiling == 75:
            line = f"| **75 (published)** | **{cells[0]}** | **{cells[1]}** | **{cells[2]}** |"
        else:
            line = f"| {ceiling} | {cells[0]} | {cells[1]} | {cells[2]} |"
        assert line in evidence, f"the EVIDENCE baseline row for a {ceiling} minute ceiling drifted"
    assert (f"{m['wrong_namings']} wrong namings for the engine against {a['wrong_namings']} and "
            f"{b['wrong_namings']}") in readme
