"""Reads the recorded correlation trial so an answer can carry its own accuracy.

An attribution is worth exactly what its measured precision says it is worth, and
the moment that matters is the moment somebody is about to act on it, not the moment
they read the README. So the endpoint that names a commit ships the number beside the
name, and the cockpit prints it under the headline.

The number comes from ``correlation_trial_summary.json``, which
``python scripts/correlation_trial.py`` writes and
``python scripts/correlation_trial.py --check`` proves is still what the committed
code produces. Nothing here recomputes it: a value invented at request time would be
a different number from the published one, which is the failure this file exists to
avoid.

When the file is absent or unreadable the accuracy is reported as unknown rather than
guessed, and the answer says so. A missing measurement is not a good measurement.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SUMMARY_PATH = REPO_ROOT / "correlation_trial_summary.json"

#: The command that writes the file this module reads. Shipped in the payload so a
#: reader can reproduce the figure rather than take it.
MEASURED_BY_COMMAND = "python scripts/correlation_trial.py"


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


def naming_accuracy(path: Path = SUMMARY_PATH) -> dict[str, object]:
    """What the labelled corpus measured about naming a commit, or an honest blank.

    ``measured`` is False when the summary file is missing or malformed, and every
    figure is then None. The cockpit renders that as "accuracy not measured in this
    checkout" rather than as a confident silence.
    """
    summary = _load(str(path))
    head = summary.get("headline") if isinstance(summary.get("headline"), dict) else {}
    precision = head.get("naming_precision")
    if precision is None:
        return {
            "measured": False,
            "precision_when_it_names_a_commit": None,
            "namings_measured": None,
            "recall_on_regressions": None,
            "corpus_cases": None,
            "measured_by_command": MEASURED_BY_COMMAND,
            "note": (
                "No correlation trial summary is present in this checkout, so this answer "
                f"carries no measured accuracy. Produce one with: {MEASURED_BY_COMMAND}"
            ),
        }
    return {
        "measured": True,
        "precision_when_it_names_a_commit": precision,
        "namings_measured": head.get("times_a_commit_was_named"),
        "recall_on_regressions": head.get("naming_recall_on_regressions"),
        "corpus_cases": summary.get("cases"),
        "measured_by_command": MEASURED_BY_COMMAND,
        "note": (
            f"Against {summary.get('cases')} labelled cases, this correlator named a commit "
            f"{head.get('times_a_commit_was_named')} times and the commit it named was the one "
            f"that caused the reading {precision} of those times. It named the cause of "
            f"{head.get('naming_recall_on_regressions')} of the genuine regressions in the "
            "corpus, refusing on the rest."
        ),
    }
