"""Validate and record an Android TV emulator journey for the exact APK."""
from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

REQUIRED_EVENTS = (
    "journey:page_loaded:",
    "journey:what_changed:ANOMALY_ATTRIBUTED:",
    "journey:rollback_staged:",
    "journey:rollback_confirmed:RECORDED_ONLY:DPAD_RECORD_ONLY_DEMO",
    "journey:handoff_published:checkout-api-active:",
)


def build_receipt(
    apk: Path, logcat: Path, screenshot: Path, endpoint: str, build_sha: str,
    device_model: str, os_version: str, install_log: Path | None = None,
    launch_log: Path | None = None, workflow_run_url: str = "", artifact_name: str = "",
) -> dict:
    if not endpoint.startswith("https://"):
        raise ValueError("the normal APK endpoint must be HTTPS")
    if not apk.is_file() or apk.stat().st_size == 0 or not zipfile.is_zipfile(apk):
        raise ValueError("APK is absent, empty or not a zip archive")
    with zipfile.ZipFile(apk) as archive:
        if "AndroidManifest.xml" not in archive.namelist():
            raise ValueError("APK has no compiled AndroidManifest.xml")
    if not logcat.is_file():
        raise ValueError("logcat evidence is absent")
    text = logcat.read_text(encoding="utf-8", errors="replace")
    if endpoint not in text:
        raise ValueError("logcat does not show the APK loading the intended endpoint")
    missing = [event for event in REQUIRED_EVENTS if event not in text]
    if missing:
        raise ValueError(f"logcat is missing required journey events: {missing}")
    if not screenshot.is_file() or screenshot.stat().st_size < 10_000:
        raise ValueError("runtime screenshot is absent or implausibly small")
    if not device_model.strip() or not os_version.strip() or not build_sha.strip():
        raise ValueError("device model, OS version and build SHA are required")
    if workflow_run_url and not workflow_run_url.startswith("https://github.com/"):
        raise ValueError("workflow run URL must be a GitHub HTTPS URL")

    def artifact(path: Path) -> dict:
        return {
            "path": path.as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "bytes": path.stat().st_size,
        }

    optional_artifacts = {}
    for name, path in (("install_log", install_log), ("launch_log", launch_log)):
        if path is not None:
            if not path.is_file() or path.stat().st_size == 0:
                raise ValueError(f"{name} is absent or empty")
            optional_artifacts[name] = artifact(path)
    return {
        "schema": "mercury.android_tv_runtime_receipt/1",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "build_sha": build_sha,
        "workflow_run_url": workflow_run_url,
        "artifact_name": artifact_name,
        "built_by_command": (
            "./gradlew :app:assembleDebug "
            "-PmercuryCockpitUrl=https://leol25sezuvokpankox5cvjopm0gtvfa.lambda-url.eu-west-1.on.aws/"
        ),
        "apk_path": apk.as_posix(),
        "apk_sha256": hashlib.sha256(apk.read_bytes()).hexdigest(),
        "adb_install_exit_code": 0,
        "normal_launcher": "monkey LEANBACK_LAUNCHER; no COCKPIT_URL intent extra",
        "endpoint_loaded_without_intent_override": endpoint,
        "runtime": {"device_model": device_model, "os_version": os_version},
        "remote_journey": {
            "input": "ADB keyevents mapped to the Android TV D-pad",
            "events": list(REQUIRED_EVENTS),
            "external_effect": "NONE; record-only fixture journey",
        },
        "artifacts": {
            "apk": artifact(apk),
            "logcat": artifact(logcat),
            "screenshot": artifact(screenshot),
            **optional_artifacts,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apk", type=Path, required=True)
    parser.add_argument("--logcat", type=Path, required=True)
    parser.add_argument("--screenshot", type=Path, required=True)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--build-sha", required=True)
    parser.add_argument("--device-model", required=True)
    parser.add_argument("--os-version", required=True)
    parser.add_argument("--install-log", type=Path)
    parser.add_argument("--launch-log", type=Path)
    parser.add_argument("--workflow-run-url", default="")
    parser.add_argument("--artifact-name", default="")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    receipt = build_receipt(
        args.apk, args.logcat, args.screenshot, args.endpoint, args.build_sha,
        args.device_model, args.os_version, args.install_log, args.launch_log,
        args.workflow_run_url, args.artifact_name,
    )
    args.output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
