"""The video capture must emulate reduced motion.

The board's headline plays a split-flap animation on every answer, and frames
taken mid-flip show scrambled glyphs. The page renders verdict lines instantly
under prefers-reduced-motion (see
test_the_verdict_line_is_instant_under_reduced_motion), so the capture asks
for that: every recorded frame is readable.
"""
from pathlib import Path

CAPTURE = Path(__file__).resolve().parents[2] / "video" / "capture-local.py"


def test_the_capture_emulates_reduced_motion():
    source = CAPTURE.read_text(encoding="utf-8")
    assert 'reduced_motion="reduce"' in source
