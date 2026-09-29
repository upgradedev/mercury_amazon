"""Reads the recorded held-out measurement so an answer can carry its own accuracy.

An attribution is worth exactly what its measured precision says it is worth, and
the moment that matters is the moment somebody is about to act on it, not the moment
they read the README. So the endpoint that names a commit ships the number beside the
name, and the cockpit prints it under the headline.

Since 2026-09-27 the number is the **held-out** one. It comes from
``attribution_holdout_summary.json``, which ``python scripts/attribution_split.py``
writes and ``python scripts/attribution_split.py --check`` proves is still what the
committed code produces: the shipped engine's figures on a split of the corpus that no
parameter was tuned on. One assumption is shared by both splits and so cannot be tested
by holding one out: the generator's ceiling on how long a regression takes to show,
which equals the shipped 75 minute window. The note says so, and reads the ceiling from
the summary. The in-sample figure the page carried before (52.2% over 113
namings) was measured on the corpus its crowding gate was chosen on, so it is kept in
``docs/EVIDENCE.md`` as history rather than shown beside a live answer. Nothing here
recomputes a figure: a value invented at request time would be a different number
from the published one, which is the failure this file exists to avoid.

When the file is absent or unreadable the accuracy is reported as unknown rather than
guessed, and the answer says so. A missing measurement is not a good measurement.

The read is cached for the life of the process, because the file only changes when
somebody re-runs the measurement. That has one consequence worth stating rather than
discovering: **re-running it while the server is up does not change the figure on
screen until the server is restarted.** It is a stale cache, not a provenance bug, and
the payload always carries the command that produced the number so the two can be
compared.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SUMMARY_PATH = REPO_ROOT / "attribution_holdout_summary.json"

#: The command that writes the file this module reads. Shipped in the payload so a
#: reader can reproduce the figure rather than take it.
MEASURED_BY_COMMAND = "python scripts/attribution_split.py"


@lru_cache(maxsize=1)
def _load(path_text: str) -> dict:
    path = Path(path_text)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _held_out_figures(summary: dict) -> dict:
    """The shipped engine's held-out block, or an empty dict when there is none."""
    engines = summary.get("engines")
    shipped = summary.get("shipped_engine")
    if not isinstance(engines, list):
        return {}
    for row in engines:
        if isinstance(row, dict) and row.get("engine") == shipped and isinstance(row.get("held_out"), dict):
            return row["held_out"]
    return {}


def _delay_ceiling_minutes(summary: dict) -> float | None:
    """The generator's delay ceiling the held-out figure is conditional on, if recorded."""
    split = summary.get("split")
    delay = split.get("propagation_delay_minutes") if isinstance(split, dict) else None
    if isinstance(delay, list) and len(delay) == 2 and isinstance(delay[1], (int, float)):
        return delay[1]
    return None


def naming_accuracy(path: Path = SUMMARY_PATH) -> dict[str, object]:
    """What the held-out split measured about naming a commit, or an honest blank.

    ``measured`` is False when the summary file is missing or malformed, and every
    figure is then None. The cockpit renders that as the note below rather than as a
    confident silence.
    """
    summary = _load(str(path))
    held = _held_out_figures(summary)
    precision = held.get("naming_precision")
    if precision is None:
        return {
            "measured": False,
            "split": None,
            "precision_when_it_names_a_commit": None,
            "precision_95ci": None,
            "namings_measured": None,
            "recall_on_regressions": None,
            "corpus_cases": None,
            "assumed_delay_ceiling_minutes": None,
            "measured_by_command": MEASURED_BY_COMMAND,
            "note": (
                "No held-out attribution summary is present in this checkout, so this answer "
                f"carries no measured accuracy. Produce one with: {MEASURED_BY_COMMAND}"
            ),
        }
    ceiling = _delay_ceiling_minutes(summary)
    condition = (
        f" The figure assumes, as the generator does, that a regression shows within "
        f"{ceiling:g} minutes of its commit. The window was widened to match on the train "
        f"split, which shares that assumption, so holding data out cannot test it; "
        f"{SUMMARY_PATH.name} records the figure at longer delays."
        if ceiling is not None else
        " The summary does not record the delay the generator assumed, so the figure's "
        "condition is unknown."
    )
    return {
        "measured": True,
        "split": "held-out",
        "engine": summary.get("shipped_engine"),
        "precision_when_it_names_a_commit": precision,
        "precision_95ci": held.get("naming_precision_95ci"),
        "namings_measured": held.get("times_a_commit_was_named"),
        "recall_on_regressions": held.get("naming_recall_on_regressions"),
        "refused_to_name_rate_on_anomalies": held.get("refused_to_name_rate_on_all_anomalies"),
        "corpus_cases": held.get("cases"),
        "assumed_delay_ceiling_minutes": ceiling,
        "measured_by_command": MEASURED_BY_COMMAND,
        "note": (
            f"On a held-out split of {held.get('cases')} synthetic, self-authored labelled cases "
            f"that no parameter was tuned on, this correlator named a commit "
            f"{held.get('times_a_commit_was_named')} times and the commit it named was the one "
            f"that caused the reading {precision} of those times (95% interval "
            f"{held.get('naming_precision_95ci')}). It named the cause of "
            f"{held.get('naming_recall_on_regressions')} of the genuine regressions, refusing "
            "on the rest." + condition
        ),
    }
