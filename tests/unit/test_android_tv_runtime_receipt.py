import zipfile

import pytest

from scripts.write_android_tv_runtime_receipt import REQUIRED_EVENTS, build_receipt


def evidence(tmp_path):
    apk = tmp_path / "app-debug.apk"
    with zipfile.ZipFile(apk, "w") as archive:
        archive.writestr("AndroidManifest.xml", b"compiled")
        archive.writestr("classes.dex", b"x" * 100)
    logcat = tmp_path / "logcat.txt"
    endpoint = "https://candidate.example/"
    logcat.write_text(endpoint + "\n" + "\n".join(REQUIRED_EVENTS), encoding="utf-8")
    screenshot = tmp_path / "final.png"
    screenshot.write_bytes(b"png" + b"x" * 10_001)
    return apk, logcat, screenshot, endpoint


def test_receipt_requires_every_runtime_event_and_records_apk_digest(tmp_path):
    apk, logcat, screenshot, endpoint = evidence(tmp_path)
    install = tmp_path / "install.txt"
    install.write_text("Success\n", encoding="utf-8")
    launch = tmp_path / "launch.txt"
    launch.write_text("Events injected: 1\n", encoding="utf-8")
    receipt = build_receipt(
        apk, logcat, screenshot, endpoint, "a" * 40, "Android TV", "Android 11",
        install, launch, "https://github.com/example/repo/actions/runs/1", "runtime-artifact",
    )
    assert receipt["remote_journey"]["events"] == list(REQUIRED_EVENTS)
    assert len(receipt["apk_sha256"]) == 64
    assert receipt["endpoint_loaded_without_intent_override"] == endpoint
    assert receipt["artifacts"]["screenshot"]["bytes"] > 10_000
    assert receipt["workflow_run_url"].endswith("/1")


def test_receipt_refuses_missing_journey_event(tmp_path):
    apk, logcat, screenshot, endpoint = evidence(tmp_path)
    logcat.write_text(endpoint + "\n" + REQUIRED_EVENTS[0], encoding="utf-8")
    with pytest.raises(ValueError, match="missing required journey events"):
        build_receipt(apk, logcat, screenshot, endpoint, "abc", "Android TV", "Android 11")
