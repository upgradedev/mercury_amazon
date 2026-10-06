#!/usr/bin/env python3
"""Record the demo journey from a local Mercury server with Playwright.

The submission kit's capture step is a Node script that runs in CI against a public
site. This repository has no public deployment of the build being recorded, so this
is the same journey logic in Python against a local server:

  * the server's own ``/health`` must report ``MERCURY_RELEASE_SHA`` before anything
    is recorded, so the commit on the title card is the commit that answered;
  * the take is desktop Chromium at 1920x1080 CSS pixels, the desktop layout; the
    Fire TV WebView lays the same page out at 960x540 CSS pixels at a device scale
    factor of 2 (``VIEWPORTS`` says why the take does not use that layout);
  * every key is sent through ``window.navigateDpad``, the bridge the Leanback
    ``MainActivity`` calls, never a mouse click;
  * the timeline starts only after all five board rows show a verdict from the
    server, and each beat is held for its measured length from ``timing.json``;
  * a key whose effect the narration names is pressed on the spoken word: at a
    mark read off the voice's alignment (``marksSeconds`` in ``timing.json``) or just
    before the caption that names its result, so no caption or word runs ahead of
    the picture;
  * every press checks which control took focus, and every answer is awaited from
    the server, so a journey that drifts from the narration aborts instead of being
    filmed. Nothing on screen is staged or edited; waiting is real waiting. The one
    addition is a 1x1 px repaint marker (see ``REPAINT``), which only makes sure
    the recorder is sent the frame the page is already showing.

The take opens on Android TV emulator footage filmed in CI, not by this script. The
narration's first beats (``source`` ``android_tv_emulator`` in ``timing.json``) play
over that footage, so this script skips them: its timeline starts at the first desktop
beat, and ``video/build-video.py`` puts the footage in front of the desktop capture.

Run from the repository root, with the server already running:

    MERCURY_OFFLINE=1 python -m uvicorn src.interfaces.mcp_server:app --port 8875
    MERCURY_VIDEO_ROOT=/path/outside/git MERCURY_RELEASE_SHA=$(git rev-parse HEAD) \\
        python video/capture-local.py

Writes ``capture/production.webm`` and ``capture/capture-receipt.json``.
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import time
import urllib.request

TRAILING_HOLD_SECONDS = 2.5
#: The two layouts this script can record. ``tv`` is the Fire TV WebView's: a 1080p
#: Fire TV reports a 960x540 CSS viewport at two device pixels per CSS pixel, and the
#: Leanback app injects ``MercuryHost`` before the page runs, which turns on
#: ``html.tv-host`` and the remote's key bar. The emulator footage shows the same
#: layout. ``desktop`` is a desktop browser at 1920x1080 CSS, the 2026-10-01 take.
#: Both are recorded into a 1920x1080 file.
#:
#: The take uses ``desktop``. A rehearsal at ``tv`` on 2026-10-06 passed the whole
#: journey unchanged (every press, focus and answer), but headless Chromium films CSS
#: pixels, not device pixels: Playwright's recorder and a raw CDP screencast both
#: return 960x540 frames at a device scale factor of 2, so the TV layout would reach
#: the video as a 960x540 picture upscaled, with half the detail of the desktop take.
VIEWPORTS = {
    "tv": {"width": 960, "height": 540, "scale": 2, "host": True},
    "desktop": {"width": 1920, "height": 1080, "scale": 1, "host": False},
}
DEFAULT_VIEWPORT = "desktop"
#: What the Fire TV app injects (MainActivity.MercuryHost); the stub the browser tests use.
HOST_STUB = "window.MercuryHost = { reportJourney: function () {} };"
EMULATOR_SOURCE = "android_tv_emulator"
#: The beats that play over emulator footage. They open the take; nothing is recorded
#: for them here.
EMULATOR_SCENES = [
    "beat_01_tv_board",
    "beat_02_tv_stage",
    "beat_03_tv_confirm",
    "beat_04_tv_publish",
]
#: The beats this script records, in order.
EXPECTED_SCENES = [
    "beat_05_desktop_board",
    "beat_06_board_on_load",
    "beat_07_crowded_refusal",
    "beat_08_named_with_odds",
    "beat_09_provenance",
    "beat_10_stage_to_evidence",
    "beat_11_dpad",
    "beat_12_fixtures",
    "beat_13_build_check",
]

FOCUSED = """() => { const c = window.mercuryNav && window.mercuryNav.current;
  return c ? (c.getAttribute('data-tv-label') || c.textContent.trim()) : null; }"""
LEGEND = "() => document.getElementById('hintBack').textContent"
ROWS_ANSWERED = """() => { const rows = document.querySelectorAll('[data-row-verdict]');
  return rows.length === 5 && Array.from(rows).every(r => ['attributed','cannot','nothing','insufficient']
    .includes(r.getAttribute('data-verdict'))); }"""

# Chromium's screencast drops a frame that is painted while the previous one is still
# unacknowledged, and sends nothing more until the page paints again. A fast answer
# (the /health check returns in a few milliseconds, straight after its "Sending"
# line) can therefore be missing from the recording although the page shows it: the
# first 2026-09-28 take held "Sending GET .../health" through the whole last beat.
# After every settled press the page is asked to paint three more times, by flipping
# the colour of one 1x1 px marker in the bottom-right corner, so the recorder receives
# the frame the page is actually showing. The marker has no text, takes no focus and
# is not a D-pad stop.
REPAINT = """() => { let m = document.getElementById('captureRepaint');
  if (!m) { m = document.createElement('div'); m.id = 'captureRepaint'; m.setAttribute('aria-hidden', 'true');
    m.style.cssText = 'position:fixed;right:0;bottom:0;width:1px;height:1px;pointer-events:none;z-index:2147483647';
    document.body.appendChild(m); }
  const tint = getComputedStyle(document.body).backgroundColor;
  [120, 400, 900].forEach((delay, i) => setTimeout(() => { m.style.background = i % 2 ? 'transparent' : tint; }, delay)); }"""

BOARD_RECORDED = """() => document.getElementById('heroFigure').textContent.trim() === 'RECORDED'
  && /recorded, not sent/i.test(document.getElementById('heroEyebrow').textContent)
  && window.scrollY === 0
  && /^Next press: Publish responder handoff/.test(document.getElementById('hintFocus').textContent)"""


def text_appears(selector: str, needle: str) -> str:
    return (
        "() => { const n = document.querySelector(%s); return !!n && n.textContent.includes(%s); }"
        % (json.dumps(selector), json.dumps(needle))
    )


# Each beat: a list of (when, key, expected focus label or None, condition to await or None).
# ``when`` is seconds into the beat; ("sentence", n, extra) for the n-th caption cue's
# start plus ``extra``; or ("mark", name, extra) for a spoken mark from timing.json.
JOURNEY: dict[str, list[tuple[object, str, str | None, str | None]]] = {
    "beat_05_desktop_board": [],
    "beat_06_board_on_load": [],
    # The four Downs and Center land while "Down walks the rows" is spoken, so the
    # verdict has settled on screen before the caption that describes it (the answer
    # takes about half a second to come up after Center).
    "beat_07_crowded_refusal": [
        (0.1, "DOWN", "Ask about checkout-api", None),
        (0.35, "DOWN", "Ask about payments worker", None),
        (0.6, "DOWN", "Ask about search indexer", None),
        (0.85, "DOWN", "Ask about release train", None),
        (1.1, "SELECT", "Ask about release train", text_appears("#heroHeadline", "Cannot attribute")),
    ],
    # The Ups and Center land on "Up, up, up, center", so focus is on checkout-api
    # before the caption that names it, and its verdict before the caption that says
    # exactly one runtime change landed.
    "beat_08_named_with_odds": [
        (("mark", "up", 0.0), "UP", "Ask about search indexer", None),
        (("mark", "up_again", 0.0), "UP", "Ask about payments worker", None),
        (("mark", "up_third", 0.0), "UP", "Ask about checkout-api", None),
        (("mark", "center", 0.0), "SELECT", "Ask about checkout-api", text_appears("#heroHeadline", "Commit")),
    ],
    "beat_09_provenance": [],
    # The stage, confirm and handoff presses of the 2026-10-01 take, in the same order
    # with the same checks, each on the word that names it. Publish and Down are
    # pressed 0.15 s before "Center publishes" and "Down shows": the handoff's answer
    # took from 0.25 s to 0.69 s on 2026-10-06, so the answer lands within a few
    # frames of its caption either way, and the RECORDED board stays up for its own.
    "beat_10_stage_to_evidence": [
        (("mark", "up", 0.0), "UP", "Ask what changed", None),
        (("mark", "stage_right", 0.0), "RIGHT", "Stage governed rollback", None),
        (("mark", "stage_center", 0.0), "SELECT", "Stage governed rollback",
         text_appears("#heroEyebrow", "Rollback staged")),
        (("mark", "confirm_right", 0.0), "RIGHT", "Confirm rollback", None),
        # The payoff stays on the board: the large figure reads RECORDED, the page has
        # not scrolled, and Publish handoff is only the next stop (no ring yet).
        (("mark", "confirm_center", 0.0), "SELECT", "Publish responder handoff", BOARD_RECORDED),
        # The cursor stays on Publish and the handoff's answer comes up above the key bar.
        (("mark", "publish", -0.15), "SELECT", "Publish responder handoff",
         text_appears("#handoffOutput", "Next step")),
        (("mark", "down", -0.15), "DOWN", "Incident evidence panel", None),
    ],
    # Center goes a third of a second before the caption that names it, so the panel
    # and the new BACK legend are up when the caption says so.
    "beat_11_dpad": [
        (0.8, "RIGHT", "Delivery velocity panel", None),
        (("sentence", 1, -0.35), "SELECT", "Load DORA velocity", text_appears("#doraOutput", "offline-fixture")),
    ],
    # An open panel holds the remote until BACK: DOWN at its foot scrolls the rest of
    # the answer into view and the cursor stays on the panel's button. Cloud spend is
    # opened before the caption that calls it synthetic.
    "beat_12_fixtures": [
        (0.0, "DOWN", "Load DORA velocity", None),
        (("sentence", 1, 0.0), "BACK", "Delivery velocity panel", None),
        (("sentence", 2, -0.8), "RIGHT", "Cloud spend panel", None),
        (("sentence", 2, -0.4), "SELECT", "Scan AWS spend", text_appears("#costOutput", "offline-fixture")),
        (("sentence", 2, 2.0), "BACK", "Cloud spend panel", None),
    ],
    "beat_13_build_check": [
        (("mark", "down", 0.0), "DOWN", "How it answers panel", None),
        (("mark", "down_again", 0.0), "DOWN", "Check connection", None),
        (("mark", "center", 0.0), "SELECT", "Check connection",
         r"() => /^GET \/health returned 200[^\n]*Build/.test(document.getElementById('connDetail').textContent)"),
    ],
}


def planned_offset(scene: dict[str, object], when: object) -> float:
    """Seconds into the beat at which a press is planned."""
    if not isinstance(when, tuple):
        return float(when)
    kind, anchor, extra = when
    if kind == "sentence":
        starts = scene.get("sentenceStartsSeconds") or [0.0]
        return float(starts[int(anchor)]) + float(extra)
    if kind == "mark":
        marks = scene.get("marksSeconds") or {}
        if anchor not in marks:
            raise SystemExit(f"{scene['id']} has no spoken mark {anchor!r} in timing.json")
        return float(marks[anchor]) + float(extra)
    raise SystemExit(f"unknown press anchor {kind!r}")


def desktop_scenes(scenes: list[dict[str, object]]) -> tuple[list[dict[str, object]], float]:
    """The scenes this script records, and the narration time its timeline starts at.

    The emulator scenes must all come first and be exactly ``EMULATOR_SCENES``; the
    rest must be exactly ``EXPECTED_SCENES``. The desktop timeline starts at the first
    desktop scene, so the capture is not left idling through the footage's length.
    """
    emulator = [scene for scene in scenes if scene.get("source") == EMULATOR_SOURCE]
    desktop = [scene for scene in scenes if scene.get("source") != EMULATOR_SOURCE]
    if scenes[: len(emulator)] != emulator:
        raise SystemExit("the emulator beats must open the narration, before any desktop beat")
    if [scene["id"] for scene in emulator] != EMULATOR_SCENES:
        raise SystemExit("the narration's emulator beats are not the ones this journey expects")
    if [scene["id"] for scene in desktop] != EXPECTED_SCENES:
        raise SystemExit("the narration and the capture journey name different beats")
    return desktop, float(desktop[0]["startSeconds"])


def health(base_url: str) -> dict[str, object]:
    with urllib.request.urlopen(base_url.rstrip("/") + "/health", timeout=10) as response:
        return json.load(response)


def main() -> None:
    # Imported here so the journey can be read (and tested) without a browser.
    from playwright.sync_api import sync_playwright

    root = pathlib.Path(os.environ["MERCURY_VIDEO_ROOT"])
    release_sha = os.environ["MERCURY_RELEASE_SHA"]
    base_url = os.environ.get("MERCURY_CAPTURE_URL", "http://127.0.0.1:8803/")
    capture = root / "capture"
    viewport = os.environ.get("MERCURY_CAPTURE_VIEWPORT", DEFAULT_VIEWPORT)
    if viewport not in VIEWPORTS:
        raise SystemExit(f"MERCURY_CAPTURE_VIEWPORT must be one of {sorted(VIEWPORTS)}")
    layout = VIEWPORTS[viewport]
    timing = json.loads((root / "narration" / "timing.json").read_text(encoding="utf-8"))
    scenes, desktop_start = desktop_scenes(timing["scenes"])
    served = health(base_url)
    head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    if served.get("build_sha") != release_sha or head != release_sha:
        raise SystemExit(
            f"refusing to record: server reports {served.get('build_sha')}, HEAD is {head}, "
            f"MERCURY_RELEASE_SHA is {release_sha}"
        )
    if served.get("rollback_dispatch") != "record-only" or served.get("github_live"):
        raise SystemExit("refusing to record: the server is not in record-only fixture mode")
    if capture.exists():
        shutil.rmtree(capture)
    (capture / "raw").mkdir(parents=True)

    errors: list[str] = []
    log: list[dict[str, object]] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(args=[f"--force-device-scale-factor={layout['scale']}"])
        # Reduced motion, so the headline's split-flap animation renders
        # instantly: frames taken mid-flip show scrambled glyphs.
        context = browser.new_context(
            viewport={"width": layout["width"], "height": layout["height"]},
            device_scale_factor=layout["scale"],
            record_video_dir=str(capture / "raw"),
            record_video_size={"width": 1920, "height": 1080},
            reduced_motion="reduce",
        )
        if layout["host"]:
            context.add_init_script(HOST_STUB)
        page = context.new_page()
        created = time.monotonic()
        page.on("pageerror", lambda error: errors.append(f"page:{error}"))
        page.on("console", lambda message: errors.append(f"console:{message.text}") if message.type == "error" else None)
        page.goto(base_url, wait_until="networkidle", timeout=60_000)
        page.wait_for_function(ROWS_ANSWERED, timeout=30_000)
        tv_host = page.evaluate("() => document.documentElement.classList.contains('tv-host')")
        if tv_host != layout["host"]:
            raise SystemExit(f"html.tv-host is {tv_host}, expected {layout['host']} for the {viewport} layout")
        if page.evaluate(FOCUSED) != "Ask what changed":
            raise SystemExit("the page did not start with focus on Ask what changed")
        page.wait_for_timeout(1000)
        timeline = time.monotonic()

        def press(key: str, expected: str | None, condition: str | None) -> dict[str, object]:
            consumed = page.evaluate(f"window.navigateDpad({json.dumps(key)})")
            if condition:
                page.wait_for_function(condition, timeout=8_000)
            page.wait_for_timeout(150)
            page.evaluate(REPAINT)
            focused = page.evaluate(FOCUSED)
            if expected is not None and focused != expected:
                raise SystemExit(f"after {key} focus is {focused!r}, expected {expected!r}")
            return {"key": key, "consumed": consumed, "focused": focused, "legend": page.evaluate(LEGEND)}

        for scene in scenes:
            start = timeline + float(scene["startSeconds"]) - desktop_start
            end = start + float(scene["holdSeconds"])
            entry: dict[str, object] = {"id": scene["id"], "lateStartSeconds": round(time.monotonic() - start, 3), "actions": []}
            for when, key, expected, condition in JOURNEY[scene["id"]]:
                offset = planned_offset(scene, when)
                target = start + offset
                wait = target - time.monotonic()
                if wait > 0:
                    page.wait_for_timeout(wait * 1000)
                pressed_at = time.monotonic() - start
                result = press(key, expected, condition)
                result.update({"plannedAt": round(offset, 3), "pressedAt": round(pressed_at, 3),
                               "settledAt": round(time.monotonic() - start, 3)})
                entry["actions"].append(result)
            remaining = end - time.monotonic()
            if remaining < 0:
                raise SystemExit(f"{scene['id']} overran its measured hold by {-remaining:.3f}s")
            page.wait_for_timeout(remaining * 1000)
            log.append(entry)

        build_line = page.evaluate("() => document.body.innerText.match(/GET \\/health returned[^\\n]*/)?.[0] || ''")
        if f"Build {release_sha[:7]}" not in build_line:
            raise SystemExit(f"the connection line does not name the recorded build: {build_line!r}")
        page.wait_for_timeout(TRAILING_HOLD_SECONDS * 1000)
        video = page.video
        context.close()
        closed = time.monotonic()
        browser.close()
        raw = pathlib.Path(video.path())

    final = capture / "production.webm"
    raw.replace(final)
    shutil.rmtree(capture / "raw", ignore_errors=True)
    probe = subprocess.run(
        [os.environ.get("FFPROBE", "ffprobe"), "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(final)],
        capture_output=True, text=True,
    ).stdout.strip()
    data = final.read_bytes()
    receipt = {
        "schemaVersion": "mercury.video-capture/1",
        "releaseSha": release_sha,
        "server": {key: served.get(key) for key in ("build_sha", "rollback_dispatch", "github_live", "dpad_demo_approval")},
        "url": base_url,
        "viewport": viewport,
        "cssViewport": f"{layout['width']}x{layout['height']}",
        "deviceScaleFactor": layout["scale"],
        "tvHost": layout["host"],
        "recordedSize": "1920x1080",
        "input": "window.navigateDpad",
        "sceneCount": len(scenes),
        "trimLeadSeconds": round(timeline - created, 3),
        "timelineSeconds": round(float(timing["totalSeconds"]) - desktop_start, 3),
        "narrationStartSeconds": desktop_start,
        "wallSecondsFromPageToClose": round(closed - created, 3),
        "webmDurationSeconds": float(probe) if probe and probe != "N/A" else None,
        "beats": log,
        "buildLine": build_line,
        "pageErrors": errors,
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    (capture / "capture-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    if errors:
        raise SystemExit(f"the journey emitted {len(errors)} browser errors: {errors[:3]}")
    print(json.dumps({key: receipt[key] for key in ("trimLeadSeconds", "timelineSeconds",
                                                    "wallSecondsFromPageToClose", "webmDurationSeconds", "sha256")}))


if __name__ == "__main__":
    main()
