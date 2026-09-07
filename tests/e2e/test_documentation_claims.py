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


def test_no_document_claims_the_apk_has_been_built():
    """The Android workflow is configured and has never executed.

    Until a push produces a run, no document may imply an APK exists or that a
    reader can download one today. This test is the pin on that claim, in the
    same shape as the Alexa one. Delete it once a run exists.
    """
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
    assert "never executed" in build_doc
    assert "zero runs" in build_doc
    readme_lower = README.lower()
    assert "has never executed" in readme_lower
    assert "no apk exists" in readme_lower


def test_the_android_workflow_exists_and_is_configured_to_fail_without_an_apk():
    """What can be verified without running it: that it is wired correctly."""
    workflow = (REPO_ROOT / ".github" / "workflows" / "android.yml").read_text(encoding="utf-8")
    assert "assembleDebug" in workflow
    assert "testDebugUnitTest" in workflow
    assert "if-no-files-found: error" in workflow


def test_the_readme_states_the_limitation_beside_each_capability():
    limitations = README.split("## Known limitations")[-1]
    for required in ["No rollback dispatch has ever been fired", "No APK and no device run",
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
