"""Tests that the written documentation matches the repository it describes.

Every finding in the audit that produced this suite was a documentation claim the
code did not support. These tests make that class of defect fail the build rather
than wait for a reader to notice.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT / "ci") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "ci"))

import readiness  # noqa: E402

README = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
BENCHMARKS = json.loads((REPO_ROOT / "benchmarks_summary.json").read_text(encoding="utf-8"))

def _tracked_markdown() -> list[Path]:
    """Markdown files git actually tracks, which is what a clone receives.

    Deriving this from ``git ls-files`` rather than from a filesystem glob keeps
    the collected test count identical in a clone and in a working checkout. That
    matters because the README badge and readiness gate G1 are both pinned to the
    collected count, and a count that depends on stray untracked files on one
    machine makes those checks unreliable.
    """
    try:
        result = subprocess.run(
            ["git", "ls-files", "*.md"],
            capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            return sorted(REPO_ROOT / line for line in result.stdout.splitlines() if line.strip())
    except Exception:
        pass
    # Outside a checkout, fall back to the tree so the tests still run.
    return sorted(
        p for p in REPO_ROOT.rglob("*.md")
        if ".git" not in p.parts and "node_modules" not in p.parts
    )


MARKDOWN_FILES = _tracked_markdown()


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
    assert "never been installed on a physical Fire TV Stick" in README
    assert "No Fire TV hardware was available" in build_doc


def test_documents_distinguish_the_built_apk_from_a_device_run():
    """The verified CI artifact must never be presented as Fire TV execution."""
    forbidden_phrasings = [
        "the apk is assembled by",
        "the apk builds in ci",
        "apk is uploaded as a downloadable artifact",
        "runs in github actions; the apk is uploaded",
    ]
    for path in MARKDOWN_FILES:
        lowered = " ".join(path.read_text(encoding="utf-8").split()).lower()
        for phrase in forbidden_phrasings:
            assert phrase not in lowered, (
                f"{path.name} claims the APK has been built: {phrase!r}"
            )

    build_doc = (REPO_ROOT / "docs" / "FIRE_TV_BUILD.md").read_text(encoding="utf-8").lower()
    readme_lower = README.lower()
    digest = "6c05dc46cdee7b6ecb49354e5ace06cd7de6913b517882e208acde8f6c296331"
    assert "35500282701" in build_doc
    assert digest in build_doc
    assert digest in readme_lower
    assert "device not run" in readme_lower or "no device run" in readme_lower
    assert "no fire tv device has connected" in (
        REPO_ROOT / "docs" / "PERSONA_REVIEW.md"
    ).read_text(encoding="utf-8").lower()


def test_the_android_workflow_exists_and_is_configured_to_fail_without_an_apk():
    """What can be verified without running it: that it is wired correctly."""
    workflow = (REPO_ROOT / ".github" / "workflows" / "android.yml").read_text(encoding="utf-8")
    assert "assembleDebug" in workflow
    assert "testDebugUnitTest" in workflow
    assert "if-no-files-found: error" in workflow


def test_no_document_claims_a_fire_tv_emulator_exists():
    """There is no Fire TV emulator, and three documents used to promise a run in one.

    Amazon's documentation says to test on an actual Fire TV device; the Vega Virtual
    Device runs Vega apps rather than this APK and needs macOS or Ubuntu. So every
    mention of a Fire TV emulator has to be a denial, the way every mention of Alexa is.
    """
    plan_files = [REPO_ROOT / "video" / name for name in ("narration.json", "cue_sheet.json")]
    for path in MARKDOWN_FILES + plan_files:
        text = " ".join(path.read_text(encoding="utf-8").split())
        for match in re.finditer(r"fire tv emulator|emulator image|official fire tv emulator", text, re.IGNORECASE):
            window = text[max(0, match.start() - 160):match.end() + 160].lower()
            denies = any(marker in window for marker in [
                "no fire tv emulator", "none exists", "does not exist", "there is no", "no emulator",
            ])
            assert denies, (
                f"{path.name} mentions a Fire TV emulator without saying none exists: "
                f"...{text[max(0, match.start() - 80):match.end() + 80]}..."
            )
    build_doc = (REPO_ROOT / "docs" / "FIRE_TV_BUILD.md").read_text(encoding="utf-8").lower()
    assert "no fire tv emulator exists" in build_doc
    assert "vega virtual device" in build_doc
    assert "actual fire tv device" in build_doc
    # And the surface is described as what it is: a D-pad and a screen.
    assert "d-pad" in build_doc and "no voice" in build_doc


def test_the_readme_states_the_limitation_beside_each_capability():
    limitations = README.split("## Known limitations")[-1]
    for required in ["No rollback dispatch has ever been fired", "APK built; no device run",
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
    "src/infrastructure/fixtures/commit_stream_fixture.json",
    "correlation_trial_summary.json",
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


def test_the_video_plan_claims_no_capability_the_repository_lacks():
    """The prose gates above read Markdown only, and the video plan is JSON.

    That gap let the shot plan keep describing an Alexa voice query, an Echo Show,
    Datadog, Jira and a spend figure nobody measured, months after those claims
    were removed from every Markdown file. This test scans the plan files as text
    so the same drift fails the build instead of shipping.
    """
    forbidden = ["alexa", "echo show", "datadog", "jira", "voice token", "elite tier"]
    for name in ["cue_sheet.json", "narration.json"]:
        lowered = (REPO_ROOT / "video" / name).read_text(encoding="utf-8").lower()
        for term in forbidden:
            assert term not in lowered, f"video/{name} describes {term!r}, which this repository has no implementation of"


def test_the_video_plan_and_shot_list_agree_and_fit_the_time_limit():
    """A beat list that outruns the limit is a plan for a rejected submission."""
    shot_list = (REPO_ROOT / "video" / "SHOT_LIST.md").read_text(encoding="utf-8")
    assert "PLAN ONLY" in shot_list, "the shot list does not declare itself a plan"
    assert "does not satisfy the Fire TV track's device requirement" in shot_list, \
        "the shot list must state that a browser recording is not a device run"

    cue = json.loads((REPO_ROOT / "video" / "cue_sheet.json").read_text(encoding="utf-8"))
    narration = json.loads((REPO_ROOT / "video" / "narration.json").read_text(encoding="utf-8"))

    assert cue["total_duration_sec"] <= cue["max_allowed_seconds"]
    assert [b["beat_id"] for b in cue["beats"]] == [b["beat_id"] for b in narration["beats"]], \
        "the cue sheet and the narration describe different beats"

    # Beats must tile the runtime with no gap and no overlap, because a plan whose
    # timings do not add up cannot be recorded from.
    previous_end = 0.0
    for beat in cue["beats"]:
        assert beat["timestamp_start"] == previous_end, f"{beat['beat_id']} does not start where the previous beat ended"
        previous_end = beat["timestamp_end"]
    assert previous_end == cue["total_duration_sec"]

    # words_count is generated from narration_text. If someone edits the text by
    # hand without rerunning the generator, this catches it.
    for beat in cue["beats"]:
        assert beat["words_count"] == len(beat["narration_text"].split()), \
            f"{beat['beat_id']} word count does not match its narration; rerun scripts/build_video_plan.py"


def test_no_fabricated_receipt_files_remain():
    for name in ["video_sync_receipt.json", "verification_receipt.json"]:
        assert not (REPO_ROOT / name).exists(), f"{name} attests something that did not happen"


# ------------------------------- Counted claims are counted by running them

def test_the_readme_spatial_nav_assertion_count_matches_the_spec_run():
    """The README quotes an assertion count. Run the spec and compare.

    This number is printed by the spec itself from ``cases.length``, so it moves
    whenever a case is added. Without this test it goes stale silently, which is
    exactly how it went stale once already.
    """
    claimed = re.findall(r"(\d+) assertions in `tests/e2e/spatial_nav_spec\.js`", README)
    assert claimed, "the README no longer states a spatial navigation assertion count"

    try:
        result = subprocess.run(
            ["node", "tests/e2e/spatial_nav_spec.js"],
            capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=60,
        )
    except (FileNotFoundError, OSError):
        pytest.skip("node is not installed, so the spec cannot be executed here")

    assert result.returncode == 0, f"the spatial navigation spec failed:\n{result.stdout}{result.stderr}"
    printed = re.search(r"(\d+)/(\d+) spatial navigation assertions passed", result.stdout)
    assert printed, f"the spec printed no assertion count:\n{result.stdout}"
    assert printed.group(1) == printed.group(2), f"{printed.group(0)}"
    for stated in claimed:
        assert stated == printed.group(2), \
            f"README says {stated} spatial navigation assertions, the spec runs {printed.group(2)}"


def test_the_readme_security_audit_check_count_matches_the_audit_run():
    """The README quotes a security-audit check count. Run the audit and compare."""
    claimed = re.search(r"`python scripts/security_audit\.py` runs (\d+) checks", README)
    assert claimed, "the README no longer states a security audit check count"

    env = dict(os.environ, MERCURY_ROLLBACK_SECRET="documentation-claim-test", MERCURY_OFFLINE="1")
    result = subprocess.run(
        [sys.executable, "scripts/security_audit.py"],
        capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=180, env=env,
    )
    assert result.returncode == 0, f"the security audit failed:\n{result.stdout}{result.stderr}"
    printed = re.search(r"all (\d+) checks passed", result.stdout)
    assert printed, f"the audit printed no check count:\n{result.stdout}"
    assert claimed.group(1) == printed.group(1), \
        f"README says {claimed.group(1)} security audit checks, the audit runs {printed.group(1)}"


def test_the_readme_coverage_numbers_match_the_recorded_measurement():
    """The README quotes a coverage percentage and a statement count. Pin both.

    These were the last unguarded numbers in the README, and they are the same
    defect class as the stale spatial-navigation and security-audit counts this
    suite already pins. The comparison is against coverage_summary.json rather
    than a live coverage run, because measuring coverage inside a test re-runs the
    whole suite and turns a fast check into a multi-minute one. CI regenerates
    that file with ``python scripts/record_coverage_summary.py --check``, so a
    drifted measurement fails the build there.
    """
    summary_path = REPO_ROOT / "coverage_summary.json"
    assert summary_path.exists(), (
        "coverage_summary.json is missing; run python scripts/record_coverage_summary.py"
    )
    recorded = json.loads(summary_path.read_text(encoding="utf-8"))

    badge = re.search(r"coverage-(\d+)%25-", README)
    assert badge, "the README no longer carries a coverage badge"
    stated = re.search(r"(\d+)% of (\d+) statements", README)
    assert stated, "the README no longer states a coverage percentage and statement count"

    assert int(stated.group(2)) == recorded["statements"], (
        f"README says {stated.group(2)} statements, the recorded run measured {recorded['statements']}"
    )
    assert int(stated.group(1)) == recorded["percent"], (
        f"README says {stated.group(1)}% coverage, the recorded run measured {recorded['percent']}%"
    )
    assert int(badge.group(1)) == recorded["percent"], (
        f"the coverage badge says {badge.group(1)}%, the recorded run measured {recorded['percent']}%"
    )


def test_the_recorded_coverage_clears_the_floor_the_ci_workflow_enforces():
    """A recorded number below the CI floor would mean the workflow could not pass."""
    recorded = json.loads((REPO_ROOT / "coverage_summary.json").read_text(encoding="utf-8"))
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    floor = re.search(r"--cov-fail-under=(\d+)", workflow)
    assert floor, "the CI workflow no longer enforces a coverage floor"
    assert recorded["percent"] >= int(floor.group(1)), (
        f"recorded coverage {recorded['percent']}% is below the CI floor of {floor.group(1)}%"
    )


def test_no_document_claims_the_rollback_dispatcher_has_been_fired():
    """A GitHub Actions dispatcher exists. No request has ever been sent.

    Same shape as the Alexa and APK pins above: the code is real, the execution
    is not, and no document may blur the two. Delete this test once a dispatch
    has actually run and there is a run to point at.
    """
    forbidden_phrasings = [
        "the rollback has been dispatched",
        "dispatches rollbacks to github actions today",
        "a rollback was dispatched",
        "fires the workflow",
    ]
    for path in MARKDOWN_FILES:
        lowered = " ".join(path.read_text(encoding="utf-8").split()).lower()
        for phrase in forbidden_phrasings:
            assert phrase not in lowered, f"{path.name} claims a dispatch happened: {phrase!r}"

    readme_lower = " ".join(README.split()).lower()
    assert "it has never been fired" in readme_lower
    assert "no request has ever been sent to github.com" in readme_lower


def test_the_readme_dispatcher_test_count_matches_the_module_it_names():
    """The README quotes a test count for the dispatcher. Count them."""
    claimed = re.search(
        r"the (\d+) tests in\s+`tests/unit/test_rollback_dispatcher\.py`", README, re.IGNORECASE)
    assert claimed, "the README no longer states a dispatcher test count"

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/unit/test_rollback_dispatcher.py",
         "--collect-only", "-q"],
        capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=300,
    )
    collected = re.search(r"(\d+)\s+tests?\s+collected", result.stdout)
    assert collected, f"could not read a collected count:\n{result.stdout[-500:]}"
    assert int(claimed.group(1)) == int(collected.group(1)), (
        f"README says {claimed.group(1)} dispatcher tests, pytest collects {collected.group(1)}"
    )


def test_the_readme_cleartext_claim_matches_the_manifests():
    """The README describes where cleartext is permitted. Read the files."""
    assert 'android:usesCleartextTraffic="false"' in README
    main_manifest = (REPO_ROOT / "app" / "src" / "main" / "AndroidManifest.xml").read_text(
        encoding="utf-8"
    )
    debug_manifest = (REPO_ROOT / "app" / "src" / "debug" / "AndroidManifest.xml").read_text(
        encoding="utf-8"
    )
    assert 'android:usesCleartextTraffic="false"' in main_manifest
    assert 'android:usesCleartextTraffic="true"' in debug_manifest
    assert "tools:replace" in debug_manifest


def test_the_buyer_section_declares_itself_a_hypothesis_and_invents_no_numbers():
    """The commercial section is the easiest place in a README to make things up.

    The rule it is held to is the one that was set for it: name the buyer, the
    budget line, the basis and the first calls, and state plainly that none of it
    has been tested. A price, a market size or a conversion rate would all be
    fabrications, so this test refuses them by shape rather than by review.
    """
    assert "## Who would buy this, and why" in README
    section = README.split("## Who would buy this, and why")[1].split("\n## ")[0]

    # Normalised, because a required sentence can be split across a wrap.
    lowered = " ".join(section.split()).lower()
    assert "commercial hypothesis, not a finding" in lowered
    assert "none of these has been contacted" in lowered
    for required in ["the buyer.", "the budget line.", "the willingness-to-pay basis."]:
        assert required in lowered, f"the section does not name {required!r}"

    forbidden = {
        r"[$€£]\s?\d": "a currency figure",
        r"\barr\b": "an ARR claim",
        r"\btam\b": "a market size",
        r"\d+\s?%": "a percentage",
        r"\bper (?:seat|user|host|month) (?:for|at) [$€£]": "a price",
    }
    for pattern, what in forbidden.items():
        found = re.search(pattern, section, re.IGNORECASE)
        assert not found, f"the buyer section states {what}: {found.group(0)!r}"


def test_the_readme_structural_test_count_matches_the_module_it_describes():
    """The Fire TV section quotes a count of structural tests. Count them."""
    claimed = re.search(r"checked by (\d+) structural tests", README)
    assert claimed, "the README no longer states a structural test count"

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/unit/test_firetv_app_structure.py",
         "--collect-only", "-q"],
        capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=300,
    )
    collected = re.search(r"(\d+)\s+tests?\s+collected", result.stdout)
    assert collected, f"could not read a collected count:\n{result.stdout[-500:]}"
    assert int(claimed.group(1)) == int(collected.group(1)), (
        f"README says {claimed.group(1)} structural tests, pytest collects {collected.group(1)}"
    )


def test_the_governance_overhead_percentage_is_the_arithmetic_of_the_recorded_run():
    """The one comparative number is derived. Derive it again from the same file.

    Its three inputs are already pinned to benchmarks_summary.json by the table
    test above. The percentage on top of them was not, which made it the one
    number in the README free to survive a re-benchmark unchanged.
    """
    stated = re.search(
        r"governance check costs ([\d.]+) ms mean over (\d+) cycles, against a ([\d.]+) ms mean "
        r"for the cheapest endpoint round trip measured in the same run\. Guarding the rollback "
        r"therefore adds ([\d.]+) percent",
        " ".join(README.split()),
    )
    assert stated, "the README no longer states the comparative number in the expected shape"

    governance = BENCHMARKS["results"]["governance_token_mint_and_verify"]
    endpoints = {name: stats for name, stats in BENCHMARKS["results"].items()
                 if name != "governance_token_mint_and_verify"}
    cheapest = min(stats["mean_ms"] for stats in endpoints.values())

    assert float(stated.group(1)) == pytest.approx(governance["mean_ms"], abs=0.0001)
    assert int(stated.group(2)) == governance["iterations"]
    assert float(stated.group(3)) == pytest.approx(cheapest, abs=0.01)
    assert float(stated.group(4)) == pytest.approx(
        governance["mean_ms"] / cheapest * 100.0, abs=0.01
    ), "the stated overhead is not the quotient of the two numbers beside it"


# ------------------------------------------ The suite's own runtime, which drifted

# This is the claim that did not reproduce. The README published "24.8 to 25.7
# seconds" for `python -m pytest tests/ -q`; three readers re-timed it on the machine
# it was measured on and every one of them landed 35 to 90 percent above that ceiling,
# because the number was typed when the suite was a third of its current size and
# nothing re-measured it afterwards. The same paragraph also carried a second, smaller
# figure that contradicted the first two lines above it.
#
# The runtime is now recorded by scripts/time_test_suite.py, exactly as the benchmark
# and coverage numbers are, and these tests compare the README against that record.
# Measuring inside a test would mean running the suite from inside the suite.

TIMING_PATH = REPO_ROOT / "suite_timing_summary.json"


def _live_prose(text: str) -> str:
    """The document with code fences and inline code removed, whitespace normalised.

    A figure inside backticks is a quotation. A figure in the prose is a claim. Only
    claims are checked against the recorded measurement, which is what lets the
    retired figures stay on the page as the record of a correction.
    """
    without_fences = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    return " ".join(re.sub(r"`[^`]*`", " ", without_fences).split())


def _timing() -> dict:
    """The recorded measurement, or a skip that says how to produce one.

    A skip rather than a failure, and only when the file is absent: the measuring
    script refuses to time a red suite, so a hard failure here would mean the record
    could never be created in the first place. Readiness gate G1 fails while the file
    is missing, which is where that absence is reported instead.
    """
    if not TIMING_PATH.exists():
        pytest.skip(
            "suite_timing_summary.json is missing. Run `python scripts/time_test_suite.py`; "
            "the README's Quickstart figure is compared against it."
        )
    return json.loads(TIMING_PATH.read_text(encoding="utf-8"))


def _session_low(session: dict) -> float:
    return min(v for k, v in session.items() if k.endswith("_min_seconds") and v is not None)


def _session_high(session: dict) -> float:
    return max(v for k, v in session.items() if k.endswith("_max_seconds") and v is not None)


def test_every_runtime_range_in_every_document_matches_the_recorded_measurement():
    """Every one of them, in every tracked document, not the first one in the README.

    The original defect was two paragraphs of the same README quoting different
    figures for the same command, so a test that checked one occurrence would have
    read straight past it. Whitespace is normalised first because both of the
    original claims were split across a line wrap.
    """
    recorded = _timing()
    allowed = {(recorded["min_seconds"], recorded["max_seconds"])}
    previous = recorded.get("previous_measurement")
    if previous:
        allowed.add((_session_low(previous), _session_high(previous)))

    seen = 0
    for path in MARKDOWN_FILES:
        text = _live_prose(path.read_text(encoding="utf-8"))
        for low, high in re.findall(r"(\d+(?:\.\d+)?) to (\d+(?:\.\d+)?) seconds", text):
            seen += 1
            assert (float(low), float(high)) in allowed, (
                f"{path.name} publishes {low} to {high} seconds for the test suite. The "
                f"recorded sessions are {sorted(allowed)}. Re-run "
                f"`python scripts/time_test_suite.py` and republish what it prints"
            )
    assert seen >= 2, (
        "the Quickstart and the timing section both have to carry the figure; "
        f"only {seen} runtime ranges were found across the tracked documents"
    )


def test_the_recorded_runtime_belongs_to_the_suite_this_repository_ships():
    """The pin that stops it drifting again.

    A runtime is a measurement of a particular suite. Add a test and the recorded
    figure describes a suite that no longer exists, so it must be re-measured rather
    than left to age the way the last one did.

    One exception, and it is the same one gate G1 makes: when the machine is too loaded
    to re-measure honestly, the README may keep the older record provided it says so in
    prose, naming the count the record was measured over, the count the suite collects
    now, and that a re-measure on an idle machine is pending. The phrases come from
    ``ci/readiness.py::stale_timing_disclosure`` so the two checks cannot drift apart,
    and the second phrase names the live count, so adding a test without updating the
    note still fails here.
    """
    recorded = _timing()
    badge = re.search(r"tests-(\d+)(?:%20|[\s_+-])*collected", README)
    assert badge, "the README has no test count badge"
    collected = int(badge.group(1))
    if recorded["tests_collected"] == collected:
        return
    prose = _live_prose(README)
    for phrase in readiness.stale_timing_disclosure(recorded["tests_collected"], collected):
        assert phrase in prose, (
            f"the runtime was measured over {recorded['tests_collected']} tests and this suite "
            f"now has {collected}. Re-run `python scripts/time_test_suite.py` on an idle "
            f"machine, or disclose the gap in the README with the exact phrase {phrase!r}"
        )


def test_the_stale_timing_disclosure_names_the_live_count_and_no_other():
    """The note is a pin, not a caveat: it has to carry the count the suite has today.

    And when the record is fresh, the note has to be gone. This test used to skip in
    that case, which made ``python -m pytest tests/ -q`` print ``506 passed, 1 skipped``
    against a README that said ``507 passed``: the one skip was this test, skipping by
    design on every healthy checkout. A fresh record with a stale-record disclosure
    still on the page is a real defect (the README would be apologising for a gap that
    closed), so that branch asserts instead of stepping aside, and the suite has no
    skip left that fires on a complete machine.
    """
    recorded = _timing()
    badge = re.search(r"tests-(\d+)(?:%20|[\s_+-])*collected", README)
    collected = int(badge.group(1))
    prose = _live_prose(README)
    pending = "re-measure on an idle machine is pending"
    if recorded["tests_collected"] == collected:
        assert pending not in prose, (
            "the runtime record matches the suite, yet the README still says a re-measure "
            "is pending; delete the stale-record disclosure"
        )
        for count in (collected - 1, collected + 1):
            stale = readiness.stale_timing_disclosure(recorded["tests_collected"], count)[1]
            assert stale not in prose, "the README names a count the suite does not have"
        return
    wrong = readiness.stale_timing_disclosure(recorded["tests_collected"], collected + 1)[1]
    assert wrong not in prose, "the README names a count the suite does not have"
    assert pending in prose


def test_every_passed_count_a_document_quotes_is_the_count_the_suite_records():
    """``# 507 passed`` beside the command is a claim about what the command prints.

    The badge pins the collected count, but the passed count printed after
    ``python -m pytest tests/ -q`` was quoted in three documents and pinned by nothing,
    which is how the README said 507 passed while the tree printed 506 passed and 1
    skipped. The record ``scripts/time_test_suite.py`` writes carries the passed and
    skipped counts of every timed run, so that is what the quotation is held to. A
    bootstrap record was measured over a red suite by the script's own definition, so
    only its collected count is trusted; a published record has to show every collected
    test passing and none skipped, or the annotation is not what the command prints.
    """
    recorded = _timing()
    badge = re.search(r"tests-(\d+)(?:%20|[\s_+-])*collected", README)
    collected = int(badge.group(1))
    assert recorded["tests_collected"] == collected or recorded["bootstrap"], (
        f"the runtime record was measured over {recorded['tests_collected']} tests and the "
        f"badge says {collected}; re-run `python scripts/time_test_suite.py`"
    )

    quoted = []
    for path in MARKDOWN_FILES:
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"python -m pytest tests/ -q[^\n]*?(?:#|,)\s*(\d+) passed", text):
            quoted.append((path.name, int(match.group(1))))
        for match in re.finditer(r"python -m pytest tests/ -q`?\s*\n\s*#\s*(\d+) passed", text):
            quoted.append((path.name, int(match.group(1))))
    assert len(quoted) >= 2, (
        f"expected the Quickstart and the test section to quote a passed count, found {quoted}"
    )

    if recorded["bootstrap"]:
        expected = collected
    else:
        assert recorded["tests_skipped"] == 0, (
            f"the recorded run skipped {recorded['tests_skipped']} tests, so the suite does not "
            f"print '{collected} passed'; the skip has to be removed or the documents changed"
        )
        assert recorded["tests_passed"] == collected, (
            f"the record says {recorded['tests_passed']} passed of {collected} collected"
        )
        expected = recorded["tests_passed"]
    for name, count in quoted:
        assert count == expected, f"{name} says {count} passed; the command prints {expected} passed"


def test_the_timing_record_says_what_it_timed_and_where():
    recorded = _timing()
    assert recorded["measured_by_command"] == "python scripts/time_test_suite.py"
    assert recorded["equivalent_command"] == "python -m pytest tests/ -q"
    assert recorded["measured_at_utc"]
    assert "CPython" in recorded["machine"], "the measurement machine is not named"
    assert "wall clock" in recorded["note"].lower()
    assert len(recorded["runs"]) >= 3, "a range needs at least three runs behind it"
    # Every run records its own exit code and failure count, and the record says
    # whether the suite was green while it was timed. That last flag cannot be
    # asserted here: the measuring script refuses to time a red suite, so a test
    # demanding a green record would be a test no record could ever satisfy after a
    # suite change. The refusal lives in scripts/time_test_suite.py, which is the only
    # place that can enforce it without deadlocking against itself.
    assert "bootstrap" in recorded, "the record does not say whether the suite was green"
    for run in recorded["runs"]:
        assert "exit_code" in run and "tests_failed" in run


def test_the_published_range_spans_more_than_one_named_condition():
    """A single-condition figure reads as a ceiling, and that is how this one failed.

    Three readers on three machine states got three different answers. So the record
    has to carry a loaded run as well as quiet ones, and the README has to name the
    machine, or the next reader with a browser open sees the same defect again.
    """
    recorded = _timing()
    conditions = {run["condition"] for run in recorded["runs"]}
    assert conditions == {"quiet", "loaded"}, (
        f"the record holds only {sorted(conditions)} runs; the published figure must span "
        "a condition where the machine was busy, measured rather than guessed"
    )
    assert recorded["machine"] in README, \
        "the README does not name the machine the runtime was measured on"
    assert "moves with machine load" in README, \
        "the README presents the runtime as a constant, which is what failed before"
    assert f"{recorded['loaded_max_seconds']} seconds" in README, (
        f"the README does not publish the loaded run at {recorded['loaded_max_seconds']} s, "
        "so the quiet range reads as a ceiling"
    )
    workers = max(run["background_cpu_workers"] for run in recorded["runs"]
                  if run["condition"] == "loaded")
    assert f"{workers} CPU-saturating background processes" in README, \
        "the README does not say how much background load produced the high figure"


def test_the_readme_publishes_how_its_own_runtime_moved_between_sessions():
    """The record keeps the session it replaced, and the README prints both.

    Replacing a figure that failed to reproduce with a fresh one and saying nothing
    is the same mistake in a newer coat. The measuring script therefore carries the
    previous session's headline forward into the file it writes, and this pins the
    README to it.
    """
    recorded = _timing()
    previous = recorded.get("previous_measurement")
    if not previous:
        pytest.skip("no earlier measurement session has been recorded yet")
    low, high = _session_low(previous), _session_high(previous)
    assert f"{low} to {high} seconds" in " ".join(README.split()), (
        f"the README does not say that the previous session measured {low} to {high} s. "
        "A number that is quietly re-rolled is indistinguishable from a number that was chosen."
    )


#: The figures that did not reproduce, and the clause that contradicted them two lines
#: later in the same paragraph. They may appear in the documentation only as quoted,
#: retired text, because deleting them silently would hide that the number moved.
RETIRED_TIMING_CLAIMS = ["24.8 to 25.7 seconds", "11 to 18 seconds"]


@pytest.mark.parametrize("stale", RETIRED_TIMING_CLAIMS)
def test_a_retired_timing_claim_is_quoted_as_retired_and_never_stated_as_live(stale):
    """Both halves matter.

    Quietly re-rolling a number that failed to reproduce is the failure mode this
    repository is trying not to have, so the old figure has to stay on the page. It
    also must not read as a live claim, so it may live only inside backticks, which
    is what ``_live_prose`` strips before any figure is checked.
    """
    for path in MARKDOWN_FILES:
        assert stale not in _live_prose(path.read_text(encoding="utf-8")), (
            f"{path.name} states the retired timing claim {stale!r} as though it were "
            "current. Quote it in backticks inside the retraction instead."
        )
    assert stale in README, (
        f"the README no longer records that it once published {stale!r}. The correction "
        "is part of the evidence, not something to tidy away."
    )


def test_the_readme_says_out_loud_that_its_timing_claim_failed_to_reproduce():
    retraction = README.lower()
    assert "did not reproduce" in retraction, \
        "the README does not admit that its published runtime failed to reproduce"
    assert "contradicted" in retraction, \
        "the README does not record that the same paragraph contradicted itself"


# ---------------------------------- Counts that describe a file, checked against it

def _denial_reasons() -> set[str]:
    source = (REPO_ROOT / "tests" / "integration" / "test_rollback_authorization.py").read_text(
        encoding="utf-8")
    return set(re.findall(r'denial_reason"\]\s*==\s*"(\w+)"', source))


def test_every_stated_denial_reason_count_matches_the_tests_that_assert_them():
    """Two documents said eight. The auditor counts nine, and so does this.

    The count is written in prose in two places and computed in a third, which is the
    arrangement that produced the drift. Now the prose is compared against the count.
    """
    counted = len(_denial_reasons())
    words = {8: "eight", 9: "nine", 10: "ten", 11: "eleven", 12: "twelve"}
    for path in MARKDOWN_FILES:
        text = path.read_text(encoding="utf-8")
        for stated in re.findall(r"(\d+|[a-z]+) (?:distinct |rollback )*denial reasons?", text):
            number = int(stated) if stated.isdigit() else \
                next((k for k, v in words.items() if v == stated), None)
            if number is None:
                continue
            assert number == counted, (
                f"{path.name} says {stated} denial reasons, "
                f"tests/integration/test_rollback_authorization.py asserts {counted}"
            )
    assert words[counted] in (REPO_ROOT / "docs" / "PERSONA_REVIEW.md").read_text(encoding="utf-8")


# ------------------------------------------- The persona review the I gates read

PERSONA_REVIEW = (REPO_ROOT / "docs" / "PERSONA_REVIEW.md").read_text(encoding="utf-8")


def _persona_finding_rows() -> list[list[str]]:
    rows = []
    for line in PERSONA_REVIEW.splitlines():
        if re.match(r"^\|\s*[PK][0-9]{2}-[0-9]+\s*\|", line) or re.match(r"^\|\s*K-[0-9]+\s*\|", line):
            rows.append([cell.strip() for cell in line.strip().strip("|").split("|")])
    return rows


def test_the_persona_review_counts_match_its_own_findings_table():
    """The document states how many findings it holds and how many failed. Count them."""
    rows = _persona_finding_rows()
    stated = re.search(r"\*\*(\d+) of the (\d+) findings are failures\*\*", PERSONA_REVIEW)
    assert stated, "the persona review no longer states its failure count"
    failures = [row for row in rows if row[3] == "FAIL"]
    assert int(stated.group(2)) == len(rows), \
        f"the document claims {stated.group(2)} findings and carries {len(rows)}"
    assert int(stated.group(1)) == len(failures), \
        f"the document claims {stated.group(1)} failures and carries {len(failures)}"


def test_the_persona_review_names_no_person_and_promises_no_endorsement():
    """The lenses are internal roles operated by the project team.

    Naming the real people the internal instrument anchors its lenses to would read,
    in a submitted repository, as a claim that those people reviewed this entry. None
    of them has seen it.
    """
    assert "Nobody from Amazon reviewed this repository" in PERSONA_REVIEW
    assert "They are not people" in PERSONA_REVIEW
    titles = ["Sr. UX Designer", "Sr. Recruiting Manager", "Bar Raiser"]
    for title in titles:
        assert title not in PERSONA_REVIEW, \
            f"the persona review carries {title!r}, which belongs to a real person"


def test_the_persona_review_admits_what_it_could_not_close():
    open_questions = PERSONA_REVIEW.split("## 4. What this review did not answer")[1]
    for expected in ["APK", "television", "deployment of this commit"]:
        assert expected in open_questions, \
            f"the review no longer records {expected!r} as an open question"


def test_no_document_commits_the_workspace_coordination_file():
    """The protocol forbids it, and the point of the restatement is that it is not needed."""
    assert not (REPO_ROOT / "STATE.md").exists(), \
        "a workspace coordination file has been committed into this repository"
    assert not (REPO_ROOT / "LOG.md").exists()


def test_the_readme_points_a_clone_at_the_review_the_gates_read():
    """Evidence a reader cannot find is evidence a reader does not have.

    The whole point of restating the review inside the repository is that somebody
    holding only a clone can check the four gates that depend on it, so the README
    has to name the file.
    """
    assert "docs/PERSONA_REVIEW.md" in README,         "the README does not tell a reader where the persona review lives"
    assert "in a clone" in README.lower() or "from a bare clone" in README.lower(),         "the README does not say that the readiness score is now reproducible from a clone"

