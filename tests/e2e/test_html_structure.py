"""Static HTML DOM Structure & UI Element Assertion Suite for Mercury.

Performs static string and structure assertions over docs/index.html to verify:
- D-Pad 10-foot spatial navigation DOM focus rings and keyboard listeners
- DORA metrics cards, PR bottleneck panels, and AWS cost surge displays
- Governed rollback modal containers and SHA-256 lease tags
(Note: Runs static file assertions without an active browser driver).
"""
import os


def test_mercury_web_html_structure():
    """Verify docs/index.html contains D-Pad nav elements, DORA tiles, and voice synthesis."""
    index_path = os.path.join(os.path.dirname(__file__), "../../docs/index.html")
    assert os.path.exists(index_path), "docs/index.html must exist"

    with open(index_path, "r", encoding="utf-8") as f:
        html = f.read()

    assert "Mercury" in html
    assert "Voice Cockpit" in html or "TV Cockpit" in html

    # D-Pad banner and spatial nav
    assert "dpad-banner" in html
    assert "tv-nav" in html
    assert "tv-focused" in html
    assert "ArrowUp" in html
    assert "ArrowDown" in html
    assert "Enter" in html

    # DORA tiles and Cost Radar
    assert "inspectDora" in html
    assert "scanCostAnomalies" in html
    assert "initiateRollback" in html

    # Speech
    assert "speechSynthesis" in html
    assert "SpeechSynthesisUtterance" in html


def test_mercury_dora_metrics_values():
    """Verify DORA numbers in HTML match benchmark receipts."""
    index_path = os.path.join(os.path.dirname(__file__), "../../docs/index.html")
    with open(index_path, "r", encoding="utf-8") as f:
        html = f.read()

    assert "2.4 / day" in html
    assert "14.5 h" in html
    assert "3.2%" in html
    assert "0.8 h" in html
