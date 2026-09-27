"""The held-out split has to be a split, not a second look at the same corpus.

These tests hold ``scripts/attribution_split.py`` to the properties its published
figures rest on: the cut is where the summary says, the two sides cannot see each
other's commits inside any window considered, each side is built by the unchanged
generator from its own commits and its own seed, and the recorded summary is what the
committed code produces.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

import attribution_split as split  # noqa: E402
import correlation_trial as trial  # noqa: E402

SUMMARY_PATH = REPO_ROOT / "attribution_holdout_summary.json"


@pytest.fixture(scope="module")
def commits():
    stream, _ = trial.load_commit_stream()
    return stream


def test_the_cut_puts_every_commit_on_exactly_one_side(commits):
    train, held_out = split.split_stream(commits)
    assert len(train) + len(held_out) == len(commits)
    assert {c.sha for c in train}.isdisjoint({c.sha for c in held_out})
    assert all(c.committed_at < split.SPLIT_CUT_UTC for c in train)
    assert all(c.committed_at >= split.SPLIT_CUT_UTC for c in held_out)
    assert (len(train), len(held_out)) == (42, 17)


def test_no_window_considered_can_reach_across_the_cut(commits):
    train, held_out = split.split_stream(commits)
    gap = held_out[0].committed_at - train[-1].committed_at
    assert gap > timedelta(minutes=split.MAX_WINDOW_CONSIDERED_MINUTES)


def test_each_side_is_built_from_its_own_commits_and_seed(commits):
    train_cases, train = split.train_corpus(commits)
    held_cases, held_out = split.held_out_corpus(commits)
    train_shas = {c.sha for c in train}
    held_shas = {c.sha for c in held_out}
    for case in train_cases:
        if case.causing_sha:
            assert case.causing_sha in train_shas
        # A train reading, less the widest window considered, never reaches held-out.
        assert case.observed_at < held_out[0].committed_at
    for case in held_cases:
        if case.causing_sha:
            assert case.causing_sha in held_shas
        window_start = case.observed_at - timedelta(minutes=split.MAX_WINDOW_CONSIDERED_MINUTES)
        assert window_start > train[-1].committed_at
    assert split.TRAIN_SEED != split.HELD_OUT_SEED
    # The generator is the published one, unchanged: same strata, same sizes.
    assert len(train_cases) == len(held_cases) == 1160


def test_the_held_out_seed_was_not_used_by_any_earlier_run():
    """19850717 and 20261231 were looked at when the crowding gate was checked."""
    assert split.HELD_OUT_SEED not in (trial.DEFAULT_SEED, 19850717, 20261231)


def test_the_recorded_summary_matches_a_fresh_run():
    result = subprocess.run(
        [sys.executable, "scripts/attribution_split.py", "--check"],
        capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=600,
    )
    assert result.returncode == 0, result.stdout[-1500:]


def test_the_summary_labels_itself_synthetic_and_names_its_command():
    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    assert summary["measured_by_command"] == "python scripts/attribution_split.py"
    assert "Synthetic" in summary["label"] and "self-authored" in summary["label"]
    assert summary["split"]["held_out_seed"] == split.HELD_OUT_SEED
    shipped = [row for row in summary["engines"] if row["engine"] == summary["shipped_engine"]]
    assert len(shipped) == 1
    for side in ("train", "held_out"):
        assert shipped[0][side]["unexpected_outcomes"] == 0


def test_the_wilson_interval_brackets_the_rate():
    low, high = split.wilson_interval(29, 71)
    assert low < 29 / 71 < high
    assert split.wilson_interval(0, 0) is None
