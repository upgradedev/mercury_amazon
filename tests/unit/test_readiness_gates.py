"""Tests for the readiness auditor's own predicates.

A gate that cannot fail is not a gate, and a gate nobody tested is a gate nobody knows
can fail. J4 is the one that matters most here: Mercury is entered in the Fire TV track,
so J4 is the gate that decides whether the sponsor product is load-bearing, and until
2026-09-08 it passed on ``'LEANBACK_LAUNCHER' in manifest`` while the README two screens
away said no APK had ever been built. It was the one gate in the file that could not fail
on the axis it exists to test, and it contributed a PASS to a published 45/53.

These drive every branch of the rewritten predicate with fixtures, including the branch
that passes, which cannot be reached in this checkout because no APK exists. Building
one needs a JDK, an Android SDK and a Fire TV device, and none is installed here, so the
passing case is proved against an injected receipt rather than faked into the repository.
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


def _exists(path: str) -> bool:
    return (REPO_ROOT / path).is_file()


def test_a_complete_receipt_passes_the_gate():
    passed, message = readiness.evaluate_firetv_gate(
        README_TERMS, LEANBACK_MANIFEST, COMPLETE_RECEIPT, _exists)
    assert passed is True
    assert "Fire TV Stick 4K Max" in message
    assert "assembleRelease" in message


def test_the_gate_fails_in_this_repository_because_no_apk_exists():
    """The honest FAIL, asserted against the real checkout rather than a fixture."""
    receipt_path = REPO_ROOT / readiness.FIRETV_BUILD_RECEIPT
    assert not receipt_path.exists(), (
        f"{readiness.FIRETV_BUILD_RECEIPT} now exists. If a real APK was built and run, this "
        "test should assert the receipt's contents; it must not be written by hand to turn "
        "the gate green."
    )
    passed, message = readiness.evaluate_firetv_gate(
        README_TERMS, LEANBACK_MANIFEST, None, _exists)
    assert passed is False
    assert readiness.FIRETV_BUILD_RECEIPT in message
    assert "not a Fire TV app" in message


def test_a_leanback_manifest_alone_no_longer_passes():
    """The exact input that used to pass: the two strings and nothing else."""
    passed, _ = readiness.evaluate_firetv_gate(README_TERMS, LEANBACK_MANIFEST, {}, _exists)
    assert passed is False


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
    assert "Android SDK" in reason and "Fire TV" in reason


def test_the_audit_reports_j4_as_failing_in_this_checkout():
    """End to end: run the auditor and read J4 out of its own results."""
    results = {r.gate_id: r for r in readiness.audit_project()}
    assert "J4" in results
    assert results["J4"].passed is False
    assert readiness.FIRETV_BUILD_RECEIPT in results["J4"].message


def test_the_readme_publishes_the_score_the_auditor_prints():
    """The lower number goes in the README, not the number before the gate was fixed."""
    result = subprocess.run(
        [sys.executable, "ci/readiness.py"],
        capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=600,
    )
    import re

    printed = re.search(r"SUMMARY: (\d+)/(\d+) PASSED", result.stdout)
    assert printed, f"the auditor printed no summary line:\n{result.stdout[-2000:]}"
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    quoted = re.search(r"(\d+)\s*/\s*53 readiness gates", readme)
    assert quoted, "the README no longer quotes a readiness score"
    assert int(quoted.group(1)) == int(printed.group(1)), (
        f"the README claims {quoted.group(1)}/53, the auditor printed {printed.group(1)}/53"
    )
    assert int(printed.group(2)) == 53


def test_the_receipt_shape_is_documented_where_a_reader_will_look():
    """The gate names a file. Somebody has to be told what to put in it."""
    doc = (REPO_ROOT / "docs" / "FIRE_TV_BUILD.md").read_text(encoding="utf-8")
    assert readiness.FIRETV_BUILD_RECEIPT in doc
    for field in readiness.FIRETV_RECEIPT_FIELDS:
        assert field in doc, f"docs/FIRE_TV_BUILD.md does not say what {field} is"
    # The document has to carry a copyable skeleton, not a prose description of one.
    block = doc.split("```json")[1].split("```")[0] if "```json" in doc else ""
    assert block, "no JSON skeleton for the receipt in docs/FIRE_TV_BUILD.md"
    skeleton = json.loads(block)
    assert set(readiness.FIRETV_RECEIPT_FIELDS) <= set(skeleton)
