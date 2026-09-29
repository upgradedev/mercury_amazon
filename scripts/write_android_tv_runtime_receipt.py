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
    built_by_command: str = "", endpoint_health: Path | None = None,
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
    if build_sha not in artifact_name:
        raise ValueError("artifact name must contain the full build SHA")
    if endpoint not in built_by_command or ":app:assembleDebug" not in built_by_command:
        raise ValueError("build command must record the APK task and compiled endpoint")
    if install_log is None or launch_log is None:
        raise ValueError("install and normal-launch logs are required")
    install_text = install_log.read_text(encoding="utf-8", errors="replace") if install_log.is_file() else ""
    launch_text = launch_log.read_text(encoding="utf-8", errors="replace") if launch_log.is_file() else ""
    if "Success" not in install_text:
        raise ValueError("install log does not record a successful adb install")
    if "Status: ok" not in launch_text or "com.amazon.mercury.wallboard/.MainActivity" not in launch_text:
        raise ValueError("launch log does not record the normal Mercury activity")
    if "COCKPIT_URL" in launch_text:
        raise ValueError("launch log contains an ADB URL override")
    if endpoint_health is None or not endpoint_health.is_file():
        raise ValueError("exact deployed endpoint health evidence is required")
    try:
        endpoint_health_data = json.loads(endpoint_health.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("endpoint health evidence is not valid JSON") from exc
    endpoint_health_build_sha = endpoint_health_data.get("build_sha")
    if endpoint_health_build_sha != build_sha:
        raise ValueError(
            f"deployed endpoint build {endpoint_health_build_sha!r} does not match APK build {build_sha}"
        )

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
        "built_by_command": built_by_command,
        "apk_path": apk.as_posix(),
        "apk_sha256": hashlib.sha256(apk.read_bytes()).hexdigest(),
        "adb_install_exit_code": 0,
        "normal_launcher": "am start MAIN + LEANBACK_LAUNCHER; no COCKPIT_URL intent extra",
        "endpoint_loaded_without_intent_override": endpoint,
        "endpoint_health_build_sha": endpoint_health_build_sha,
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
            "endpoint_health": artifact(endpoint_health),
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
    parser.add_argument("--endpoint-health", type=Path, required=True)
    parser.add_argument("--workflow-run-url", default="")
    parser.add_argument("--artifact-name", default="")
    parser.add_argument("--built-by-command", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    receipt = build_receipt(
        args.apk, args.logcat, args.screenshot, args.endpoint, args.build_sha,
        args.device_model, args.os_version, args.install_log, args.launch_log,
        args.workflow_run_url, args.artifact_name, args.built_by_command, args.endpoint_health,
    )
    args.output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
