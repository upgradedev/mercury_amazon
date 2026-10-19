import hashlib
import json
import struct
import zipfile
import zlib

import pytest

from scripts.write_android_tv_runtime_receipt import (
    REQUIRED_EVENTS,
    build_receipt,
    screenshot_problem,
)


def _paeth(a, b, c):
    pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
    return a if pa <= pb and pa <= pc else (b if pb <= pc else c)


def png(width, height, pixel, channels=4):
    """An 8-bit PNG whose rows cycle through all five filter types, so the
    writer's decoder is exercised on each one. pixel(x, y) gives the channels."""
    raw, previous = bytearray(), bytes(width * channels)
    for y in range(height):
        line = bytes(v for x in range(width) for v in pixel(x, y))
        kind = y % 5
        out = bytearray()
        for i, value in enumerate(line):
            a = line[i - channels] if i >= channels else 0
            b = previous[i]
            c = previous[i - channels] if i >= channels else 0
            pred = (0, a, b, (a + b) >> 1, _paeth(a, b, c))[kind]
            out.append((value - pred) & 0xFF)
        raw += bytes([kind]) + out
        previous = line
    colour = {1: 0, 3: 2, 4: 6}[channels]

    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

    return (bytes((137, 80, 78, 71, 13, 10, 26, 10))
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, colour, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 0))
            + chunk(b"IEND", b""))


def page_like(x, y):
    """Many colours, like a page with text: a deterministic pseudo-random field."""
    digest = hashlib.sha256(f"{x},{y}".encode()).digest()
    return (digest[0], digest[1], digest[2], 255)


def evidence(tmp_path):
    apk = tmp_path / "app-debug.apk"
    with zipfile.ZipFile(apk, "w") as archive:
        archive.writestr("AndroidManifest.xml", b"compiled")
        archive.writestr("classes.dex", b"x" * 100)
    logcat = tmp_path / "logcat.txt"
    endpoint = "https://candidate.example/"
    logcat.write_text(endpoint + "\n" + "\n".join(REQUIRED_EVENTS), encoding="utf-8")
    screenshot = tmp_path / "final.png"
    screenshot.write_bytes(png(80, 60, page_like))
    return apk, logcat, screenshot, endpoint


def activities_dump(tmp_path):
    path = tmp_path / "activities.txt"
    path.write_text("ACTIVITY MANAGER ACTIVITIES (dumpsys activity activities)\n", encoding="utf-8")
    return path


def _receipt(tmp_path, screenshot=None, activities="default"):
    apk, logcat, shot, endpoint = evidence(tmp_path)
    if screenshot is not None:
        shot.write_bytes(screenshot)
    install = tmp_path / "install.txt"
    install.write_text("Success\n", encoding="utf-8")
    launch = tmp_path / "launch.txt"
    launch.write_text(
        "Status: ok\nActivity: io.github.upgradedev.mercury.wallboard/.MainActivity\n",
        encoding="utf-8",
    )
    health = tmp_path / "endpoint-health.json"
    health.write_text(json.dumps({"build_sha": "a" * 40}), encoding="utf-8")
    return build_receipt(
        apk, logcat, shot, endpoint, "a" * 40, "Android TV", "Android 11",
        install, launch, "https://github.com/example/repo/actions/runs/1", "runtime-" + "a" * 40,
        "./gradlew :app:assembleDebug -PmercuryCockpitUrl=https://candidate.example/",
        health, activities_dump(tmp_path) if activities == "default" else activities,
    )


def test_receipt_requires_every_runtime_event_and_records_apk_digest(tmp_path):
    apk, logcat, screenshot, endpoint = evidence(tmp_path)
    install = tmp_path / "install.txt"
    install.write_text("Success\n", encoding="utf-8")
    launch = tmp_path / "launch.txt"
    launch.write_text(
        "Status: ok\nActivity: io.github.upgradedev.mercury.wallboard/.MainActivity\n",
        encoding="utf-8",
    )
    health = tmp_path / "endpoint-health.json"
    health.write_text(json.dumps({"build_sha": "a" * 40}), encoding="utf-8")
    receipt = build_receipt(
        apk, logcat, screenshot, endpoint, "a" * 40, "Android TV", "Android 11",
        install, launch, "https://github.com/example/repo/actions/runs/1", "runtime-" + "a" * 40,
        "./gradlew :app:assembleDebug -PmercuryCockpitUrl=https://candidate.example/",
        health, activities_dump(tmp_path),
    )
    assert receipt["remote_journey"]["events"] == list(REQUIRED_EVENTS)
    assert len(receipt["apk_sha256"]) == 64
    assert receipt["endpoint_loaded_without_intent_override"] == endpoint
    assert receipt["artifacts"]["screenshot"]["bytes"] > 10_000
    assert receipt["workflow_run_url"].endswith("/1")
    assert receipt["endpoint_health_build_sha"] == "a" * 40


def test_receipt_refuses_an_endpoint_from_a_different_release(tmp_path):
    apk, logcat, screenshot, endpoint = evidence(tmp_path)
    install = tmp_path / "install.txt"
    install.write_text("Success\n", encoding="utf-8")
    launch = tmp_path / "launch.txt"
    launch.write_text(
        "Status: ok\nActivity: io.github.upgradedev.mercury.wallboard/.MainActivity\n",
        encoding="utf-8",
    )
    health = tmp_path / "endpoint-health.json"
    health.write_text(json.dumps({"build_sha": "b" * 40}), encoding="utf-8")
    with pytest.raises(ValueError, match="does not match APK build"):
        build_receipt(
            apk, logcat, screenshot, endpoint, "a" * 40, "Android TV", "Android 11",
            install, launch, "https://github.com/example/repo/actions/runs/1",
            "runtime-" + "a" * 40,
            "./gradlew :app:assembleDebug -PmercuryCockpitUrl=https://candidate.example/",
            health, activities_dump(tmp_path),
        )


def test_receipt_refuses_missing_journey_event(tmp_path):
    apk, logcat, screenshot, endpoint = evidence(tmp_path)
    logcat.write_text(endpoint + "\n" + REQUIRED_EVENTS[0], encoding="utf-8")
    with pytest.raises(ValueError, match="missing required journey events"):
        build_receipt(apk, logcat, screenshot, endpoint, "abc", "Android TV", "Android 11")


def test_a_page_like_frame_passes_and_the_activity_dump_is_hashed(tmp_path):
    receipt = _receipt(tmp_path)
    dump = (tmp_path / "activities.txt").read_bytes()
    assert receipt["artifacts"]["activities"]["sha256"] == hashlib.sha256(dump).hexdigest()
    assert receipt["artifacts"]["activities"]["bytes"] == len(dump)


def test_a_black_frame_over_the_byte_floor_is_refused(tmp_path):
    """Run 39210785053's final.png: one colour, (0,0,0), at 10,608 bytes. Stored
    uncompressed here, it is far over the 10,000 byte floor and must still fail."""
    black = png(200, 100, lambda x, y: (0, 0, 0, 255))
    assert len(black) > 10_000
    with pytest.raises(ValueError, match="uniform or near-uniform"):
        _receipt(tmp_path, screenshot=black)


def test_a_near_uniform_frame_is_refused(tmp_path):
    """A blank screen with a small cursor or a status dot is still not the page."""
    def mostly_black(x, y):
        return page_like(x, y) if x < 2 and y < 40 else (0, 0, 0, 255)

    frame = png(200, 100, mostly_black)
    assert screenshot_problem_text(tmp_path, frame) is not None
    with pytest.raises(ValueError, match="uniform or near-uniform"):
        _receipt(tmp_path, screenshot=frame)


def test_rgb_and_greyscale_frames_decode_on_every_filter(tmp_path):
    rgb = png(70, 50, lambda x, y: page_like(x, y)[:3], channels=3)
    assert screenshot_problem_text(tmp_path, rgb) is None
    grey = png(70, 50, lambda x, y: ((x * 7 + y * 13) % 256,), channels=1)
    assert screenshot_problem_text(tmp_path, grey) is None
    flat_grey = png(70, 50, lambda x, y: (128,), channels=1)
    assert "uniform" in screenshot_problem_text(tmp_path, flat_grey)


def test_a_file_that_is_not_a_png_is_refused(tmp_path):
    with pytest.raises(ValueError, match="not a PNG"):
        _receipt(tmp_path, screenshot=b"png" + b"x" * 10_001)


def test_the_activity_dump_is_required(tmp_path):
    with pytest.raises(ValueError, match="activity dump"):
        _receipt(tmp_path, activities=None)
    empty = tmp_path / "empty.txt"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="activity dump"):
        _receipt(tmp_path, activities=empty)


def screenshot_problem_text(tmp_path, data):
    path = tmp_path / "frame.png"
    path.write_bytes(data)
    return screenshot_problem(path)
