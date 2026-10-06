"""The next take opens on the Android TV emulator footage, and stays truthful.

These tests read the plan, the capture journey and the compose graph without a
browser, a server, a key or a render:

* the emulator beats open the content, cover one unbroken window of the CI footage
  on 25 fps frames, and are held for exactly that window;
* the planned video stays under 172 s, inside the gate's 175 s budget;
* the desktop journey presses the same keys, expects the same focus and awaits the
  same answers as the 2026-10-01 take, only regrouped into fewer beats, because no
  browser could be run to probe a different route;
* the compose splices the footage at the start of the content and burns the captions
  on the joined content, so they run on the narration's clock;
* no plan or document claims the video shows no device or emulator.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
VIDEO = REPO / "video"
EMULATOR = "android_tv_emulator"


def _load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, REPO / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


capture = _load("mercury_capture_local", "video/capture-local.py")
compose = _load("mercury_build_video", "video/build-video.py")
narration_generator = _load("mercury_generate_narration", "video/generate-narration.py")

PLAN = json.loads((VIDEO / "narration.json").read_text(encoding="utf-8"))
CUES = json.loads((VIDEO / "cue_sheet.json").read_text(encoding="utf-8"))

#: The desktop presses of the 2026-10-01 take at 9620743: key, expected focus, and a
#: digest of the condition awaited after the press. Frozen from that journey.
MASTER_DESKTOP_PRESSES = [
    ('DOWN', 'Ask about checkout-api', None),
    ('DOWN', 'Ask about payments worker', None),
    ('DOWN', 'Ask about search indexer', None),
    ('DOWN', 'Ask about release train', None),
    ('SELECT', 'Ask about release train', '73ba6bfe2c25eacf'),
    ('UP', 'Ask about search indexer', None),
    ('UP', 'Ask about payments worker', None),
    ('UP', 'Ask about checkout-api', None),
    ('SELECT', 'Ask about checkout-api', 'b716b0aa23f1d70c'),
    ('UP', 'Ask what changed', None),
    ('RIGHT', 'Stage governed rollback', None),
    ('SELECT', 'Stage governed rollback', '5e4bb36a386c5004'),
    ('RIGHT', 'Confirm rollback', None),
    ('SELECT', 'Publish responder handoff', 'a364f1b6d71021e5'),
    ('SELECT', 'Publish responder handoff', '58200ec2dacb8042'),
    ('DOWN', 'Incident evidence panel', None),
    ('RIGHT', 'Delivery velocity panel', None),
    ('SELECT', 'Load DORA velocity', '88e0cc5b0f0cf8b4'),
    ('DOWN', 'Load DORA velocity', None),
    ('BACK', 'Delivery velocity panel', None),
    ('RIGHT', 'Cloud spend panel', None),
    ('SELECT', 'Scan AWS spend', 'f4080c0bd37b936a'),
    ('BACK', 'Cloud spend panel', None),
    ('DOWN', 'How it answers panel', None),
    ('DOWN', 'Check connection', None),
    ('SELECT', 'Check connection', '22bcb81f3c407055'),
]


def _emulator_beats() -> list[dict]:
    return [beat for beat in PLAN["beats"] if beat["source"] == EMULATOR]


# ------------------------------------------------------------------- The plan

def test_the_emulator_footage_opens_the_content():
    sources = [beat["source"] for beat in PLAN["beats"]]
    count = sources.count(EMULATOR)
    assert count >= 1
    assert sources[:count] == [EMULATOR] * count
    assert set(sources[count:]) == {"desktop_capture"}


def test_the_emulator_beats_cover_one_window_of_the_footage_on_frames():
    beats = _emulator_beats()
    windows = [beat["footage_window_seconds"] for beat in beats]
    for before, after in zip(windows, windows[1:]):
        assert before[1] == after[0], "the footage must play once, in order, without a cut"
    for beat, (start, end) in zip(beats, windows):
        assert beat["fixed_hold_seconds"] == pytest.approx(end - start, abs=1e-6)
        for edge in (start, end):
            assert edge * 25 == pytest.approx(round(edge * 25), abs=1e-6), "cuts sit on 25 fps frames"
    assert windows[-1][1] * 25 <= PLAN["emulator_footage"]["frames_at_25_fps"]
    # The idle lead-in is trimmed, but the launch from the home screen stays in.
    assert 0 < windows[0][0] <= 1.5


def test_the_plan_names_the_footage_it_was_cut_for():
    footage = PLAN["emulator_footage"]
    assert footage["workflow_run_url"].endswith("/actions/runs/37475795991")
    assert footage["workflow_sha"].startswith("f423ba5")
    assert footage["public_demo_build_sha"].startswith("ea2cff5")
    assert footage["os_version"] == "Android 14 / API 34"
    assert footage["rollback_dispatch"] == "record-only"


def test_the_planned_video_stays_under_172_seconds():
    content = CUES["total_duration_sec"]
    assert content + compose.TITLE_SECONDS + compose.OUTRO_SECONDS < 172.0


def test_the_emulator_narration_says_what_the_tv_shows():
    spoken = " ".join(beat["caption_text"] for beat in _emulator_beats()).lower()
    for phrase in ["android tv emulator", "home screen", "public demo", "right", "center",
                   "recorded, no pipeline contacted", "record-only", "handoff"]:
        assert phrase in spoken, phrase


def test_the_desktop_part_is_introduced_once_as_the_same_board_at_1080p():
    desktop = [beat for beat in PLAN["beats"] if beat["source"] == "desktop_capture"]
    first = desktop[0]["caption_text"]
    assert "same board" in first and "desktop browser at 1080p" in first
    assert sum("desktop browser" in beat["caption_text"] for beat in PLAN["beats"]) == 1


def test_the_held_out_figures_are_the_ones_the_board_prints():
    from src.infrastructure.trial_summary import naming_accuracy

    accuracy = naming_accuracy()
    captions = " ".join(beat["caption_text"] for beat in PLAN["beats"])
    refused = f"{accuracy['refused_to_name_rate_on_anomalies'] * 100:.1f}%"
    precision = f"{accuracy['precision_when_it_names_a_commit'] * 100:.1f}%"
    assert f"named nobody {refused} of the time" in captions
    assert f"the cause {precision} of the time, over {accuracy['namings_measured']} namings" in captions
    assert f"within {int(accuracy['assumed_delay_ceiling_minutes'])} minutes" in captions
    assert f"{accuracy['namings_measured']} namings, in {accuracy['corpus_cases']} synthetic cases" in captions


# ------------------------------------------------------- No retired claim

RETIRED_CLAIMS = [
    r"no device or emulator",
    r"no (?:device|emulator)(?: run)? (?:is shown|appears)",
    r"shows no emulator",
    r"desktop chromium only",
]


@pytest.mark.parametrize("relative", [
    "video/narration.json", "video/cue_sheet.json", "video/SHOT_LIST.md", "video/README.md",
    "scripts/build_video_plan.py",
])
def test_nothing_claims_the_video_shows_no_device_or_emulator(relative):
    text = " ".join((REPO / relative).read_text(encoding="utf-8").lower().split())
    for pattern in RETIRED_CLAIMS:
        assert not re.search(pattern, text), f"{relative} still says {pattern!r}"


def test_the_documents_say_the_footage_is_not_a_device_or_a_receipt():
    readme = " ".join((VIDEO / "README.md").read_text(encoding="utf-8").split())
    shots = " ".join((VIDEO / "SHOT_LIST.md").read_text(encoding="utf-8").split())
    for text in (readme, shots):
        assert "not a Fire TV device" in text
        assert "android_tv_runtime_receipt.json" in text
        assert "37475795991" in text


# ------------------------------------------------------------ The capture

def _flattened_journey() -> list[tuple]:
    pressed = []
    for beat in capture.EXPECTED_SCENES:
        for _, key, expected, condition in capture.JOURNEY[beat]:
            digest = hashlib.sha256(condition.encode()).hexdigest()[:16] if condition else None
            pressed.append((key, expected, digest))
    return pressed


def test_the_desktop_journey_presses_the_same_keys_as_the_recorded_take():
    assert _flattened_journey() == MASTER_DESKTOP_PRESSES


def test_the_capture_journey_matches_the_plan():
    emulator = [beat["beat_id"] for beat in _emulator_beats()]
    desktop = [beat["beat_id"] for beat in PLAN["beats"] if beat["source"] != EMULATOR]
    assert capture.EMULATOR_SCENES == emulator
    assert capture.EXPECTED_SCENES == desktop
    assert set(capture.JOURNEY) == set(desktop)


def test_the_capture_skips_the_footage_and_starts_at_the_first_desktop_beat():
    scenes = [
        {"id": "beat_01_tv_launch", "source": EMULATOR, "startSeconds": 0.0},
        {"id": "beat_02_tv_board", "source": EMULATOR, "startSeconds": 7.6},
        {"id": "beat_03_tv_stage", "source": EMULATOR, "startSeconds": 13.32},
        {"id": "beat_04_tv_confirm_publish", "source": EMULATOR, "startSeconds": 18.32},
    ] + [
        {"id": beat, "source": "desktop_capture", "startSeconds": 26.64 + i}
        for i, beat in enumerate(capture.EXPECTED_SCENES)
    ]
    desktop, start = capture.desktop_scenes(scenes)
    assert [scene["id"] for scene in desktop] == capture.EXPECTED_SCENES
    assert start == 26.64
    with pytest.raises(SystemExit):
        capture.desktop_scenes(scenes[4:5] + scenes[:4] + scenes[5:])


# ----------------------------------------------------------- The narration

def test_a_footage_beat_is_held_for_its_window_and_refused_if_the_voice_overruns():
    assert narration_generator.beat_hold("d", 10.0, None) == pytest.approx(10.65)
    assert narration_generator.beat_hold("e", 5.387, 5.72) == 5.72
    with pytest.raises(SystemExit):
        narration_generator.beat_hold("e", 7.988, 7.76)


# ------------------------------------------------------------- The compose

def _timing_scenes() -> list[dict]:
    scenes, offset = [], 0.0
    for beat in PLAN["beats"]:
        hold = beat.get("fixed_hold_seconds") or (beat["timestamp_end"] - beat["timestamp_start"])
        scene = {"id": beat["beat_id"], "source": beat["source"], "startSeconds": round(offset, 3),
                 "holdSeconds": round(hold, 3)}
        if "footage_window_seconds" in beat:
            scene["footageWindowSeconds"] = beat["footage_window_seconds"]
        scenes.append(scene)
        offset += hold
    return scenes


def test_the_compose_plays_the_planned_frames_of_the_footage():
    plan = compose.emulator_plan(_timing_scenes())
    first, last = _emulator_beats()[0], _emulator_beats()[-1]
    assert plan["start_frame"] == round(first["footage_window_seconds"][0] * 25)
    assert plan["end_frame"] == round(last["footage_window_seconds"][1] * 25)
    assert plan["seconds"] == pytest.approx(sum(b["fixed_hold_seconds"] for b in _emulator_beats()), abs=0.002)


def test_the_compose_refuses_a_footage_beat_held_off_its_window():
    scenes = _timing_scenes()
    scenes[0]["holdSeconds"] += 0.5
    with pytest.raises(SystemExit):
        compose.emulator_plan(scenes)


def test_the_footage_is_spliced_first_and_the_captions_burned_on_the_joined_content():
    emulator = compose.emulator_plan(_timing_scenes())
    total = CUES["total_duration_sec"]
    graph = compose.content_filters(trim_lead=3.2, narration_total=total, emulator=emulator,
                                    subtitle_path="C\\:/x/captions.en.srt")
    joined = ";".join(graph)
    concat = next(part for part in graph if "concat=n=2" in part)
    assert concat.startswith("[emu][desk]concat=n=2"), "the footage comes before the desktop capture"
    assert joined.count("subtitles=") == 1 and "subtitles=" in concat, \
        "captions are burned once, after the footage and the capture are joined"
    footage = next(part for part in graph if part.startswith("[3:v]"))
    assert footage.startswith("[3:v]fps=25,trim=start_frame="), "converted to 25 fps before it is cut"
    for forbidden in ("setpts=0.", "setpts=2", "tpad", "minterpolate", "atempo"):
        assert forbidden not in footage, "the footage plays at 1x and is never frozen or retimed"
    desktop = next(part for part in graph if part.startswith("[0:v]"))
    assert f"trim=end_frame={round(total * 25) - emulator['frames']}" in desktop


def test_the_label_and_the_cards_name_both_sources():
    provenance = {
        "workflow_run_url": PLAN["emulator_footage"]["workflow_run_url"],
        "os_version": PLAN["emulator_footage"]["os_version"],
        "public_demo_build_sha": PLAN["emulator_footage"]["public_demo_build_sha"],
    }
    facts = compose.footage_facts(provenance)
    assert compose.emulator_label(facts) == (
        "Android TV emulator (API 34), debug APK, public demo build ea2cff5, CI run 37475795991"
    )
    title = " ".join(text for text, *_ in compose.title_lines("9620743", facts))
    assert "Android TV emulator, API 34, CI run 37475795991" in title
    assert "local desktop run of 9620743" in title


def test_the_cards_still_read_as_cards_to_the_gate(tmp_path):
    from PIL import Image, ImageFilter, ImageStat

    if not (compose.FONT_DIR / "segoeui.ttf").exists():
        pytest.skip("the card fonts are Windows fonts")
    facts = {"run_id": "37475795991", "api": "34", "demo_short": "ea2cff5"}
    for name, lines in (("title", compose.title_lines("9620743", facts)),
                        ("outro", compose.outro_lines("9620743", facts))):
        path = tmp_path / f"{name}.png"
        compose.card(path, lines)
        image = Image.open(path).convert("L")
        edge = ImageStat.Stat(image.filter(ImageFilter.FIND_EDGES)).mean[0]
        assert edge < 4.0, f"{name} card edge density {edge:.2f} is too close to the gate's 4.5"
