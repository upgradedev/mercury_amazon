"""The cockpit's rendered text must clear the 10-foot floor on its own track.

This runs ``scripts/measure_legibility.py``, which starts the server, opens the
page in Chromium at 1920x1080, drives it until the evidence panels have content
in them, and reports the smallest rendered ``font-size`` on screen. The defect it
pins: the page set a 24px root at the television breakpoint and then wrote every
label, badge and provenance stamp in fractions of that root, so the headline read
across a room at 55.7px while the evidence under it rendered at 17.3px.

It lives in ``tests/ux`` rather than ``tests/e2e`` on purpose. Readiness gate C5
asks for an end-to-end browser journey and looks for a browser driver under
``tests/e2e``; a font-size measurement is not a user journey, and putting this
file there would flip that gate to PASS on the strength of an import. C5 stays
failing and exempt, which is the truth.

The measurement needs an optional extra and a browser download, so it skips
rather than fails where neither is present::

    pip install -e ".[ux]" && playwright install chromium
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FLOOR_PX = 24.0
NOTHING_MEASURED = 2


@pytest.fixture(scope="module")
def measurement() -> dict:
    result = subprocess.run(
        [sys.executable, "scripts/measure_legibility.py", "--json"],
        capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=300,
    )
    if result.returncode == NOTHING_MEASURED:
        pytest.skip(f"nothing was measured: {result.stdout.strip()[:200]}")
    assert result.stdout.strip(), f"the measurement printed nothing:\n{result.stderr[-2000:]}"
    return json.loads(result.stdout)


def test_no_visible_text_renders_below_the_ten_foot_floor(measurement):
    offenders = measurement["offenders"]
    assert measurement["smallest_rendered_px"] >= FLOOR_PX, (
        f"{measurement['under_floor']} of {measurement['text_element_readings']} readings are under "
        f"{FLOOR_PX:.0f}px, smallest {measurement['smallest_rendered_px']}px: "
        f"{[(o['px'], o['selector']) for o in offenders[:8]]}"
    )
    assert measurement["under_floor"] == 0


def test_the_evidence_panels_were_actually_open_when_this_was_measured(measurement):
    """A measurement of the default view alone passes by not looking.

    The panels are hidden on load and most of their text does not exist until a
    fetch has returned, so a run that never opened them proves nothing about the
    evidence a viewer reads.
    """
    per_view = measurement["per_view"]
    assert set(per_view) == {"wall", "incident", "velocity", "spend"}
    for view, stats in per_view.items():
        assert stats["text_elements"] >= 20, f"the {view} view rendered almost no text"


def test_the_page_never_scrolls_sideways_on_a_television(measurement):
    assert measurement["horizontal_overflow"] is False


def test_the_fixed_key_bar_does_not_cover_the_content_it_sits_under(measurement):
    """Raising the type made the bar wrap, and it is fixed over the page."""
    assert measurement["keybar_height_px"] <= measurement["body_padding_bottom_px"], (
        f"the key bar is {measurement['keybar_height_px']}px tall but the body reserves only "
        f"{measurement['body_padding_bottom_px']}px below the content"
    )


def test_the_readme_legibility_numbers_match_this_measurement(measurement):
    """The README quotes the script's output. Run it and compare.

    Same pin as the spatial navigation and security audit counts elsewhere in
    this suite: a number quoted in prose is free to drift the day after it is
    typed unless something re-runs the command that produced it.
    """
    import re

    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    readings = re.search(r"Measured (\d+) visible text readings across (\d+) views", readme)
    assert readings, "the README no longer quotes the legibility measurement"
    smallest = re.search(r"smallest rendered text anywhere: ([\d.]+)px", readme)
    assert smallest, "the README no longer quotes the smallest rendered size"
    under = re.search(r"readings under the floor: (\d+) of (\d+)", readme)
    assert under, "the README no longer quotes the count under the floor"

    assert int(readings.group(1)) == measurement["text_element_readings"]
    assert int(readings.group(2)) == len(measurement["per_view"])
    assert float(smallest.group(1)) == measurement["smallest_rendered_px"]
    assert (int(under.group(1)), int(under.group(2))) == (
        measurement["under_floor"], measurement["text_element_readings"]
    )
