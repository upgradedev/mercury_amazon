"""Validate and record an Android TV emulator journey for the exact APK."""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import zipfile
import zlib
from datetime import datetime, timezone
from pathlib import Path

REQUIRED_EVENTS = (
    "journey:page_loaded:",
    "journey:what_changed:ANOMALY_ATTRIBUTED:",
    "journey:rollback_staged:",
    "journey:rollback_confirmed:RECORDED_ONLY:DPAD_RECORD_ONLY_DEMO",
    "journey:handoff_published:checkout-api-active:",
)

#: A frame that shows the page has text, antialiasing and more than one surface, so
#: a sampled grid of it carries many colours. Run 39210785053's final.png was one
#: colour, (0,0,0), over 1920x1080 and passed only because it was 10,608 bytes.
SCREENSHOT_GRID = 64
PNG_SIGNATURE = bytes((137, 80, 78, 71, 13, 10, 26, 10))
SCREENSHOT_MIN_COLOURS = 16
SCREENSHOT_MAX_MODAL_SHARE = 0.98


def _png_rows(data: bytes) -> tuple[int, int, int, list[bytes]]:
    """Decode an 8-bit greyscale, RGB or RGBA PNG to its unfiltered rows (stdlib only)."""
    if data[:8] != PNG_SIGNATURE:
        raise ValueError("runtime screenshot is not a PNG")
    pos, idat, header = 8, [], None
    while pos + 8 <= len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        chunk = data[pos + 8:pos + 8 + length]
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", chunk)
        elif kind == b"IDAT":
            idat.append(chunk)
        elif kind == b"IEND":
            break
        pos += 12 + length
    if header is None or not idat:
        raise ValueError("runtime screenshot PNG has no image data")
    width, height, depth, colour, _, _, interlace = header
    channels = {0: 1, 2: 3, 4: 2, 6: 4}.get(colour)
    if depth != 8 or channels is None or interlace != 0:
        raise ValueError("runtime screenshot PNG format cannot be checked (need 8-bit, non-interlaced)")
    raw = zlib.decompress(b"".join(idat))
    stride = width * channels
    rows: list[bytes] = []
    previous = bytearray(stride)
    for y in range(height):
        start = y * (stride + 1)
        kind, line = raw[start], bytearray(raw[start + 1:start + 1 + stride])
        if len(line) != stride:
            raise ValueError("runtime screenshot PNG is truncated")
        if kind == 1:
            for i in range(channels, stride):
                line[i] = (line[i] + line[i - channels]) & 0xFF
        elif kind == 2:
            for i in range(stride):
                line[i] = (line[i] + previous[i]) & 0xFF
        elif kind == 3:
            for i in range(stride):
                left = line[i - channels] if i >= channels else 0
                line[i] = (line[i] + ((left + previous[i]) >> 1)) & 0xFF
        elif kind == 4:
            for i in range(stride):
                a = line[i - channels] if i >= channels else 0
                b = previous[i]
                c = previous[i - channels] if i >= channels else 0
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                pred = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                line[i] = (line[i] + pred) & 0xFF
        elif kind != 0:
            raise ValueError("runtime screenshot PNG has an unknown row filter")
        rows.append(bytes(line))
        previous = line
    return width, height, channels, rows


def screenshot_problem(screenshot: Path) -> str | None:
    """Why the final frame cannot show the page, or None.

    A grid of SCREENSHOT_GRID x SCREENSHOT_GRID pixels is sampled. A frame with fewer
    than SCREENSHOT_MIN_COLOURS colours, or one colour on more than
    SCREENSHOT_MAX_MODAL_SHARE of the samples, is uniform or near-uniform: a black or
    blank screen, not the cockpit."""
    width, height, channels, rows = _png_rows(screenshot.read_bytes())
    counts: dict[bytes, int] = {}
    for gy in range(SCREENSHOT_GRID):
        row = rows[min(height - 1, gy * height // SCREENSHOT_GRID)]
        for gx in range(SCREENSHOT_GRID):
            x = min(width - 1, gx * width // SCREENSHOT_GRID) * channels
            pixel = row[x:x + channels]
            counts[pixel] = counts.get(pixel, 0) + 1
    samples = SCREENSHOT_GRID * SCREENSHOT_GRID
    modal_pixel, modal = max(counts.items(), key=lambda item: item[1])
    if len(counts) < SCREENSHOT_MIN_COLOURS or modal / samples > SCREENSHOT_MAX_MODAL_SHARE:
        return (f"runtime screenshot {width}x{height} is uniform or near-uniform: {len(counts)} "
                f"colours in {samples} samples, {modal / samples:.1%} of them {tuple(modal_pixel)}")
    return None


def build_receipt(
    apk: Path, logcat: Path, screenshot: Path, endpoint: str, build_sha: str,
    device_model: str, os_version: str, install_log: Path | None = None,
    launch_log: Path | None = None, workflow_run_url: str = "", artifact_name: str = "",
    built_by_command: str = "", endpoint_health: Path | None = None,
    activities: Path | None = None,
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
    frame = screenshot_problem(screenshot)
    if frame is not None:
        raise ValueError(frame)
    if activities is None or not activities.is_file() or activities.stat().st_size == 0:
        raise ValueError("the activity dump (dumpsys activity activities) is required")
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
    if "Status: ok" not in launch_text or "io.github.upgradedev.mercury.wallboard/.MainActivity" not in launch_text:
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
            "activities": artifact(activities),
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
    parser.add_argument("--activities", type=Path, required=True)
    parser.add_argument("--workflow-run-url", default="")
    parser.add_argument("--artifact-name", default="")
    parser.add_argument("--built-by-command", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    receipt = build_receipt(
        args.apk, args.logcat, args.screenshot, args.endpoint, args.build_sha,
        args.device_model, args.os_version, args.install_log, args.launch_log,
        args.workflow_run_url, args.artifact_name, args.built_by_command, args.endpoint_health,
        args.activities,
    )
    args.output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
