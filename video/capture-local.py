#!/usr/bin/env python3
"""Record the demo journey from a local Mercury server with Playwright.

The submission kit's capture step is a Node script that runs in CI against a public
site. This repository has no public deployment of the build being recorded, so this
is the same journey logic in Python against a local server:

  * the server's own ``/health`` must report ``MERCURY_RELEASE_SHA`` before anything
    is recorded, so the commit on the title card is the commit that answered;
  * Chromium records at 1920x1080, the size the Fire TV WebView renders;
  * every key is sent through ``window.navigateDpad``, the bridge the Leanback
    ``MainActivity`` calls, never a mouse click;
  * the timeline starts only after all five board rows show a verdict from the
    server, and each beat is held for its measured length from ``timing.json``;
  * every press checks which control took focus, and every answer is awaited from
    the server, so a journey that drifts from the narration aborts instead of being
    filmed. Nothing on screen is staged or edited; waiting is real waiting. The one
    addition is a 1x1 px repaint marker (see ``REPAINT``), which only makes sure
    the recorder is sent the frame the page is already showing.

Run from the repository root, with the server already running:

    MERCURY_OFFLINE=1 python -m uvicorn src.interfaces.mcp_server:app --port 8803
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

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(os.environ["MERCURY_VIDEO_ROOT"])
RELEASE_SHA = os.environ["MERCURY_RELEASE_SHA"]
BASE_URL = os.environ.get("MERCURY_CAPTURE_URL", "http://127.0.0.1:8803/")
CAPTURE = ROOT / "capture"
TRAILING_HOLD_SECONDS = 2.5
EXPECTED_SCENES = [
    "beat_01_question",
    "beat_02_board_on_load",
    "beat_03_crowded_refusal",
    "beat_04_named_with_odds",
    "beat_05_provenance",
    "beat_06_stage",
    "beat_07_confirm",
    "beat_08_handoff",
    "beat_09_dpad",
    "beat_10_fixtures",
    "beat_11_build_check",
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
# ``when`` is seconds into the beat, or ("sentence", n, extra) for n-th caption sentence start.
JOURNEY: dict[str, list[tuple[object, str, str | None, str | None]]] = {
    "beat_01_question": [],
    "beat_02_board_on_load": [],
    "beat_03_crowded_refusal": [
        (0.3, "DOWN", "Ask about checkout-api", None),
        (0.9, "DOWN", "Ask about payments worker", None),
        (1.5, "DOWN", "Ask about search indexer", None),
        (2.1, "DOWN", "Ask about release train", None),
        (2.9, "SELECT", "Ask about release train", text_appears("#heroHeadline", "Cannot attribute")),
    ],
    "beat_04_named_with_odds": [
        (0.3, "UP", "Ask about search indexer", None),
        (0.9, "UP", "Ask about payments worker", None),
        (1.5, "UP", "Ask about checkout-api", None),
        (2.2, "SELECT", "Ask about checkout-api", text_appears("#heroHeadline", "Commit")),
    ],
    "beat_05_provenance": [],
    "beat_06_stage": [
        (("sentence", 1, 0.0), "UP", "Ask what changed", None),
        (("sentence", 1, 0.6), "RIGHT", "Stage governed rollback", None),
        (("sentence", 1, 1.2), "SELECT", "Stage governed rollback", text_appears("#heroEyebrow", "Rollback staged")),
    ],
    "beat_07_confirm": [
        (0.2, "RIGHT", "Confirm rollback", None),
        # The payoff stays on the board: the large figure reads RECORDED, the page has
        # not scrolled, and Publish handoff is only the next stop (no ring yet).
        (1.0, "SELECT", "Publish responder handoff", BOARD_RECORDED),
    ],
    "beat_08_handoff": [
        # The cursor stays on Publish and the handoff's answer comes up above the key bar.
        (0.3, "SELECT", "Publish responder handoff", text_appears("#handoffOutput", "Next step")),
        (("sentence", 1, 0.0), "DOWN", "Incident evidence panel", None),
    ],
    "beat_09_dpad": [
        (0.8, "RIGHT", "Delivery velocity panel", None),
        (("sentence", 1, 0.0), "SELECT", "Load DORA velocity", text_appears("#doraOutput", "offline-fixture")),
    ],
    # An open panel holds the remote until BACK: DOWN at its foot scrolls the rest of
    # the answer into view and the cursor stays on the panel's button.
    "beat_10_fixtures": [
        (0.2, "DOWN", "Load DORA velocity", None),
        (("sentence", 1, 0.0), "BACK", "Delivery velocity panel", None),
        (("sentence", 2, 0.0), "RIGHT", "Cloud spend panel", None),
        (("sentence", 2, 0.8), "SELECT", "Scan AWS spend", text_appears("#costOutput", "offline-fixture")),
        (("sentence", 2, 2.0), "BACK", "Cloud spend panel", None),
    ],
    "beat_11_build_check": [
        (0.2, "DOWN", "How it answers panel", None),
        (0.6, "DOWN", "Check connection", None),
        (1.0, "SELECT", "Check connection",
         r"() => /^GET \/health returned 200[^\n]*Build/.test(document.getElementById('connDetail').textContent)"),
    ],
}


def health() -> dict[str, object]:
    with urllib.request.urlopen(BASE_URL.rstrip("/") + "/health", timeout=10) as response:
        return json.load(response)


def main() -> None:
    timing = json.loads((ROOT / "narration" / "timing.json").read_text(encoding="utf-8"))
    scenes = timing["scenes"]
    if [scene["id"] for scene in scenes] != EXPECTED_SCENES:
        raise SystemExit("the narration and the capture journey name different beats")
    served = health()
    head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    if served.get("build_sha") != RELEASE_SHA or head != RELEASE_SHA:
        raise SystemExit(
            f"refusing to record: server reports {served.get('build_sha')}, HEAD is {head}, "
            f"MERCURY_RELEASE_SHA is {RELEASE_SHA}"
        )
    if served.get("rollback_dispatch") != "record-only" or served.get("github_live"):
        raise SystemExit("refusing to record: the server is not in record-only fixture mode")
    if CAPTURE.exists():
        shutil.rmtree(CAPTURE)
    (CAPTURE / "raw").mkdir(parents=True)

    errors: list[str] = []
    log: list[dict[str, object]] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(args=["--force-device-scale-factor=1"])
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            device_scale_factor=1,
            record_video_dir=str(CAPTURE / "raw"),
            record_video_size={"width": 1920, "height": 1080},
        )
        page = context.new_page()
        created = time.monotonic()
        page.on("pageerror", lambda error: errors.append(f"page:{error}"))
        page.on("console", lambda message: errors.append(f"console:{message.text}") if message.type == "error" else None)
        page.goto(BASE_URL, wait_until="networkidle", timeout=60_000)
        page.wait_for_function(ROWS_ANSWERED, timeout=30_000)
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
            start = timeline + float(scene["startSeconds"])
            end = start + float(scene["holdSeconds"])
            starts = scene.get("sentenceStartsSeconds") or [0.0]
            entry: dict[str, object] = {"id": scene["id"], "lateStartSeconds": round(time.monotonic() - start, 3), "actions": []}
            for when, key, expected, condition in JOURNEY[scene["id"]]:
                if isinstance(when, tuple):
                    _, sentence, extra = when
                    offset = float(starts[sentence]) + float(extra)
                else:
                    offset = float(when)
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
        if f"Build {RELEASE_SHA[:7]}" not in build_line:
            raise SystemExit(f"the connection line does not name the recorded build: {build_line!r}")
        page.wait_for_timeout(TRAILING_HOLD_SECONDS * 1000)
        video = page.video
        context.close()
        closed = time.monotonic()
        browser.close()
        raw = pathlib.Path(video.path())

    final = CAPTURE / "production.webm"
    raw.replace(final)
    shutil.rmtree(CAPTURE / "raw", ignore_errors=True)
    probe = subprocess.run(
        [os.environ.get("FFPROBE", "ffprobe"), "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(final)],
        capture_output=True, text=True,
    ).stdout.strip()
    data = final.read_bytes()
    receipt = {
        "schemaVersion": "mercury.video-capture/1",
        "releaseSha": RELEASE_SHA,
        "server": {key: served.get(key) for key in ("build_sha", "rollback_dispatch", "github_live", "dpad_demo_approval")},
        "url": BASE_URL,
        "viewport": "1920x1080",
        "input": "window.navigateDpad",
        "sceneCount": len(scenes),
        "trimLeadSeconds": round(timeline - created, 3),
        "timelineSeconds": float(timing["totalSeconds"]),
        "wallSecondsFromPageToClose": round(closed - created, 3),
        "webmDurationSeconds": float(probe) if probe and probe != "N/A" else None,
        "beats": log,
        "buildLine": build_line,
        "pageErrors": errors,
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    (CAPTURE / "capture-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    if errors:
        raise SystemExit(f"the journey emitted {len(errors)} browser errors: {errors[:3]}")
    print(json.dumps({key: receipt[key] for key in ("trimLeadSeconds", "timelineSeconds",
                                                    "wallSecondsFromPageToClose", "webmDurationSeconds", "sha256")}))


if __name__ == "__main__":
    main()
