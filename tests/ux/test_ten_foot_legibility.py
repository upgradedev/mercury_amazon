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


def test_the_operational_text_reads_above_the_body_copy_not_at_the_floor(measurement):
    """A floor is not a reading order.

    The sentence that says what the D-pad is about to do ("Ready to stage a rollback of
    checkout-api to b485c43"), the two provenance chips that say whether the number
    driving it was live, and the connection pill were all sitting exactly on the 24px
    floor, which is where the decorative wordmark caption sits. They are now a tier above
    it. This asserts the ordering rather than a magic number, so the type scale can move
    as long as the operational text keeps reading larger than the smallest decoration.
    """
    assert measurement["operational_readings"] >= 10, (
        "almost no operational text was measured, so this assertion proves nothing"
    )
    assert measurement["smallest_operational_px"] > measurement["smallest_rendered_px"], (
        f"the smallest operational reading is {measurement['smallest_operational_px']}px, the same "
        f"as the smallest reading anywhere ({measurement['smallest_rendered_px']}px): "
        f"{measurement['smallest_operational_selector']}"
    )


def test_the_provenance_stamp_renders_on_the_same_screenful_as_the_figure(measurement):
    """A wallboard is never scrolled, so a stamp below the fold is a stamp nobody reads.

    Measured before this was fixed: the anomaly factor rendered at y=274 and the words
    saying where that number came from were not in the first 1080 pixels at all. A
    viewer across a room read a locally generated 12.9x as a production number while the
    README claimed every number on the screen carried a badge saying otherwise.

    Reproduce the failure on a clean checkout, which overwrites the page and then throws
    the copy away, so stash anything uncommitted in it first::

        git show 455f60b:docs/index.html > docs/index.html
        python scripts/measure_legibility.py     # exits 1, zero stamps above the fold
        git checkout -- docs/index.html
    """
    fold = measurement["provenance_above_the_fold"]
    assert fold["hero_figure_top_px"] is not None, "the hero figure did not render at all"
    assert fold["stamps_above_the_fold"] >= 1, (
        "no provenance stamp renders within the first "
        f"{fold['viewport_height_px']}px, while the figure it qualifies renders at "
        f"y={fold['hero_figure_top_px']}: {fold['stamps']}"
    )
    assert fold["topmost_stamp_top_px"] <= fold["viewport_height_px"]
    # The words themselves, not the machine value. "offline-fixture" is a data source
    # slug; "OFFLINE FIXTURE" is what a viewer reads.
    assert any("OFFLINE FIXTURE" in text or "LIVE" in text
               for text in fold["stamp_text_above_the_fold"]), (
        f"the stamps above the fold say {fold['stamp_text_above_the_fold']}, none of which "
        "tells a viewer whether the number was read live or served from a recording"
    )
    assert fold["strings_naming_a_source_above_the_fold"] >= 1


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

    Two of the quoted numbers are pinned exactly and one is not, on purpose. The
    smallest rendered size and the count under the floor are what the fix claims,
    and neither moves unless the type scale moves. The total number of readings
    moves with whatever the page happened to render, which includes a commit
    message from ``git log``, so holding the README to it would turn an unrelated
    commit into a red build. The README says so where it quotes the number.
    """
    import re

    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    readings = re.search(r"Measured (\d+) visible text readings across (\d+) views", readme)
    assert readings, "the README no longer quotes the legibility measurement"
    smallest = re.search(r"smallest rendered text anywhere: ([\d.]+)px", readme)
    assert smallest, "the README no longer quotes the smallest rendered size"
    under = re.search(r"readings under the floor: (\d+) of (\d+)", readme)
    assert under, "the README no longer quotes the count under the floor"

    assert int(readings.group(2)) == len(measurement["per_view"])
    assert float(smallest.group(1)) == measurement["smallest_rendered_px"], (
        f"README says the smallest rendered text is {smallest.group(1)}px, this run measured "
        f"{measurement['smallest_rendered_px']}px"
    )
    assert int(under.group(1)) == measurement["under_floor"], (
        f"README says {under.group(1)} readings are under the floor, this run measured "
        f"{measurement['under_floor']}"
    )
    assert int(under.group(2)) == int(readings.group(1)), (
        "the two totals the README quotes from the same run disagree with each other"
    )
    assert int(readings.group(1)) > 0

    operational = re.search(r"smallest operational text[^:]*: ([\d.]+)px", readme)
    assert operational, "the README no longer quotes the smallest operational reading"
    assert float(operational.group(1)) == measurement["smallest_operational_px"], (
        f"README says the smallest operational text is {operational.group(1)}px, this run "
        f"measured {measurement['smallest_operational_px']}px"
    )
