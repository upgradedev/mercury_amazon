"""Tests for the script that writes the Fire TV build receipt gate J4 reads.

The receipt is the one file in this repository that turns the sponsor-product gate
green, so the thing to prove about the script that writes it is every way it refuses.
Each test below runs against a throwaway checkout under ``tmp_path``; none of them
touches the real repository root, and the last test asserts that the real root still
has no receipt, because producing one needs an APK and a Fire TV that this machine
does not have.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
for entry in ("scripts", "ci"):
    if str(REPO_ROOT / entry) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT / entry))

import readiness  # noqa: E402
import write_firetv_receipt as receipt_script  # noqa: E402

APK_RELATIVE = Path("app/build/outputs/apk/debug/app-debug.apk")


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    """A throwaway repository root holding a real zip archive where the APK would be."""
    apk = tmp_path / APK_RELATIVE
    apk.parent.mkdir(parents=True)
    with zipfile.ZipFile(apk, "w") as archive:
        archive.writestr("AndroidManifest.xml", "<manifest/>")
        archive.writestr("classes.dex", b"\x00" * 64)
    return tmp_path


def _argv(checkout: Path, **overrides: object) -> list[str]:
    values: dict[str, object] = {
        "gradle-exit-code": 0,
        "apk": str(APK_RELATIVE),
        "built-by-command": "./gradlew :app:assembleDebug",
        "device-model": "Fire TV Stick 4K Max (2nd gen)",
        "os-version": "Fire OS 8.1.0.3",
        "adb-install-exit-code": 0,
        "observed": "The wallboard rendered and the D-pad moved the focus ring across the tiles.",
        "repo-root": str(checkout),
    }
    values.update(overrides)
    argv: list[str] = []
    for flag, value in values.items():
        if value is None:
            continue
        argv += [f"--{flag}", str(value)]
    return argv


def _receipt_path(checkout: Path) -> Path:
    return checkout / readiness.FIRETV_BUILD_RECEIPT


def _exists_in(checkout: Path):
    return lambda path: (checkout / path).is_file()


# ------------------------------------------------------------------ It writes

def test_a_real_build_and_launch_produce_a_receipt_the_gate_accepts(checkout, capsys):
    assert receipt_script.main(_argv(checkout)) == 0
    written = json.loads(_receipt_path(checkout).read_text(encoding="utf-8"))

    passed, message = readiness.evaluate_firetv_gate(
        ["fire tv"], "LEANBACK_LAUNCHER", written, _exists_in(checkout))
    assert passed is True, message
    assert "Fire TV Stick 4K Max" in message

    assert written["schema"] == receipt_script.RECEIPT_SCHEMA
    assert written["recorded_by_command"] == "python scripts/write_firetv_receipt.py"
    assert written["apk_path"] == APK_RELATIVE.as_posix()
    assert written["gradle_exit_code"] == 0
    assert written["device_run"]["adb_install_exit_code"] == 0
    assert set(readiness.FIRETV_RECEIPT_FIELDS) <= set(written)
    assert set(readiness.FIRETV_DEVICE_FIELDS) <= set(written["device_run"])
    # The script prints what it wrote, so the owner sees the receipt in the terminal.
    assert written["apk_sha256"] in capsys.readouterr().out


def test_the_digest_is_computed_from_the_file_and_never_typed(checkout):
    receipt_script.main(_argv(checkout))
    written = json.loads(_receipt_path(checkout).read_text(encoding="utf-8"))
    expected = hashlib.sha256((checkout / APK_RELATIVE).read_bytes()).hexdigest()
    assert written["apk_sha256"] == expected
    # There is no flag to supply a digest: a typed digest is a claim, not a measurement.
    assert "--apk-sha256" not in receipt_script.parse_args.__code__.co_consts
    with pytest.raises(SystemExit):
        receipt_script.parse_args(_argv(checkout) + ["--apk-sha256", "0" * 64])


def test_a_dry_run_prints_the_receipt_and_writes_nothing(checkout, capsys):
    assert receipt_script.main(_argv(checkout) + ["--dry-run"]) == 0
    assert not _receipt_path(checkout).exists()
    captured = capsys.readouterr()
    assert json.loads(captured.out)["apk_path"] == APK_RELATIVE.as_posix()
    assert "nothing written" in captured.err


def test_the_adb_launch_output_is_attached_verbatim_when_given(checkout, tmp_path):
    log = tmp_path / "launch.log"
    log.write_text("Starting: Intent { cmp=com.amazon.mercury.wallboard/.MainActivity }\n", encoding="utf-8")
    assert receipt_script.main(_argv(checkout) + ["--adb-launch-output", str(log)]) == 0
    written = json.loads(_receipt_path(checkout).read_text(encoding="utf-8"))
    assert "MainActivity" in written["device_run"]["adb_launch_output"]


def test_an_explicit_launch_time_is_kept(checkout):
    assert receipt_script.main(_argv(checkout, **{"launched-at-utc": "2026-09-08T10:00:00Z"})) == 0
    written = json.loads(_receipt_path(checkout).read_text(encoding="utf-8"))
    assert written["device_run"]["launched_at_utc"] == "2026-09-08T10:00:00Z"


# ----------------------------------------------------------------- It refuses

@pytest.mark.parametrize("override, expected", [
    ({"gradle-exit-code": 1}, "gradle exited 1"),
    ({"adb-install-exit-code": 1}, "adb install exited 1"),
    ({"observed": "   "}, "--observed is empty"),
    ({"device-model": ""}, "--device-model is empty"),
    ({"os-version": ""}, "--os-version is empty"),
    ({"built-by-command": ""}, "--built-by-command is empty"),
    ({"launched-at-utc": "yesterday"}, "not an ISO-8601 timestamp"),
])
def test_missing_evidence_is_refused_and_nothing_is_written(checkout, capsys, override, expected):
    assert receipt_script.main(_argv(checkout, **override)) == receipt_script.REFUSED
    assert not _receipt_path(checkout).exists()
    err = capsys.readouterr().err
    assert "refused" in err and expected in err
    assert "Nothing was written" in err


def test_no_apk_file_means_no_receipt(checkout, capsys):
    (checkout / APK_RELATIVE).unlink()
    assert receipt_script.main(_argv(checkout)) == receipt_script.REFUSED
    assert not _receipt_path(checkout).exists()
    assert "no APK at" in capsys.readouterr().err


def test_an_empty_file_is_not_an_apk(checkout, capsys):
    (checkout / APK_RELATIVE).write_bytes(b"")
    assert receipt_script.main(_argv(checkout)) == receipt_script.REFUSED
    assert not _receipt_path(checkout).exists()
    assert "is empty" in capsys.readouterr().err


def test_a_file_that_is_not_a_zip_archive_is_not_an_apk(checkout, capsys):
    (checkout / APK_RELATIVE).write_text("this is a text file wearing an apk extension", encoding="utf-8")
    assert receipt_script.main(_argv(checkout)) == receipt_script.REFUSED
    assert not _receipt_path(checkout).exists()
    assert "does not start with a zip header" in capsys.readouterr().err


def test_a_zip_archive_without_a_manifest_is_not_an_apk(checkout, capsys):
    """A zip with the right name and the right first bytes is still not an APK."""
    with zipfile.ZipFile(checkout / APK_RELATIVE, "w") as archive:
        archive.writestr("README.txt", "a zip archive wearing an apk extension")
    assert receipt_script.main(_argv(checkout)) == receipt_script.REFUSED
    assert not _receipt_path(checkout).exists()
    assert "no AndroidManifest.xml inside" in capsys.readouterr().err


def test_an_apk_outside_the_checkout_is_refused(checkout, tmp_path_factory, capsys):
    elsewhere = tmp_path_factory.mktemp("elsewhere") / "app-debug.apk"
    with zipfile.ZipFile(elsewhere, "w") as archive:
        archive.writestr("AndroidManifest.xml", "<manifest/>")
    assert receipt_script.main(_argv(checkout, apk=str(elsewhere))) == receipt_script.REFUSED
    assert not _receipt_path(checkout).exists()
    assert "outside the checkout" in capsys.readouterr().err


def test_an_unreadable_launch_log_is_refused(checkout, tmp_path, capsys):
    missing = tmp_path / "does-not-exist.log"
    assert receipt_script.main(_argv(checkout) + ["--adb-launch-output", str(missing)]) == receipt_script.REFUSED
    assert not _receipt_path(checkout).exists()
    assert "cannot read --adb-launch-output" in capsys.readouterr().err


def test_the_receipt_is_checked_against_the_gate_before_it_is_written(checkout, monkeypatch):
    """Belt and braces: if the gate would refuse the receipt, the script refuses to write it."""
    monkeypatch.setattr(readiness, "evaluate_firetv_gate", lambda *args: (False, "gate says no"))
    with pytest.raises(receipt_script.ReceiptRefused, match="would not pass gate J4"):
        receipt_script.build_receipt(
            gradle_exit_code=0, apk=checkout / APK_RELATIVE, built_by_command="./gradlew :app:assembleDebug",
            device_model="Fire TV Stick", os_version="Fire OS 8", adb_install_exit_code=0,
            observed="It rendered.", repo_root=checkout,
        )
    assert not _receipt_path(checkout).exists()


# ---------------------------------------------------------- The command line

def test_the_command_line_refuses_with_exit_two(checkout):
    """The CLI wiring, run as an owner would run it, on a checkout with no APK."""
    (checkout / APK_RELATIVE).unlink()
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "write_firetv_receipt.py"), *_argv(checkout)],
        capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=120,
    )
    assert result.returncode == receipt_script.REFUSED, result.stderr
    assert "refused: no APK at" in result.stderr
    assert not _receipt_path(checkout).exists()


def test_the_real_checkout_still_has_no_receipt():
    """A CI artifact and local download must not fabricate a device receipt."""
    assert not (REPO_ROOT / readiness.FIRETV_BUILD_RECEIPT).exists()


# ---------------------------------------------------------------- The workflow

def test_the_android_workflow_builds_on_every_push_and_on_demand():
    """The workflow has to run on the first push, whatever that push touches.

    A paths filter could let a documentation-only release commit skip the exact-SHA APK
    build, so there is none. The digest step is what the receipt records for the APK the
    run produced.
    """
    workflow = (REPO_ROOT / ".github" / "workflows" / "android.yml").read_text(encoding="utf-8")
    on_block = workflow.split("\non:")[1].split("\njobs:")[0]
    assert "push:" in on_block and "workflow_dispatch:" in on_block
    assert "paths:" not in on_block, "a paths filter can skip the first push"
    assert ":app:assembleDebug" in workflow
    assert "sha256sum app/build/outputs/apk/debug/app-debug.apk" in workflow
    assert "path: app/build/outputs/apk/debug/app-debug.apk" in workflow
    assert "if-no-files-found: error" in workflow
    assert "write_firetv_receipt.py" in workflow, "the workflow has to point the owner at the receipt step"
