"""Tests for the readiness auditor's own predicates.

A gate that cannot fail is not a gate, and a gate nobody tested is a gate nobody knows
can fail. J4 is the one that matters most here: Mercury is entered in the Fire TV track,
so J4 is the gate that decides whether the sponsor product is load-bearing, and until
2026-09-08 it passed on ``'LEANBACK_LAUNCHER' in manifest`` while the README two screens
away said no APK had ever been built. It was the one gate in the file that could not fail
on the axis it exists to test, and it contributed a PASS to a published 46/53.

These drive every branch of the predicate with fixtures, including both accepted runtime
routes: a physical Fire TV receipt and the Android TV Emulator receipt allowed by the
event's official FAQ.
"""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT / "ci") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "ci"))

import readiness  # noqa: E402

LEANBACK_MANIFEST = '<category android:name="android.intent.category.LEANBACK_LAUNCHER" />'
README_TERMS = ["fire tv", "leanback"]

COMPLETE_RECEIPT = {
    "built_by_command": "./gradlew assembleRelease",
    "gradle_exit_code": 0,
    "apk_path": "README.md",  # any file that exists; the gate only checks it is there
    "apk_sha256": "0" * 64,
    "device_run": {
        "device_model": "Fire TV Stick 4K Max (2nd gen)",
        "fire_os_or_android_version": "Fire OS 8.0",
        "adb_install_exit_code": 0,
        "launched_at_utc": "2026-09-08T10:00:00Z",
        "observed": "The wallboard rendered and the D-pad moved the focus ring across the tiles.",
    },
}

COMPLETE_EMULATOR_RECEIPT = {
    "schema": "mercury.android_tv_runtime_receipt/1",
    "recorded_at_utc": "2026-09-23T10:00:00Z",
    "build_sha": "a" * 40,
    "workflow_run_url": "https://github.com/upgradedev/mercury_amazon/actions/runs/1",
    "artifact_name": "mercury-android-tv-runtime-" + "a" * 40,
    "built_by_command": "./gradlew :app:assembleDebug -PmercuryCockpitUrl=https://example.test/",
    "apk_path": "app/build/outputs/apk/debug/app-debug.apk",
    "apk_sha256": "b" * 64,
    "adb_install_exit_code": 0,
    "normal_launcher": "monkey LEANBACK_LAUNCHER; no COCKPIT_URL intent extra",
    "endpoint_loaded_without_intent_override": "https://example.test/",
    "endpoint_health_build_sha": "a" * 40,
    "runtime": {"device_model": "Android TV", "os_version": "Android 11 / API 30"},
    "remote_journey": {
        "input": "ADB keyevents mapped to the Android TV D-pad",
        "events": sorted(readiness.ANDROID_TV_REQUIRED_EVENTS),
        "external_effect": "NONE; record-only fixture journey",
    },
    "artifacts": {
        name: {"path": name, "sha256": char * 64, "bytes": 10000}
        for name, char in (
            ("apk", "b"),
            ("logcat", "d"),
            ("screenshot", "e"),
            ("install_log", "f"),
            ("launch_log", "1"),
            ("endpoint_health", "2"),
        )
    },
}

COMPLETE_TERRAFORM_CYCLE_RECEIPT = {
    "schema": "mercury.terraform_cycle_receipt/2",
    "source_revision": "a" * 40,
    "workflow_run_url": "https://github.com/upgradedev/mercury_amazon/actions/runs/1",
    "execution_mode": "github_actions_pipeline",
    "environment": "ci-1-1",
    "production_url_destroyed": False,
    "lambda_package": {"sha256": "b" * 64, "bytes": 1000},
    "pre_destroy": {
        "root_http_status": 200,
        "health_http_status": 200,
        "health_build_sha": "a" * 40,
        "health_durable_state": True,
        "function_policy_statements": [
            "FunctionURLAllowPublicAccess",
            "FunctionURLAllowInvokeAction",
        ],
    },
    "destroy": {
        "terraform_exit_code": 0,
        "post_destroy_url_http_status": 403,
        "lambda_absent": True,
        "dynamodb_absent": True,
        "iam_role_absent": True,
        "iam_policy_absent": True,
        "cloudwatch_log_group_absent": True,
        "terraform_state_empty": True,
        "teardown_verified": True,
    },
    "error": None,
    "passed": True,
}


def _exists(path: str) -> bool:
    return (REPO_ROOT / path).is_file()


def test_a_complete_receipt_passes_the_gate():
    passed, message = readiness.evaluate_firetv_gate(
        README_TERMS, LEANBACK_MANIFEST, COMPLETE_RECEIPT, _exists)
    assert passed is True
    assert "Fire TV Stick 4K Max" in message
    assert "assembleRelease" in message


def test_a_complete_android_tv_emulator_receipt_passes_the_gate():
    passed, message = readiness.evaluate_firetv_gate(
        README_TERMS, LEANBACK_MANIFEST, COMPLETE_EMULATOR_RECEIPT, _exists)
    assert passed is True
    assert "Android TV" in message
    assert "via D-pad" in message


def test_invalid_android_receipt_does_not_shadow_valid_physical_receipt():
    passed, message = readiness.evaluate_firetv_receipt_candidates(
        README_TERMS,
        LEANBACK_MANIFEST,
        [
            (readiness.ANDROID_TV_RUNTIME_RECEIPT, "{not-json"),
            (readiness.FIRETV_BUILD_RECEIPT, json.dumps(COMPLETE_RECEIPT)),
        ],
        _exists,
        checkout_validator=lambda _receipt: None,
    )
    assert passed is True
    assert readiness.FIRETV_BUILD_RECEIPT in message


def test_both_invalid_runtime_routes_report_both_rejection_reasons():
    passed, message = readiness.evaluate_firetv_receipt_candidates(
        README_TERMS,
        LEANBACK_MANIFEST,
        [
            (readiness.ANDROID_TV_RUNTIME_RECEIPT, "{not-json"),
            (readiness.FIRETV_BUILD_RECEIPT, json.dumps({"gradle_exit_code": 1})),
        ],
        _exists,
        checkout_validator=lambda _receipt: None,
    )
    assert passed is False
    assert readiness.ANDROID_TV_RUNTIME_RECEIPT in message
    assert readiness.FIRETV_BUILD_RECEIPT in message


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        (
            lambda receipt: receipt.update(
                workflow_run_url="https://github.com/example/other/actions/runs/1"
            ),
            "mercury_amazon",
        ),
        (lambda receipt: receipt.update(artifact_name="runtime-without-revision"), "artifact_name"),
        (lambda receipt: receipt.update(apk_sha256="9" * 64), "artifacts.apk.sha256"),
        (lambda receipt: receipt["artifacts"].pop("launch_log"), "launch_log"),
    ],
)
def test_android_receipt_binds_repository_revision_and_runtime_artifacts(mutation, expected):
    receipt = copy.deepcopy(COMPLETE_EMULATOR_RECEIPT)
    mutation(receipt)
    passed, message = readiness.evaluate_firetv_gate(
        README_TERMS, LEANBACK_MANIFEST, receipt, _exists
    )
    assert passed is False
    assert expected in message


def test_the_runtime_receipt_in_this_repository_is_real_evidence():
    """The landed artifact validates against its immutable recorded source.

    Current-checkout freshness is verified independently below; a new wrapper
    must never inherit a historical journey's current-pass claim.
    """
    path = REPO_ROOT / readiness.ANDROID_TV_RUNTIME_RECEIPT
    assert path.is_file(), "the landed runtime receipt is missing"
    receipt = json.loads(path.read_text(encoding="utf-8"))
    assert receipt.get("schema") == "mercury.android_tv_runtime_receipt/1"
    for field in readiness.ANDROID_TV_RECEIPT_FIELDS:
        assert receipt.get(field) not in (None, "", []), f"receipt {field} missing"
    events = set(receipt["remote_journey"]["events"])
    assert readiness.ANDROID_TV_REQUIRED_EVENTS <= events
    assert receipt["endpoint_health_build_sha"] == receipt["build_sha"]
    assert receipt["artifacts"]["apk"]["sha256"] == receipt["apk_sha256"]
    assert receipt["build_sha"] in receipt["artifact_name"]
    assert receipt["workflow_run_url"].removeprefix(
        "https://github.com/upgradedev/mercury_amazon/actions/runs/"
    ).isdigit()
    passed, message = readiness.evaluate_firetv_gate(
        README_TERMS, LEANBACK_MANIFEST, receipt, _exists)
    assert passed is True, message
    def validates_recorded_source(recorded):
        return readiness.runtime_receipt_checkout_problem(
            recorded, checkout_ref=recorded["build_sha"]
        )

    problem = validates_recorded_source(receipt)
    assert problem is None, f"receipt does not validate against its recorded source: {problem}"
    audited, audited_message = readiness.evaluate_firetv_receipt_candidates(
        README_TERMS, LEANBACK_MANIFEST,
        [(readiness.ANDROID_TV_RUNTIME_RECEIPT, json.dumps(receipt))],
        _exists,
        checkout_validator=validates_recorded_source,
    )
    assert audited is True, audited_message


def test_a_leanback_manifest_alone_no_longer_passes():
    """The exact input that used to pass: the two strings and nothing else."""
    passed, _ = readiness.evaluate_firetv_gate(README_TERMS, LEANBACK_MANIFEST, {}, _exists)
    assert passed is False


def test_complete_disposable_actions_cycle_passes_d2_predicate():
    passed, message = readiness.evaluate_terraform_cycle_receipt(
        COMPLETE_TERRAFORM_CYCLE_RECEIPT
    )
    assert passed is True
    assert "deployed and destroyed" in message


@pytest.mark.parametrize(
    ("path", "value", "expected"),
    [
        (("execution_mode",), "local_manual", "github_actions_pipeline"),
        (("production_url_destroyed",), True, "production URL"),
        (("pre_destroy", "health_build_sha"), "c" * 40, "source_revision"),
        (("destroy", "terraform_exit_code"), 1, "destroy did not exit 0"),
        (("destroy", "lambda_absent"), False, "lambda_absent"),
        (("destroy", "iam_policy_absent"), False, "iam_policy_absent"),
        (("destroy", "terraform_state_empty"), False, "terraform_state_empty"),
    ],
)
def test_d2_refuses_incomplete_or_non_pipeline_cycle(path, value, expected):
    receipt = copy.deepcopy(COMPLETE_TERRAFORM_CYCLE_RECEIPT)
    target = receipt
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    passed, message = readiness.evaluate_terraform_cycle_receipt(receipt)
    assert passed is False
    assert expected in message


@pytest.mark.parametrize("field", sorted(readiness.FIRETV_RECEIPT_FIELDS))
def test_every_missing_top_level_field_fails_the_gate(field):
    receipt = copy.deepcopy(COMPLETE_RECEIPT)
    receipt.pop(field)
    passed, message = readiness.evaluate_firetv_gate(
        README_TERMS, LEANBACK_MANIFEST, receipt, _exists)
    assert passed is False, f"the gate passed with {field} missing"
    assert field in message


@pytest.mark.parametrize("field", sorted(readiness.FIRETV_DEVICE_FIELDS))
def test_every_missing_device_field_fails_the_gate(field):
    receipt = copy.deepcopy(COMPLETE_RECEIPT)
    receipt["device_run"].pop(field)
    passed, message = readiness.evaluate_firetv_gate(
        README_TERMS, LEANBACK_MANIFEST, receipt, _exists)
    assert passed is False, f"the gate passed with device_run.{field} missing"
    assert field in message


def test_a_failed_gradle_run_is_not_a_build():
    receipt = copy.deepcopy(COMPLETE_RECEIPT)
    receipt["gradle_exit_code"] = 1
    passed, message = readiness.evaluate_firetv_gate(
        README_TERMS, LEANBACK_MANIFEST, receipt, _exists)
    assert passed is False
    assert "gradle exited 1" in message


def test_a_failed_install_is_not_a_device_run():
    receipt = copy.deepcopy(COMPLETE_RECEIPT)
    receipt["device_run"]["adb_install_exit_code"] = 1
    passed, message = readiness.evaluate_firetv_gate(
        README_TERMS, LEANBACK_MANIFEST, receipt, _exists)
    assert passed is False
    assert "never installed" in message


def test_a_receipt_naming_an_apk_that_is_not_there_fails():
    """The receipt is a claim about a file. The gate checks the file."""
    receipt = copy.deepcopy(COMPLETE_RECEIPT)
    receipt["apk_path"] = "app/build/outputs/apk/release/app-release.apk"
    passed, message = readiness.evaluate_firetv_gate(
        README_TERMS, LEANBACK_MANIFEST, receipt, _exists)
    assert passed is False
    assert "is not a file in this checkout" in message


def test_the_manifest_and_readme_are_still_necessary():
    passed, message = readiness.evaluate_firetv_gate([], LEANBACK_MANIFEST, COMPLETE_RECEIPT, _exists)
    assert passed is False and "never names Fire TV" in message

    passed, message = readiness.evaluate_firetv_gate(README_TERMS, "", COMPLETE_RECEIPT, _exists)
    assert passed is False and "LEANBACK_LAUNCHER" in message


def test_the_gate_is_exempt_from_the_ci_exit_code_and_says_why():
    """An honest FAIL must not turn the build red, and must not hide either."""
    assert "J4" in readiness.CI_EXEMPT
    reason = readiness.CI_EXEMPT["J4"]
    assert "official FAQ" in reason and "Android TV" in reason


def test_the_audit_reports_j4_for_the_actual_receipt_freshness():
    """A historical journey passes only while its runtime files are unchanged."""
    receipt = json.loads(
        (REPO_ROOT / readiness.ANDROID_TV_RUNTIME_RECEIPT).read_text(encoding="utf-8")
    )
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", receipt["build_sha"], "HEAD"],
        cwd=REPO_ROOT, check=True, capture_output=True, text=True,
    )
    changed = subprocess.run(
        ["git", "diff", "--name-only", f"{receipt['build_sha']}..HEAD",
         "--", *readiness.ANDROID_TV_RUNTIME_PATHS],
        cwd=REPO_ROOT, check=True, capture_output=True, text=True,
    )
    changed_paths = changed.stdout.splitlines()
    results = {r.gate_id: r for r in readiness.audit_project()}
    assert "J4" in results
    j4 = results["J4"]
    assert j4.passed is (not changed_paths), j4.message
    if changed_paths:
        for path in changed_paths:
            assert path in j4.message
    else:
        assert receipt["workflow_run_url"] in j4.message


def test_a_receipt_from_before_the_page_change_still_fails_naming_the_file():
    """The 2026-10-01 invalidation, pinned without waiting for the next drift.

    Rewind the receipt independently of whether the current checkout is fresh
    or stale, so rejection remains tested across releases. Rewinding its build to 69aa972, the build the
    2026-09-30 receipt was written from, replays the exact failure: the
    candidate page moved after that build, so the gate must fail and name
    docs/index.html rather than pass on a journey the receipt never saw.
    """
    path = REPO_ROOT / readiness.ANDROID_TV_RUNTIME_RECEIPT
    receipt = json.loads(path.read_text(encoding="utf-8"))
    receipt["build_sha"] = "69aa9728fdb1a3e8089376b061884a6e0b5235ea"
    receipt["endpoint_health_build_sha"] = receipt["build_sha"]
    receipt["artifact_name"] = "mercury-android-tv-runtime-" + receipt["build_sha"]
    problem = readiness.runtime_receipt_checkout_problem(receipt)
    assert problem is not None and "docs/index.html" in problem
    audited, audited_message = readiness.evaluate_firetv_receipt_candidates(
        README_TERMS, LEANBACK_MANIFEST,
        [(readiness.ANDROID_TV_RUNTIME_RECEIPT, json.dumps(receipt))],
        _exists,
    )
    assert audited is False and "docs/index.html" in audited_message


def test_the_readme_publishes_the_score_the_auditor_prints():
    """The lower number goes in the README, not the number before the gate was fixed."""
    result = subprocess.run(
        [sys.executable, "ci/readiness.py"],
        capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=600,
    )
    import re

    printed = re.search(r"SUMMARY: (\d+)/(\d+) PASSED", result.stdout)
    assert printed, f"the auditor printed no summary line:\n{result.stdout[-2000:]}"
    readme = (REPO_ROOT / "docs" / "EVIDENCE.md").read_text(encoding="utf-8")
    quoted = re.search(r"(\d+)\s*/\s*53 readiness gates", readme)
    assert quoted, "docs/EVIDENCE.md no longer quotes a readiness score"
    assert int(quoted.group(1)) == int(printed.group(1)), (
        f"the README claims {quoted.group(1)}/53, the auditor printed {printed.group(1)}/53"
    )
    assert int(printed.group(2)) == 53


# ------------------------------------------ G1: a runtime record older than the suite

def test_the_stale_timing_disclosure_names_both_counts_and_nothing_vaguer():
    """The README may keep a runtime record that predates the suite only by saying so
    in two exact phrases: the count the record was measured over, and the count the
    suite collects now with a re-measure pending. Both carry a number, so a note that
    says 'roughly current' cannot satisfy the gate, and the second changes with the
    live count, so adding a test without updating the note fails the gate again."""
    recorded, live = readiness.stale_timing_disclosure(440, 505)
    assert recorded == "measured over 440 collected tests"
    assert live == "the suite now collects 505 tests and a re-measure on an idle machine is pending"
    assert readiness.stale_timing_disclosure(440, 506)[1] != live
    assert readiness.stale_timing_disclosure(441, 505)[0] != recorded


def test_the_receipt_shape_is_documented_where_a_reader_will_look():
    """The gate names a file. Somebody has to be told what to put in it."""
    doc = (REPO_ROOT / "docs" / "FIRE_TV_BUILD.md").read_text(encoding="utf-8")
    assert readiness.FIRETV_BUILD_RECEIPT in doc
    assert readiness.ANDROID_TV_RUNTIME_RECEIPT in doc
    for field in readiness.ANDROID_TV_RECEIPT_FIELDS:
        assert field in doc, f"docs/FIRE_TV_BUILD.md does not say what {field} is"
    # The document has to carry a copyable skeleton, not a prose description of one.
    block = doc.split("```json")[1].split("```")[0] if "```json" in doc else ""
    assert block, "no JSON skeleton for the receipt in docs/FIRE_TV_BUILD.md"
    skeleton = json.loads(block)
    assert set(readiness.ANDROID_TV_RECEIPT_FIELDS) <= set(skeleton)


# ------------------------------------------------------------ I1 to I4: the review

# A minimal document that satisfies all four gates. Every test below removes exactly
# one thing from it and asserts which gate goes red, which is the only way to know the
# gates are checking what their titles say they check.
COMPLETE_REVIEW = """# Persona review

Review date: 2026-09-08

| Step | What it asks | Outcome | Evidence |
|---|---|---|---|
| 1 | Does a deployed endpoint answer? | PARTIAL | `python ci/readiness.py` |
| 2 | What is owner-gated and unmet? | OPEN | `python ci/readiness.py` |
| 3 | Is the track written down? | PASS | `README.md` |
| 4 | Do the surfaces match the code? | PASS | `tests/e2e/test_documentation_claims.py` |

| Lens | Owner | What it decides | Verdict |
|---|---|---|---|
| Sponsor product owner | maintainer, product row | Is the sponsor product load-bearing? | FAIL |
| UX designer | maintainer, interface row | Can a cold visitor use it? | PASS |
| Recruiter | maintainer, engineering bar row | Does it clear an engineering bar? | PASS |

| ID | Lens | Finding | Verdict | Evidence |
|---|---|---|---|---|
| P01-1 | Sponsor product owner | No APK exists | FAIL | `docs/FIRE_TV_BUILD.md` |
| P06-1 | UX designer | The hero action is marked | PASS | `docs/index.html` |
| P06-2 | UX designer | No control is disabled unexplained | PASS | `docs/index.html` |
| P08-1 | Recruiter | No em dashes in the prose | PASS | `tests/e2e/test_documentation_claims.py` |
| P08-2 | Recruiter | The domain imports no SDK | PASS | `python ci/readiness.py` |
"""


def _review(text: str = COMPLETE_REVIEW) -> dict[str, tuple[bool, str]]:
    return readiness.evaluate_persona_review_gates(text, _exists)


def test_a_complete_review_passes_all_four_gates():
    outcomes = _review()
    assert [gid for gid, (passed, _) in outcomes.items() if not passed] == []
    assert "2026-09-08" in outcomes["I4"][1]
    assert "Sponsor product owner FAIL" in outcomes["I2"][1]


def test_the_gates_read_the_document_this_repository_ships():
    """The gates must point at a file a clone receives, not at a workspace file."""
    assert readiness.PERSONA_REVIEW_DOC == "docs/PERSONA_REVIEW.md"
    assert (REPO_ROOT / readiness.PERSONA_REVIEW_DOC).is_file()
    for gate_id in ("I1", "I2", "I3", "I4"):
        assert gate_id not in readiness.CI_EXEMPT, (
            f"{gate_id} reads a file inside this repository now, so it must be able to "
            "fail the build rather than sit on the exemption list"
        )


def test_the_audit_reports_all_four_as_passing_from_inside_the_repository():
    """End to end, and with no external-evidence marker on any of the four."""
    results = {r.gate_id: r for r in readiness.audit_project()}
    for gate_id in ("I1", "I2", "I3", "I4"):
        assert results[gate_id].passed is True, results[gate_id].message
        assert results[gate_id].external_evidence is False, (
            f"{gate_id} still claims evidence from outside this repository"
        )
        assert readiness.PERSONA_REVIEW_DOC in results[gate_id].message


def test_a_missing_document_fails_all_four():
    outcomes = _review("")
    assert all(not passed for passed, _ in outcomes.values())
    assert all("is missing" in message for _, message in outcomes.values())


def test_fewer_than_four_procedure_steps_fails_i1():
    trimmed = COMPLETE_REVIEW.replace(
        "| 4 | Do the surfaces match the code? | PASS | `tests/e2e/test_documentation_claims.py` |\n", "")
    outcomes = _review(trimmed)
    assert outcomes["I1"][0] is False
    assert "3 procedure steps" in outcomes["I1"][1]


def test_a_procedure_step_with_no_outcome_fails_i1():
    outcomes = _review(COMPLETE_REVIEW.replace(
        "| 3 | Is the track written down? | PASS |", "| 3 | Is the track written down? |  |"))
    assert outcomes["I1"][0] is False
    assert "no outcome or no evidence" in outcomes["I1"][1]


def test_an_invented_verdict_is_not_a_verdict():
    outcomes = _review(COMPLETE_REVIEW.replace(
        "| 1 | Does a deployed endpoint answer? | PARTIAL |",
        "| 1 | Does a deployed endpoint answer? | LOOKS FINE |"))
    assert outcomes["I1"][0] is False


@pytest.mark.parametrize("lens", readiness.PERSONA_LENSES)
def test_dropping_any_lens_fails_i2(lens):
    outcomes = _review("\n".join(
        line for line in COMPLETE_REVIEW.splitlines() if not line.startswith(f"| {lens} |")))
    assert outcomes["I2"][0] is False, f"{lens} could be deleted without failing I2"
    assert lens in outcomes["I2"][1]


def test_a_lens_with_no_finding_of_its_own_fails_i2():
    """A verdict in the ownership table with nothing behind it is not a review."""
    outcomes = _review("\n".join(
        line for line in COMPLETE_REVIEW.splitlines() if not line.startswith("| P01-1 |")))
    assert outcomes["I2"][0] is False
    assert "Sponsor product owner" in outcomes["I2"][1]


def test_a_finding_attributed_to_a_lens_nobody_owns_fails_i3():
    outcomes = _review(COMPLETE_REVIEW + (
        "| P99-1 | Passing Stranger | Something | PASS | `README.md` |\n"))
    assert outcomes["I3"][0] is False
    assert "Passing Stranger" in outcomes["I3"][1]


def test_an_empty_owner_cell_fails_i3():
    outcomes = _review(COMPLETE_REVIEW.replace("| UX designer | maintainer, interface row |",
                                               "| UX designer |  |"))
    assert outcomes["I3"][0] is False


def test_fewer_than_five_findings_fails_i4():
    outcomes = _review("\n".join(
        line for line in COMPLETE_REVIEW.splitlines() if not line.startswith("| P08-2 |")))
    assert outcomes["I4"][0] is False
    assert "records 4 findings" in outcomes["I4"][1]


def test_an_undated_review_fails_i4():
    outcomes = _review(COMPLETE_REVIEW.replace("Review date: 2026-09-08", ""))
    assert outcomes["I4"][0] is False
    assert "no review date" in outcomes["I4"][1]


def test_a_finding_citing_a_file_that_is_not_there_fails_i4():
    """The citation is a claim about a file. The gate opens the file."""
    outcomes = _review(COMPLETE_REVIEW.replace(
        "| P08-2 | Recruiter | The domain imports no SDK | PASS | `python ci/readiness.py` |",
        "| P08-2 | Recruiter | The domain imports no SDK | PASS | `tests/unit/test_nothing.py` |"))
    assert outcomes["I4"][0] is False
    assert "tests/unit/test_nothing.py" in outcomes["I4"][1]


def test_a_finding_with_no_evidence_at_all_fails_i4():
    outcomes = _review(COMPLETE_REVIEW.replace(
        "| P06-1 | UX designer | The hero action is marked | PASS | `docs/index.html` |",
        "| P06-1 | UX designer | The hero action is marked | PASS |  |"))
    assert outcomes["I4"][0] is False
    assert "P06-1" in outcomes["I4"][1]


def test_the_gates_do_not_reproduce_the_internal_instrument():
    """The review instrument is a workspace document and is not part of a submission.

    A gate that string-matched its filename would also be pressuring whoever writes the
    repository-local restatement to paste that filename in to satisfy the match. Neither
    the auditor nor the shipped document may carry it.
    """
    auditor = (REPO_ROOT / "ci" / "readiness.py").read_text(encoding="utf-8")
    document = (REPO_ROOT / readiness.PERSONA_REVIEW_DOC).read_text(encoding="utf-8")
    for internal in ("00-RUNBOOK.md", "00-ROSTER.md"):
        assert internal not in auditor, f"the auditor names the internal instrument {internal}"
        assert internal not in document, f"the shipped review names the internal instrument {internal}"


def test_the_shipped_review_claims_no_endorsement():
    """The lenses are internal roles. A reader must not be able to read them as judges."""
    document = (REPO_ROOT / readiness.PERSONA_REVIEW_DOC).read_text(encoding="utf-8")
    assert "Nobody from Amazon reviewed this repository" in document
    assert "They are not people" in document


def test_the_gates_no_longer_read_anything_above_this_repository():
    """The defect these gates carried was the path, not the predicate.

    They read a coordination file two directories up, so they passed on the machine that
    had it and failed for anyone holding only a clone. Nothing in the auditor may climb
    out of the checkout for I-section evidence again.
    """
    auditor = (REPO_ROOT / "ci" / "readiness.py").read_text(encoding="utf-8")
    section = auditor.split("I: Personas review instrument")[1].split("O: Owner-gated")[0]
    assert ".." not in section, "the I gates read a path outside this repository again"
    assert "STATE.md" not in section


# ----------------- G2: a deployed ancestor with no runtime change is live


def _git_run(monkeypatch, *, ancestor=True, changed=()):
    import subprocess as stdlib_subprocess

    def fake_run(cmd, **kwargs):
        if cmd[:3] == ["git", "merge-base", "--is-ancestor"]:
            return stdlib_subprocess.CompletedProcess(cmd, 0 if ancestor else 1, "", "")
        if cmd[:2] == ["git", "diff"]:
            out = "\n".join(changed) + ("\n" if changed else "")
            return stdlib_subprocess.CompletedProcess(cmd, 0, out, "")
        if cmd[:2] == ["git", "rev-parse"]:
            return stdlib_subprocess.CompletedProcess(cmd, 0, "f" * 40 + "\n", "")
        raise AssertionError(f"unexpected git call in test: {cmd}")

    monkeypatch.setattr(readiness.subprocess, "run", fake_run)


def test_g2_passes_when_only_non_runtime_files_moved_after_the_deploy(monkeypatch):
    """The commit-SHA trap: a receipt committed after its deploy must stay green.

    Committing the receipt moves HEAD, so deployed == HEAD can never hold on a
    committed tree. G2 passes when the deployed SHA is an ancestor whose live
    runtime files are unchanged since; docs, tests and receipts do not move it.
    """
    _git_run(monkeypatch, ancestor=True, changed=())

    assert readiness.deployed_checkout_problem("a" * 40) is None


def test_g2_fails_naming_the_runtime_files_that_moved_after_the_deploy(monkeypatch):
    _git_run(monkeypatch, ancestor=True, changed=("src/domain/x.py", "docs/index.html"))

    problem = readiness.deployed_checkout_problem("a" * 40)

    assert problem is not None
    assert "src/domain/x.py" in problem and "docs/index.html" in problem


def test_g2_fails_when_the_deployed_build_left_history(monkeypatch):
    _git_run(monkeypatch, ancestor=False)

    problem = readiness.deployed_checkout_problem("a" * 40)

    assert problem is not None and "not an ancestor" in problem


# ---------------------------------- G2: a receipt without a deployed build SHA

def test_g2_blames_the_deployed_endpoint_by_url_and_not_the_local_health_route():
    """The previous wording, "The deployment does not report a build SHA from /health",
    read as a defect in this checkout, whose /health does report one. The gate has to
    name the deployed URL from the receipt and say the older build is what lacks the field.
    """
    receipt = json.loads((REPO_ROOT / "deploy_teardown_receipt.json").read_text(encoding="utf-8"))
    message = {r.gate_id: r for r in readiness.audit_project()}["G2"].message
    if receipt.get("deployed_commit_sha"):
        # A receipt that carries the SHA takes the other branch, where G2 is judged on
        # the equality alone and the wording under test is unreachable.
        assert "older build" not in message
        return
    from fastapi.testclient import TestClient

    from src.interfaces.mcp_server import app

    assert "build_sha" in TestClient(app).get("/health").json(), (
        "the local /health no longer reports build_sha, so the wording under test would be false"
    )
    assert receipt["base_url"] in message, "G2 does not name the deployed URL it probed"
    assert "older build" in message and "deployed endpoint" in message.lower()
    assert "this checkout does report build_sha" in message
    assert "The deployment does not report a build SHA from /health" not in message
