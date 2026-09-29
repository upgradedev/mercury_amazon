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


def test_the_tuning_script_does_not_load_the_held_out_side():
    """Parameters are chosen by scripts/tune_attribution.py, on train corpora only.

    An import-level check in a fresh interpreter: after importing the tuning script, no
    loaded module may be ``attribution_split`` or define the held-out builder or seed.
    It stops an import, not a determined edit, and is described that way.
    """
    probe = "\n".join((
        "import sys; sys.path[:0] = ['scripts', '.']",
        "import tune_attribution",
        "bad = sorted(name for name, mod in list(sys.modules.items())",
        "             if name == 'attribution_split'",
        "             or hasattr(mod, 'held_out_corpus') or hasattr(mod, 'HELD_OUT_SEED'))",
        "print(','.join(bad))",
        "sys.exit(1 if bad else 0)",
    ))
    result = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True,
                            cwd=str(REPO_ROOT), timeout=120)
    assert result.returncode == 0, f"the tuning script loads the held-out side: {result.stdout}{result.stderr}"
    source = (REPO_ROOT / "scripts" / "tune_attribution.py").read_text(encoding="utf-8")
    assert "from attribution_train import SYNTHETIC_LABEL, train_corpus" in source
    train_source = (REPO_ROOT / "scripts" / "attribution_train.py").read_text(encoding="utf-8")
    for forbidden in ("held_out_corpus", "HELD_OUT_SEED", "import attribution_split", "from attribution_split"):
        assert forbidden not in train_source, f"attribution_train.py references {forbidden}"


def test_the_recorded_tuning_summary_matches_a_fresh_sweep():
    result = subprocess.run(
        [sys.executable, "scripts/tune_attribution.py", "--check"],
        capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=600,
    )
    assert result.returncode == 0, result.stdout[-1500:]


# ------------------------------------------------ The documents quote the record


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _engines() -> dict:
    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    return {row["engine"]: row for row in summary["engines"]}, summary["shipped_engine"]


def _precision_row(before: dict, after: dict) -> str:
    return (f"| Held-out naming precision | {_pct(before['naming_precision'])} "
            f"({before['correct_namings']} of {before['times_a_commit_was_named']}, 95% CI "
            f"{_pct(before['naming_precision_95ci'][0])} to {_pct(before['naming_precision_95ci'][1])}) | "
            f"**{_pct(after['naming_precision'])}** ({after['correct_namings']} of "
            f"{after['times_a_commit_was_named']}, 95% CI {_pct(after['naming_precision_95ci'][0])} to "
            f"{_pct(after['naming_precision_95ci'][1])}) |")


def _false_exo_row(before: dict, after: dict) -> str:
    return (f"| Held-out false attribution on exogenous spikes | "
            f"{_pct(before['false_attribution_rate_on_exogenous_spikes'])} "
            f"({before['false_attributions_on_exogenous_spikes']} of 300) | "
            f"**{_pct(after['false_attribution_rate_on_exogenous_spikes'])}** "
            f"({after['false_attributions_on_exogenous_spikes']} of 300) |")


def test_the_documents_quote_the_recorded_held_out_figures():
    """Every held-out figure the README, EVIDENCE and Devpost text quote, pinned to the file.

    Two comparisons are published: the runtime filter (previous engine to shipped engine),
    which is the current before-and-after, and the window change before it (v1 to v2),
    which EVIDENCE keeps as history. Both are held to the record.
    """
    engines, shipped = _engines()
    after = engines[shipped]["held_out"]
    before = engines[split.PREVIOUS_ENGINE]["held_out"]
    v1 = engines["v1_2026_09_08"]["held_out"]
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    evidence = " ".join((REPO_ROOT / "docs" / "EVIDENCE.md").read_text(encoding="utf-8").split())
    devpost = " ".join((REPO_ROOT / "docs" / "DEVPOST_SUBMISSION.md").read_text(encoding="utf-8").split())
    readme_flat = " ".join(readme.split())

    assert f"{_pct(after['naming_precision'])} (n={after['times_a_commit_was_named']} namings" in readme_flat
    assert f"from {_pct(before['naming_precision'])} to {_pct(after['naming_precision'])}" in readme_flat
    assert (f"from {_pct(before['naming_recall_on_regressions'])} to "
            f"{_pct(after['naming_recall_on_regressions'])}") in readme_flat
    assert (f"from {_pct(before['refused_to_name_rate_on_all_anomalies'])} to "
            f"{_pct(after['refused_to_name_rate_on_all_anomalies'])}") in readme_flat
    assert f"from {before['wrong_namings']} to {after['wrong_namings']}" in readme_flat

    assert _precision_row(before, after) in evidence, "the EVIDENCE runtime-filter precision row drifted"
    assert _false_exo_row(before, after) in evidence
    assert (f"| Held-out naming recall | {_pct(before['naming_recall_on_regressions'])} "
            f"({before['correct_namings']} of 600) | **{_pct(after['naming_recall_on_regressions'])}** "
            f"({after['correct_namings']} of 600) |") in evidence
    assert (f"| Wrong commit named for a regression | {before['regressions_named_wrong_commit']} | "
            f"**{after['regressions_named_wrong_commit']}** |") in evidence
    # The history the filter came after: v1 to v2, the window change.
    assert _precision_row(v1, before) in evidence, "the EVIDENCE v1 to v2 precision row drifted"
    assert _false_exo_row(v1, before) in evidence
    assert f"{v1['wrong_namings']} under v1, {before['wrong_namings']} under v2" in evidence

    assert (f"right {_pct(after['naming_precision'])} of the time over "
            f"{after['times_a_commit_was_named']} namings") in devpost
    assert f"read {_pct(v1['naming_precision'])} over {v1['times_a_commit_was_named']} namings" in devpost
    assert (f"from {_pct(before['naming_precision'])} over {before['times_a_commit_was_named']} namings "
            f"to {_pct(after['naming_precision'])} over {after['times_a_commit_was_named']}") in devpost


def test_the_documents_quote_the_filter_cost_breakdown():
    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    cost = summary["runtime_filter_cost_on_published_labels"]
    variant = {r["engine"]: r for r in summary["runtime_cause_assumption_variant"]["rows"]}
    evidence = " ".join((REPO_ROOT / "docs" / "EVIDENCE.md").read_text(encoding="utf-8").split())
    readme = " ".join((REPO_ROOT / "README.md").read_text(encoding="utf-8").split())
    wrong = cost["regressions_named_wrong_commit"]
    labelled = cost["wrong_namings_whose_labelled_cause_touched_no_runtime_file"]
    assert f"of v3's {wrong} wrong namings on regressions, {labelled} are cases" in evidence
    assert f"{labelled} of its {wrong} wrong namings on regressions" in readme
    lost = cost["hits_lost_against_previous"]
    if lost == cost["lost_hits_whose_labelled_cause_touched_no_runtime_file"]:
        assert f"all {lost} correct namings v2 made and v3 does not" in evidence
    for name in (split.PREVIOUS_ENGINE, split.SHIPPED_ENGINE):
        row = variant[name]
        assert (f"{_pct(row['naming_precision'])} ({row['correct_namings']} of "
                f"{row['times_a_commit_was_named']})") in evidence


def test_the_shipped_engine_keeps_the_train_choice_and_imposes_the_runtime_filter():
    """Window and gate are the train sweep's choice; the runtime filter is imposed on top.

    The sweep's rule picked no filter (under the generator's labels a prose-only commit can
    cause a server regression), so the shipped engine departs from it on that one axis and
    this test says so rather than pretending the sweep chose it. The server wires the same
    engine, and the summary publishes the filter's cost on the unchanged labels.
    """
    from src.domain.change_scope import MERCURY_SERVICE_SCOPE
    from src.domain.incident_correlation import (
        DEFAULT_ATTRIBUTION_WINDOW_MINUTES,
        DEFAULT_MAX_COMMITS_IN_WINDOW,
    )
    from src.interfaces import mcp_server

    tuning = json.loads((REPO_ROOT / "attribution_tuning_summary.json").read_text(encoding="utf-8"))
    chosen = tuning["chosen"]
    engine = split.ENGINES[split.SHIPPED_ENGINE]["build"]()
    assert (engine.attribution_window_minutes, engine.max_commits_in_window) == (chosen["window"], chosen["gate"])
    assert chosen["scope"] is False, "the sweep now picks the filter itself; retire this departure"
    assert engine.service_scope is MERCURY_SERVICE_SCOPE
    assert (DEFAULT_ATTRIBUTION_WINDOW_MINUTES, DEFAULT_MAX_COMMITS_IN_WINDOW) == (chosen["window"], chosen["gate"])
    assert tuning["split"].startswith("train only")
    served = mcp_server.incident_correlator
    assert (served.attribution_window_minutes, served.max_commits_in_window, served.service_scope) == (
        engine.attribution_window_minutes, engine.max_commits_in_window, engine.service_scope)
    previous = split.ENGINES[split.PREVIOUS_ENGINE]["build"]()
    assert (previous.attribution_window_minutes, previous.max_commits_in_window, previous.service_scope) == (
        engine.attribution_window_minutes, engine.max_commits_in_window, None)


def test_the_filter_cost_on_the_published_labels_is_published_and_explained():
    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    cost = summary["runtime_filter_cost_on_published_labels"]
    engines, shipped = _engines()
    assert cost["engine"] == shipped
    assert cost["regressions_named_wrong_commit"] == engines[shipped]["held_out"]["regressions_named_wrong_commit"]
    variant = summary["runtime_cause_assumption_variant"]
    assert variant["note"].startswith("ASSUMPTION VARIANT, NOT A MEASURED GAIN")
    assert [r["engine"] for r in variant["rows"]] == [split.PREVIOUS_ENGINE, shipped]


# ------------------------------------------- The figure is conditional on a delay ceiling


def test_the_delay_ceiling_rows_hold_the_published_figure_at_the_published_ceiling():
    """The 75 minute row is the headline, so the table and the headline cannot drift apart."""
    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    sensitivity = summary["delay_ceiling_sensitivity"]
    assert sensitivity["published_delay_minutes"] == list(trial.PROPAGATION_DELAY_MINUTES)
    assert summary["split"]["propagation_delay_minutes"] == list(trial.PROPAGATION_DELAY_MINUTES)
    engines, shipped = _engines()
    published = [r for r in sensitivity["rows"]
                 if r["delay_ceiling_minutes"] == trial.PROPAGATION_DELAY_MINUTES[1]]
    by_engine = {r["engine"]: r for r in published}
    for name, row in engines.items():
        assert by_engine[name]["naming_precision"] == row["held_out"]["naming_precision"]
        assert by_engine[name]["times_a_commit_was_named"] == row["held_out"]["times_a_commit_was_named"]
    # The shipped window equals the published ceiling; that coincidence is what the table discloses.
    assert split.ENGINES[shipped]["build"]().attribution_window_minutes == trial.PROPAGATION_DELAY_MINUTES[1]


def test_the_ranking_but_not_the_level_survives_other_delay_ceilings():
    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    rows = summary["delay_ceiling_sensitivity"]["rows"]
    ceilings = sorted({r["delay_ceiling_minutes"] for r in rows})
    assert ceilings == list(split.DELAY_CEILINGS_MINUTES)
    shipped = summary["shipped_engine"]
    precision = {(r["delay_ceiling_minutes"], r["engine"]): r["naming_precision"] for r in rows}
    # The window change (v1 to v2) held its ranking at every ceiling. The runtime filter
    # does not claim one: on these labels v3 sits below v2 up to 120 minutes, which
    # EVIDENCE says in words.
    for ceiling in ceilings:
        assert precision[(ceiling, "v2_2026_09_27")] > precision[(ceiling, "v1_2026_09_08")]
    # The level falls as the ceiling rises past the window: the headline is conditional.
    assert precision[(ceilings[-1], shipped)] < precision[(75, shipped)]


def test_the_check_compares_every_field_but_the_run_metadata():
    recorded = {"measured_at_utc": "a", "measured_on": "x", "python_version": "3.11",
                "split": {"cut_utc": "c", "train_burstiness": {"mean": 2.57}}, "engines": []}
    fresh = {"measured_at_utc": "b", "measured_on": "y", "python_version": "3.12",
             "split": {"cut_utc": "c", "train_burstiness": {"mean": 2.86}}, "engines": []}
    assert split.drifted_keys(recorded, fresh) == ["split.train_burstiness.mean"]
    assert split.drifted_keys(recorded, recorded) == []


def _cell(row: dict) -> str:
    return f"{_pct(row['naming_precision'])} ({row['correct_namings']} of {row['times_a_commit_was_named']})"


def test_the_documents_quote_the_recorded_delay_ceiling_rows():
    """The conditional figures the README, EVIDENCE and Devpost text quote, pinned to the file."""
    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    shipped = summary["shipped_engine"]
    rows = {(r["delay_ceiling_minutes"], r["engine"]): r for r in summary["delay_ceiling_sensitivity"]["rows"]}
    readme = " ".join((REPO_ROOT / "README.md").read_text(encoding="utf-8").split())
    evidence = " ".join((REPO_ROOT / "docs" / "EVIDENCE.md").read_text(encoding="utf-8").split())
    devpost = " ".join((REPO_ROOT / "docs" / "DEVPOST_SUBMISSION.md").read_text(encoding="utf-8").split())
    at_90, at_180 = _pct(rows[(90, shipped)]["naming_precision"]), _pct(rows[(180, shipped)]["naming_precision"])
    for text in (readme, devpost):
        assert f"{at_90} at 90" in text and at_180 in text
    for ceiling in split.DELAY_CEILINGS_MINUTES:
        v1, v2 = rows[(ceiling, "v1_2026_09_08")], rows[(ceiling, split.PREVIOUS_ENGINE)]
        v3 = rows[(ceiling, shipped)]
        label = f"**{ceiling} (published)**" if ceiling == 75 else str(ceiling)
        if ceiling == 75:
            line = (f"| {label} | **{_cell(v1)}** | **{_cell(v2)}** | **{_cell(v3)}** | "
                    f"**{v3['regressions_named_wrong_commit']}** |")
        else:
            line = (f"| {label} | {_cell(v1)} | {_cell(v2)} | {_cell(v3)} | "
                    f"{v3['regressions_named_wrong_commit']} |")
        assert line in evidence, f"the EVIDENCE delay-ceiling row for {ceiling} no longer matches the record"
    spread = summary["held_out_seed_spread"]["engines"][shipped]
    assert f"averaging {_pct(spread['mean_naming_precision'])}" in evidence
