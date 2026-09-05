"""Tests that the written documentation matches the repository it describes.

Every finding in the audit that produced this suite was a documentation claim the
code did not support. These tests make that class of defect fail the build rather
than wait for a reader to notice.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
README = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
BENCHMARKS = json.loads((REPO_ROOT / "benchmarks_summary.json").read_text(encoding="utf-8"))

MARKDOWN_FILES = [
    p for p in REPO_ROOT.rglob("*.md")
    if ".git" not in p.parts and "node_modules" not in p.parts
]


# ------------------------------------------------ Numbers match their source

def _readme_benchmark_rows() -> dict[str, tuple[int, float, float]]:
    rows = {}
    for line in README.splitlines():
        match = re.match(
            r"\|\s*`?([\w ]+?)`?\s*\|\s*(\d+)\s*\|\s*([\d.]+) ms\s*\|\s*([\d.]+) ms\s*\|", line)
        if match:
            rows[match.group(1).strip()] = (int(match.group(2)), float(match.group(3)), float(match.group(4)))
    return rows


@pytest.mark.parametrize("endpoint", list(BENCHMARKS["results"]))
def test_every_measured_endpoint_appears_in_the_readme(endpoint):
    label = "Governance mint and verify" if endpoint == "governance_token_mint_and_verify" else endpoint
    assert label in README, f"{endpoint} was measured but is not reported in the README"


def test_readme_benchmark_numbers_match_the_recorded_measurement():
    """A number in the README must equal the number the command produced."""
    rows = _readme_benchmark_rows()
    assert rows, "no benchmark table found in the README"

    for endpoint, stats in BENCHMARKS["results"].items():
        label = "Governance mint and verify" if endpoint == "governance_token_mint_and_verify" else endpoint
        assert label in rows, f"{label} missing from the README benchmark table"
        iterations, mean_ms, p95_ms = rows[label]
        assert iterations == stats["iterations"]
        assert mean_ms == pytest.approx(stats["mean_ms"], abs=0.01), \
            f"README says {label} mean is {mean_ms} ms, the measurement says {stats['mean_ms']}"
        assert p95_ms == pytest.approx(stats["p95_ms"], abs=0.01), \
            f"README says {label} p95 is {p95_ms} ms, the measurement says {stats['p95_ms']}"


def test_the_benchmark_file_records_how_it_was_produced():
    assert BENCHMARKS["measured_by_command"] == "python scripts/benchmark_suite.py"
    assert BENCHMARKS["measured_at_utc"]
    assert BENCHMARKS["data_mode"], "the run must record the data mode it observed"
    assert "excludes network transit" in BENCHMARKS["note"].lower()


def test_the_readme_test_count_matches_what_pytest_collects():
    match = re.search(r"tests-(\d+)(?:%20|[\s_+-])*collected", README)
    assert match, "the README has no test count badge"
    claimed = int(match.group(1))

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests", "--collect-only", "-q"],
        capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=300,
    )
    collected = re.search(r"(\d+)\s+tests?\s+collected", result.stdout)
    assert collected, f"could not read a collected count from pytest:\n{result.stdout[-500:]}"
    assert claimed == int(collected.group(1)), \
        f"README badge says {claimed}, pytest collects {collected.group(1)}"


def test_every_command_the_readme_cites_exists():
    for command in re.findall(r"`(python (?:scripts|ci|-m)[^`]*)`", README):
        parts = command.split()
        if parts[1] == "-m":
            continue
        assert (REPO_ROOT / parts[1]).exists(), f"README cites {parts[1]}, which does not exist"


# ------------------------------------------- Claims match the code that ships

def test_no_document_claims_an_alexa_integration_that_does_not_exist():
    """There is no Alexa skill in this repository, so nothing may imply one."""
    source_files = list((REPO_ROOT / "src").rglob("*.py")) + list((REPO_ROOT / "app").rglob("*.kt"))
    implements_alexa = any(
        "alexa" in path.read_text(encoding="utf-8").lower() for path in source_files
    )
    assert not implements_alexa, "if Alexa is implemented, relax this test"

    for path in MARKDOWN_FILES:
        # Compare against the surrounding sentence rather than the surrounding
        # line, because a denial can be split across a wrap.
        text = " ".join(path.read_text(encoding="utf-8").split())
        for match in re.finditer(r"alexa", text, re.IGNORECASE):
            window = text[max(0, match.start() - 140):match.end() + 140].lower()
            denies = any(marker in window for marker in
                         ["no alexa", "not", "never", "there is no", "without", "absent"])
            assert denies, (
                f"{path.name} mentions Alexa without saying it is absent: "
                f"...{text[max(0, match.start() - 60):match.end() + 60]}..."
            )


def test_no_document_claims_a_device_run_that_did_not_happen():
    build_doc = (REPO_ROOT / "docs" / "FIRE_TV_BUILD.md").read_text(encoding="utf-8")
    assert "Not run" in build_doc
    assert "JAVA_HOME is not set" in build_doc, "the verbatim local build error must be recorded"
    assert "has never been installed on a Fire TV device" in README \
        or "never been installed on Fire TV" in README


def test_the_readme_states_the_limitation_beside_each_capability():
    limitations = README.split("## Known limitations")[-1]
    for required in ["No deployment pipeline integration", "No device run",
                     "Cost Explorer lags", "browser speech synthesis", "In-memory state"]:
        assert required in limitations, f"the limitations section does not mention {required!r}"


# --------------------------------------------------- Prose quality gates

@pytest.mark.parametrize("path", MARKDOWN_FILES, ids=lambda p: p.name)
def test_no_em_dashes_in_documentation(path):
    text = path.read_text(encoding="utf-8")
    count = text.count("—")
    assert count == 0, f"{path.name} contains {count} em dashes"


@pytest.mark.parametrize("path", MARKDOWN_FILES, ids=lambda p: p.name)
def test_no_ai_filler_in_documentation(path):
    banned = [
        "seamless", "leverage", "cutting-edge", "revolutionary", "effortless",
        "world-class", "best-in-class", "state-of-the-art", "unlock the power",
        "harness the power", "delve into", "tapestry", "testament to", "supercharge",
        "game-changing", "frictionless", "turnkey", "synergy",
    ]
    lowered = path.read_text(encoding="utf-8").lower()
    found = [word for word in banned if word in lowered]
    assert not found, f"{path.name} contains filler: {found}"


def test_the_readme_never_claims_conformity():
    for word in ["compliant", "conformity"]:
        assert word not in README.lower(), f"the README claims {word!r}, which nobody has established"


# -------------------------------------------------- Fixtures declare themselves

@pytest.mark.parametrize("fixture_path", [
    "src/infrastructure/fixtures/github_telemetry_fixture.json",
    "src/infrastructure/fixtures/aws_cost_fixture.json",
    "deploy_teardown_receipt.json",
    "benchmarks_summary.json",
])
def test_every_committed_data_artifact_declares_its_origin(fixture_path):
    data = json.loads((REPO_ROOT / fixture_path).read_text(encoding="utf-8"))
    origin_fields = {"note", "recorded_by_command", "measured_by_command", "recorded_at_utc", "schema"}
    assert origin_fields & set(data), f"{fixture_path} does not say where it came from"


def test_the_video_directory_does_not_attest_a_video():
    video_readme = (REPO_ROOT / "video" / "README.md").read_text(encoding="utf-8")
    assert "No video has been recorded" in video_readme
    assert not (REPO_ROOT / "video" / "subtitles.srt").exists(), \
        "a subtitle file asserts timing against a picture that does not exist"
    assert not (REPO_ROOT / "video" / "subtitles.vtt").exists()
    for name in ["cue_sheet.json", "narration.json"]:
        data = json.loads((REPO_ROOT / "video" / name).read_text(encoding="utf-8"))
        assert "PLAN ONLY" in data.get("status", ""), f"{name} does not declare itself a plan"


def test_no_fabricated_receipt_files_remain():
    for name in ["video_sync_receipt.json", "verification_receipt.json"]:
        assert not (REPO_ROOT / name).exists(), f"{name} attests something that did not happen"
