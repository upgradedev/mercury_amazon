#!/usr/bin/env python3
"""Measure the rendered text sizes of the cockpit at a television viewport.

The Fire TV track's own screen is 1920x1080 viewed from across a room, and the
usual floor for body text at that distance is 24 CSS pixels. This script is the
only honest way to check that: the page's type is set in rem against a root that
changes at a breakpoint, with several ``clamp()`` values on top, so the rendered
size of any given line is not something a reader can work out from the stylesheet.

It starts the real server, opens the real page in Chromium, drives it far enough
that the evidence panels have content in them, and then reports the rendered
``font-size`` of every element that is actually painting text. The panels matter:
they are ``hidden`` on load and most of their text does not exist until a fetch
has returned, so a measurement of the default view reports a clean minimum while
the evidence underneath is still too small to read.

Usage::

    pip install playwright && playwright install chromium
    python scripts/measure_legibility.py            # measure and report
    python scripts/measure_legibility.py --json     # machine readable

Exit code is 1 when any visible text renders below the floor, so this can be run
as a check as well as a measurement.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VIEWPORT = {"width": 1920, "height": 1080}
TEN_FOOT_FLOOR_PX = 24.0

# Every element that paints text of its own, with the rendered size of that text.
# "Of its own" means a direct child text node: without that, a wrapper reports the
# size it inherits and the same line is counted several times.
COLLECT_JS = """
() => {
  const out = [];
  for (const el of document.body.querySelectorAll('*')) {
    const own = Array.from(el.childNodes)
      .filter(n => n.nodeType === Node.TEXT_NODE && n.textContent.trim().length)
      .map(n => n.textContent.trim())
      .join(' ');
    if (!own) continue;
    const style = getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity) === 0) continue;
    const rect = el.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) continue;
    if (rect.bottom <= 0) continue;   // parked off-screen by design, e.g. the skip link
    out.push({
      tag: el.tagName.toLowerCase(),
      cls: el.className && typeof el.className === 'string' ? el.className : '',
      id: el.id || '',
      px: Math.round(parseFloat(style.fontSize) * 10) / 10,
      text: own.slice(0, 60),
    });
  }
  return out;
}
"""


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def wait_for_health(port: int, process: subprocess.Popen, timeout: float = 40.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if process.poll() is not None:
            raise SystemExit(f"the server exited early with code {process.returncode}")
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
            time.sleep(0.25)
    raise SystemExit(f"the server did not answer /health on port {port} within {timeout:.0f}s")


def collect(port: int) -> dict[str, object]:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as driver:
        browser = driver.chromium.launch()
        page = browser.new_page(viewport=VIEWPORT)
        page.goto(f"http://127.0.0.1:{port}/", wait_until="load")

        # The page asks what changed on load. Wait for that answer rather than a
        # timer, so the hero is measured with real content in it.
        page.wait_for_function(
            "() => document.getElementById('heroLatency')"
            "  && document.getElementById('heroLatency').textContent.indexOf('answered') !== -1",
            timeout=20000,
        )

        # Each view is measured on its own. The hero, the top bar and the key
        # hint bar stay on screen behind an open panel, so they are legitimately
        # part of every view rather than counted once and forgotten.
        views: dict[str, list] = {"wall": page.evaluate(COLLECT_JS)}

        # The panels are hidden on load and most of their text does not exist
        # until a fetch has returned, so each one is opened and loaded here.
        page.click(".tile[data-panel='incident']")
        views["incident"] = page.evaluate(COLLECT_JS)

        page.click("#panel-incident [data-back]")
        page.click(".tile[data-panel='velocity']")
        page.click("#panel-velocity [data-action='dora']")
        page.wait_for_selector("#doraOutput dl.kv, #doraOutput .error-card", timeout=20000)
        views["velocity"] = page.evaluate(COLLECT_JS)

        page.click("#panel-velocity [data-back]")
        page.click(".tile[data-panel='spend']")
        page.click("#panel-spend [data-action='cost']")
        page.wait_for_selector("#costOutput dl.kv, #costOutput .error-card", timeout=20000)
        views["spend"] = page.evaluate(COLLECT_JS)

        layout = page.evaluate(
            "() => ({"
            "  scrollWidth: document.documentElement.scrollWidth,"
            "  innerWidth: window.innerWidth,"
            "  keybarHeight: Math.round(document.querySelector('.keybar').getBoundingClientRect().height),"
            "  bodyPaddingBottom: Math.round(parseFloat(getComputedStyle(document.body).paddingBottom)),"
            "  rootFontPx: parseFloat(getComputedStyle(document.documentElement).fontSize)"
            "})"
        )
        browser.close()

    return {"views": views, "layout": layout}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="print the measurement as JSON")
    parser.add_argument("--floor", type=float, default=TEN_FOOT_FLOOR_PX)
    args = parser.parse_args()
    # The key hint bar contains arrow glyphs, and this repository is developed on
    # a console whose default encoding cannot represent them.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    try:
        import playwright  # noqa: F401
    except ImportError:
        print(
            "playwright is not installed, so nothing was measured. It is an optional extra:\n"
            '  pip install -e ".[ux]" && playwright install chromium'
        )
        return 2

    port = free_port()
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "src.interfaces.mcp_server:app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=str(REPO_ROOT),
        env=dict(os.environ, MERCURY_OFFLINE="1", MERCURY_ROLLBACK_SECRET="legibility-measurement"),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        wait_for_health(port, server)
        measurement = collect(port)
    except Exception as exc:
        if "playwright install" in str(exc).lower() or "executable doesn't exist" in str(exc).lower():
            print(
                "the Chromium build playwright drives is not installed, so nothing was "
                f"measured: {exc}"
            )
            return 2
        raise
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()

    views = measurement["views"]
    layout = measurement["layout"]
    every = [dict(element, view=view) for view, elements in views.items() for element in elements]
    under = sorted((e for e in every if e["px"] < args.floor), key=lambda e: (e["px"], e["view"]))
    smallest = min((e["px"] for e in every), default=0.0)

    per_view = {
        view: {
            "text_elements": len(elements),
            "under_floor": sum(1 for e in elements if e["px"] < args.floor),
            "smallest_px": min((e["px"] for e in elements), default=0.0),
        }
        for view, elements in views.items()
    }

    result = {
        "viewport": VIEWPORT,
        "floor_px": args.floor,
        "root_font_px": layout["rootFontPx"],
        "text_element_readings": len(every),
        "under_floor": len(under),
        "smallest_rendered_px": smallest,
        "per_view": per_view,
        "horizontal_overflow": layout["scrollWidth"] > layout["innerWidth"],
        "keybar_height_px": layout["keybarHeight"],
        "body_padding_bottom_px": layout["bodyPaddingBottom"],
        "offenders": [
            {"px": e["px"], "view": e["view"],
             "selector": f"{e['tag']}.{e['cls']}".rstrip("."), "text": e["text"]}
            for e in under[:40]
        ],
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Measured {len(every)} visible text readings across {len(views)} views at "
              f"{VIEWPORT['width']}x{VIEWPORT['height']} (root font {layout['rootFontPx']}px)")
        for view, stats in per_view.items():
            print(f"  {view:<9} {stats['text_elements']:>3} text elements, "
                  f"{stats['under_floor']:>3} under the floor, smallest {stats['smallest_px']}px")
        print(f"  smallest rendered text anywhere: {smallest}px "
              f"(floor {args.floor:.0f}px)")
        print(f"  readings under the floor: {len(under)} of {len(every)}")
        print(f"  horizontal overflow: {result['horizontal_overflow']} "
              f"(scrollWidth {layout['scrollWidth']}, innerWidth {layout['innerWidth']})")
        print(f"  fixed key bar: {layout['keybarHeight']}px tall, "
              f"body reserves {layout['bodyPaddingBottom']}px below the content")
        for offender in result["offenders"]:
            print(f"    {offender['px']:>6}px  {offender['view']:<9} "
                  f"{offender['selector']:<32} {offender['text']}")

    failures = len(under) > 0 or result["horizontal_overflow"] \
        or layout["keybarHeight"] > layout["bodyPaddingBottom"]
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
