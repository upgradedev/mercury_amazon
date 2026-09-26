"""A refusal is a refusal, not an acquittal, on every surface a judge reads.

The finding that produced this file: Mercury rendered a refusal to attribute an
incident as proof that no deploy caused it. The README glossed both
``NO_CANDIDATE_IN_WINDOW`` and ``WINDOW_TOO_CROWDED`` as an instruction not to revert
because the incident was not a deploy, and the cockpit headline for both read as the
same instruction. Neither refusal can support that: an empty window says nothing
about a change that landed outside it, a crowded window says nothing about which of
its changes did it, and a missing baseline says nothing at all. The only verdict that
may say nothing needs reverting is ``NO_ANOMALY``.

The domain states the contract as ``REFUSAL_MUST_NOT_CLAIM``. This file holds the
judge-facing documents to it as text, the same way the Alexa and APK pins in
``test_documentation_claims.py`` work. Code spans are stripped before reading, and
mermaid fences are kept, so a retired phrase can be quoted in backticks as the record
of the correction without reading as a live claim while the diagram is still audited.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from src.domain.incident_correlation import REFUSAL_MUST_NOT_CLAIM

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

#: Every document a judge, a viewer or a presenter reads. The generator for the video
#: plan is included because the JSON it writes is regenerated from it.
JUDGE_FACING = [
    "README.md",
    "docs/EVIDENCE.md",
    "docs/DEVPOST_SUBMISSION.md",
    "docs/index.html",
    "docs/UAT_TESTBOOK.md",
    "docs/COMPLIANCE_AND_ARCHITECTURE.md",
    "docs/PERSONA_REVIEW.md",
    "docs/FIRE_TV_BUILD.md",
    "video/SHOT_LIST.md",
    "video/narration.json",
    "video/cue_sheet.json",
    "scripts/build_video_plan.py",
]

#: The documents that describe what a refusal means, and therefore have to use the
#: words the product uses for it.
DESCRIBE_A_REFUSAL = [
    "README.md",
    "docs/EVIDENCE.md",
    "docs/DEVPOST_SUBMISSION.md",
    "docs/index.html",
    "video/SHOT_LIST.md",
    "video/narration.json",
]

#: The wording the finding was about, verbatim. The scanner has to catch every one of
#: these, or it is not a scanner.
RETIRED_WORDING = [
    "Do not revert anything, this is not a deploy.",
    "do not revert anything yet",
    "Do not revert on this. 6 changes landed before the spike",
    "Incident, nothing to blame",
    "tells an on-call engineer when not to blame a deployment",
    "worse off than one who is told to look elsewhere",
    "the refusal rules out a deploy",
    "an anomaly not caused by a deploy",
    "Do not roll back on this answer.",
    "so no deploy caused it",
]


def _live_text(text: str) -> str:
    """The document with code spans removed and whitespace normalised.

    Mermaid fences are unwrapped rather than removed: the diagram is judge-facing and
    the finding was in it. Every other fence, and every inline code span, is a
    quotation, which is how the README keeps the retired phrasing on the page.
    """
    kept = re.sub(r"```mermaid\s*(.*?)```", r" \1 ", text, flags=re.DOTALL)
    without_fences = re.sub(r"```.*?```", " ", kept, flags=re.DOTALL)
    without_inline = re.sub(r"`[^`\n]*`", " ", without_fences)
    return " ".join(without_inline.split())


def _violations(text: str) -> list[str]:
    found = []
    for pattern in REFUSAL_MUST_NOT_CLAIM:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            start, end = max(0, match.start() - 60), match.end() + 60
            found.append(f"{pattern!r} -> ...{text[start:end]}...")
    return found


# ------------------------------------------------- The list catches what it is for

@pytest.mark.parametrize("retired", RETIRED_WORDING)
def test_the_forbidden_list_catches_the_wording_it_was_written_for(retired):
    """Negative control: a scanner that cannot refuse the original text is decoration."""
    assert _violations(retired), f"REFUSAL_MUST_NOT_CLAIM does not catch {retired!r}"


def test_the_forbidden_list_lets_the_honest_wording_through():
    """The replacement wording is held to the same list, so the list must accept it."""
    honest = (
        "Mercury cannot attribute this anomaly to a change: no commit landed in the 60 "
        "minutes before the onset. That is an empty window, not evidence that no change "
        "caused it. It does not call any deploy innocent, and rolling back on this answer "
        "would be a guess. Nothing needs reverting only when the reading is inside its "
        "baseline."
    )
    assert _violations(honest) == []


# --------------------------------------------------- Every judge-facing surface

@pytest.mark.parametrize("relative", JUDGE_FACING)
def test_no_judge_facing_document_states_a_refusal_as_a_certainty(relative):
    path = REPO_ROOT / relative
    assert path.exists(), f"{relative} is missing"
    text = _live_text(path.read_text(encoding="utf-8"))
    violations = _violations(text)
    assert not violations, (
        f"{relative} renders a refusal as a certainty. A refusal says Mercury cannot "
        f"attribute, and why; it never says the incident was not a deploy or that nothing "
        f"needs reverting:\n  " + "\n  ".join(violations)
    )


@pytest.mark.parametrize("relative", DESCRIBE_A_REFUSAL)
def test_every_document_that_describes_a_refusal_says_cannot_attribute(relative):
    text = (REPO_ROOT / relative).read_text(encoding="utf-8").lower()
    assert "cannot attribute" in text, (
        f"{relative} describes the refusal without the words the product uses for it"
    )


def test_the_readme_records_the_retired_phrasing_as_retired_and_never_as_live():
    """Both halves, the same rule the timing retraction follows.

    The correction is part of the evidence, so the old phrasing stays on the page. It
    stays inside backticks, which is what the scanner strips, so it cannot read as a
    live claim.
    """
    # The correction moved with the audit history into docs/EVIDENCE.md; the README
    # must still never state the retired phrasing as live.
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    evidence = (REPO_ROOT / "docs" / "EVIDENCE.md").read_text(encoding="utf-8")
    assert "this is not a deploy" in evidence, (
        "docs/EVIDENCE.md no longer records the phrasing it retired; deleting the correction "
        "hides that the claim moved"
    )
    assert "this is not a deploy" not in _live_text(evidence)
    assert "this is not a deploy" not in _live_text(readme)
    assert "A refusal is not an acquittal" in evidence


# ----------------------------------------------------------- The diagram

def _mermaid_flowchart() -> str:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    blocks = re.findall(r"```mermaid\s*(.*?)```", readme, flags=re.DOTALL)
    flowcharts = [block for block in blocks if block.strip().startswith("flowchart")]
    assert flowcharts, "the README no longer opens with a flowchart"
    return flowcharts[0]


#: The words on the one dotted edge that may lead to "nothing needs reverting": the
#: reading is under the anomaly threshold. It used to say "inside baseline", which read
#: as flat for a reading 1.6 times its baseline, so the label names the threshold now.
NO_ANOMALY_EDGE = "under 3.0x"


def _dotted_edge_targets(chart: str) -> dict[str, str]:
    """Edge label -> target node id, for every dotted edge in the flowchart."""
    targets = {}
    for label, node in re.findall(r'-\.->\|"([^"]+)"\|\s*([A-Za-z_][A-Za-z0-9_]*)', chart):
        targets[label] = node
    return targets


def test_the_diagram_gives_the_inside_baseline_verdict_a_node_of_its_own():
    """The finding, in the picture.

    The flowchart used to route the inside-baseline reading and both refusals into one
    node that said not to revert anything. The inside-baseline verdict may say that;
    the two refusals may not, so they cannot share its node.
    """
    targets = _dotted_edge_targets(_mermaid_flowchart())
    assert len(targets) == 3, f"expected three dotted edges, found {sorted(targets)}"
    baseline = [node for label, node in targets.items() if NO_ANOMALY_EDGE in label]
    refusals = [node for label, node in targets.items() if NO_ANOMALY_EDGE not in label]
    assert len(baseline) == 1 and len(refusals) == 2, sorted(targets)
    assert baseline[0] not in refusals, (
        "the inside-baseline verdict shares a node with a refusal, so the refusal "
        "inherits its 'nothing needs reverting'"
    )
    assert refusals[0] == refusals[1], "the two refusals are the same kind of answer"


def test_the_diagram_refusal_node_says_cannot_attribute_and_names_no_innocent():
    chart = _mermaid_flowchart()
    targets = _dotted_edge_targets(chart)
    refusal_node = next(node for label, node in targets.items() if NO_ANOMALY_EDGE not in label)
    definition = re.search(rf'\b{refusal_node}\["([^"]+)"\]', chart)
    assert definition, f"node {refusal_node} is never defined with a label"
    label = definition.group(1).replace("<br/>", " ").lower()
    assert "cannot attribute" in label
    assert "innocent" in label, "the refusal node has to say it clears nobody"
    assert not _violations(label)


# ------------------------------------------------------------- The video plan

def test_the_narration_and_the_cue_sheet_carry_the_same_words():
    """Both are generated from one list. If they differ, one was edited by hand."""
    narration = json.loads((REPO_ROOT / "video" / "narration.json").read_text(encoding="utf-8"))
    cue = json.loads((REPO_ROOT / "video" / "cue_sheet.json").read_text(encoding="utf-8"))
    spoken = {beat["beat_id"]: beat["narration_text"] for beat in narration["beats"]}
    cued = {beat["beat_id"]: beat["narration_text"] for beat in cue["beats"]}
    assert spoken == cued, "narration.json and cue_sheet.json disagree; rerun scripts/build_video_plan.py"
    assert narration["status"] == cue["status"]


def test_the_video_plan_uses_the_officially_allowed_android_tv_emulator_route():
    """The event FAQ permits Android TV Emulator and makes hardware optional."""
    for name in ("narration.json", "cue_sheet.json"):
        status = json.loads((REPO_ROOT / "video" / name).read_text(encoding="utf-8"))["status"]
        assert "android tv emulator" in status.lower()
        assert "does not require physical hardware" in status.lower()
