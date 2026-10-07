"""The footage script's D-pad walk to the Mercury tile, decided from uiautomator dumps."""

from __future__ import annotations

from pathlib import Path

from scripts import android_tv_tile_focus as focus

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _tile(label: str, bounds: str, focused: bool = False) -> str:
    return (
        '<node text="" content-desc="" focusable="true" clickable="true" '
        f'focused="{str(focused).lower()}" bounds="{bounds}">'
        f'<node text="{label}" content-desc="" focusable="false" clickable="false" '
        f'focused="false" bounds="{bounds}" /></node>'
    )


def _dump(tmp_path: Path, *rows: str) -> str:
    body = "".join(rows)
    xml = (
        "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?><hierarchy rotation=\"0\">"
        '<node text="" content-desc="" focusable="false" clickable="false" focused="false" '
        f'bounds="[0,0][1920,1080]">{body}</node></hierarchy>'
    )
    path = tmp_path / "ui.xml"
    path.write_text(xml, encoding="utf-8")
    return str(path)


def _decide(path: str) -> tuple[str, str]:
    return focus.decide(focus.parse(path), "Mercury")


def test_focused_tile_that_names_mercury_is_confirmed(tmp_path):
    path = _dump(
        tmp_path,
        _tile("Settings", "[100,300][400,500]"),
        _tile("Mercury Incident Board", "[450,300][750,500]", focused=True),
    )
    assert _decide(path) == ("FOCUSED", "Mercury Incident Board")


def test_moves_along_the_row_then_between_rows(tmp_path):
    same_row = _dump(
        tmp_path,
        _tile("Settings", "[100,300][400,500]", focused=True),
        _tile("Mercury Incident Board", "[450,300][750,500]"),
    )
    assert _decide(same_row)[0] == "KEYCODE_DPAD_RIGHT"
    row_below = _dump(
        tmp_path,
        _tile("Settings", "[100,300][400,500]", focused=True),
        _tile("Mercury Incident Board", "[100,600][400,800]"),
    )
    assert _decide(row_below)[0] == "KEYCODE_DPAD_DOWN"


def test_a_focused_container_is_not_the_tile(tmp_path):
    """A whole row being focused must not count as focus on the Mercury tile."""
    row = (
        '<node text="" content-desc="" focusable="true" clickable="false" focused="true" '
        'bounds="[0,0][1920,1080]">'
        + _tile("Mercury Incident Board", "[450,300][750,500]")
        + "</node>"
    )
    action, _ = _decide(_dump(tmp_path, row))
    assert action != "FOCUSED"


def test_opens_the_apps_entry_when_no_tile_names_mercury(tmp_path):
    towards = _dump(
        tmp_path,
        _tile("Apps", "[100,300][300,500]"),
        _tile("Settings", "[350,300][650,500]", focused=True),
    )
    assert _decide(towards)[0] == "KEYCODE_DPAD_LEFT"
    on_it = _dump(
        tmp_path,
        _tile("Apps", "[100,300][300,500]", focused=True),
        _tile("Settings", "[350,300][650,500]"),
    )
    assert _decide(on_it) == ("OPEN", "Apps")


def test_search_and_nofocus_never_claim_focus(tmp_path):
    action, signature = _decide(_dump(tmp_path, _tile("Settings", "[100,300][400,500]", focused=True)))
    assert action == "SEARCH"
    assert "Settings" in signature
    assert _decide(_dump(tmp_path, _tile("Settings", "[100,300][400,500]")))[0] == "NOFOCUS"


def test_footage_script_records_which_launch_path_it_used():
    script = (REPO_ROOT / "scripts" / "android_tv_footage.sh").read_text(encoding="utf-8")
    assert "scripts/android_tv_tile_focus.py" in script
    assert '"launch_path": launch_path' in script
    assert 'mark "launch path: dpad' in script
    assert 'mark "launch path: am start fallback' in script
    workflow = (REPO_ROOT / ".github" / "workflows" / "android-tv-footage.yml").read_text(encoding="utf-8")
    assert "scripts/android_tv_tile_focus.py" in workflow
