"""The accuracy that travels with an answer must be read, never guessed.

``src/infrastructure/trial_summary.py`` puts the measured naming precision on the wire
so the cockpit can print it beside a named commit. The failure to avoid is a number that
looks measured and is not: a checkout without a trial summary must say the accuracy is
unknown rather than fall back to a plausible figure.
"""
from __future__ import annotations

import json
from pathlib import Path

from src.infrastructure import trial_summary

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def test_the_committed_summary_is_reported_verbatim():
    accuracy = trial_summary.naming_accuracy()
    recorded = json.loads((REPO_ROOT / "correlation_trial_summary.json").read_text(encoding="utf-8"))
    assert accuracy["measured"] is True
    assert accuracy["precision_when_it_names_a_commit"] == recorded["headline"]["naming_precision"]
    assert accuracy["namings_measured"] == recorded["headline"]["times_a_commit_was_named"]
    assert accuracy["recall_on_regressions"] == recorded["headline"]["naming_recall_on_regressions"]
    assert accuracy["corpus_cases"] == recorded["cases"]
    assert accuracy["measured_by_command"] == "python scripts/correlation_trial.py"


def test_a_missing_summary_reports_unknown_rather_than_a_plausible_number(tmp_path):
    accuracy = trial_summary.naming_accuracy(tmp_path / "nothing-here.json")
    assert accuracy["measured"] is False
    assert accuracy["precision_when_it_names_a_commit"] is None
    assert accuracy["namings_measured"] is None
    assert "no measured accuracy" in accuracy["note"]
    assert "python scripts/correlation_trial.py" in accuracy["note"]


def test_a_malformed_summary_is_not_read_as_a_measurement(tmp_path):
    broken = tmp_path / "broken.json"
    broken.write_text("{not json at all", encoding="utf-8")
    assert trial_summary.naming_accuracy(broken)["measured"] is False


def test_a_summary_without_a_precision_field_is_not_a_measurement(tmp_path):
    partial = tmp_path / "partial.json"
    partial.write_text(json.dumps({"cases": 10, "headline": {}}), encoding="utf-8")
    assert trial_summary.naming_accuracy(partial)["measured"] is False


def test_a_summary_that_is_not_an_object_is_not_a_measurement(tmp_path):
    listy = tmp_path / "list.json"
    listy.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    assert trial_summary.naming_accuracy(listy)["measured"] is False


def test_the_summary_is_cached_for_the_life_of_the_process(tmp_path):
    """Documents the staleness the cache buys, so it is not found as a surprise.

    A re-run of the trial does not change what a running server reports until it is
    restarted. That is a deliberate trade: the alternative is reading and parsing a
    file on every incident request. It is written down here and in the module docstring
    rather than left for somebody to file as a provenance bug.
    """
    path = tmp_path / "summary.json"
    path.write_text(json.dumps({"cases": 10, "headline": {"naming_precision": 0.5}}), encoding="utf-8")
    first = trial_summary.naming_accuracy(path)
    assert first["precision_when_it_names_a_commit"] == 0.5

    path.write_text(json.dumps({"cases": 10, "headline": {"naming_precision": 0.9}}), encoding="utf-8")
    assert trial_summary.naming_accuracy(path)["precision_when_it_names_a_commit"] == 0.5, (
        "the cache is no longer holding, so the docstring's warning about needing a "
        "restart is now wrong and should be removed"
    )
    trial_summary._load.cache_clear()
    assert trial_summary.naming_accuracy(path)["precision_when_it_names_a_commit"] == 0.9


def test_the_note_carries_the_denominator_not_only_the_rate():
    """A precision without its sample size is a rate somebody can inflate by naming less."""
    note = trial_summary.naming_accuracy()["note"]
    recorded = json.loads((REPO_ROOT / "correlation_trial_summary.json").read_text(encoding="utf-8"))
    assert str(recorded["headline"]["times_a_commit_was_named"]) in note
    assert str(recorded["cases"]) in note
