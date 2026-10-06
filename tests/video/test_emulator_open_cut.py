"""The next take opens on the Android TV emulator footage, and stays truthful.

These tests read the plan, the capture journey and the compose graph without a
browser, a server, a key or a render:

* the emulator beats open the content, cover one unbroken window of the CI footage
  on 25 fps frames at 1x, and are held for exactly that window plus holds of frames
  that are static in the source;
* the footage starts on the board: the home screen and the black cold start are not
  shown, because CI launched the app by intent, not with a D-pad press on a tile;
* a label stamps the footage's invented commits, and another names the desktop
  browser on every desktop frame;
* the frame table the cuts were read from lists all 52 frames by index, and no
  caption or spoken press runs ahead of the frame it names by more than half a second;
* the planned video stays under 172 s, inside the gate's 175 s budget;
* the desktop journey presses the same keys, expects the same focus and awaits the
  same answers as the 2026-10-01 take, only regrouped into fewer beats, because no
  browser could be run to probe a different route;
* the compose splices the footage at the start of the content and burns the captions
  on the joined content, so they run on the narration's clock;
* the compose imports Pillow only where it draws a card, so this module loads where
  Pillow is not installed;
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
plan_builder = _load("mercury_build_video_plan", "scripts/build_video_plan.py")

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
        holds = beat["footage_holds_seconds"]
        assert beat["fixed_hold_seconds"] == pytest.approx(end - start + sum(h for _, h in holds), abs=1e-6)
        for edge in (start, end) + tuple(value for hold in holds for value in hold):
            assert edge * 25 == pytest.approx(round(edge * 25), abs=1e-6), "cuts and holds sit on 25 fps frames"
        for at, _ in holds:
            assert start < at <= end
    assert windows[-1][1] * 25 <= PLAN["emulator_footage"]["frames_at_25_fps"]
    # The footage opens on the board as it first shows (frame 19), never before it.
    assert FRAMES[19][0] <= windows[0][0] < FRAMES[20][0]


# --------------------------------------------------------- Frame truth

FRAMES = {index: (pts, seen) for index, pts, seen in plan_builder.FOOTAGE_FRAMES}


def test_the_frame_table_lists_every_frame_by_index():
    assert sorted(FRAMES) == list(range(52))
    times = [FRAMES[index][0] for index in range(52)]
    assert times == sorted(times) and len(set(times)) == 52
    # Verified by index on 2026-10-06; seeking with -ss returns a neighbouring frame.
    assert FRAMES[39][0] == 21.250 and "still ROLLBACK STAGED" in FRAMES[39][1]
    assert FRAMES[40][0] == 21.691 and FRAMES[40][1].startswith("RECORDED")
    assert FRAMES[41][0] == 21.812 and FRAMES[41][1].startswith("the same")
    assert FRAMES[42][0] == 26.290 and "focus on Publish handoff" in FRAMES[42][1]
    assert FRAMES[43][0] == 26.588 and "SHARED REVISION 13" in FRAMES[43][1]
    assert FRAMES[11][0] == 4.228 and FRAMES[11][1].startswith("black")
    assert FRAMES[19][0] == 8.856 and "first shows" in FRAMES[19][1]


def test_every_hold_repeats_a_frame_the_source_shows_still():
    for at, _ in plan_builder.FOOTAGE_HOLDS:
        assert plan_builder.static_hold(at), at
    assert not plan_builder.static_hold(21.70), "a frame the source replaces within a second"


def _footage_time(beat: dict, seconds: float) -> float:
    """The footage second on screen ``seconds`` into an emulator beat."""
    first, _ = beat["footage_window_seconds"]
    at = first + seconds
    for hold_at, held in beat["footage_holds_seconds"]:
        if at <= hold_at:
            break
        at = max(hold_at, at - held)
    return at


def test_no_caption_names_a_value_before_its_frame():
    for beat in _emulator_beats():
        marks = beat["measured"]["marks_seconds"]
        for text, mark, shows in beat["caption_cues"]:
            if shows is None:
                continue
            start = _footage_time(beat, marks[mark] if mark else 0.0)
            lead = FRAMES[shows][0] - start
            assert lead <= 0.5, f"{text!r} appears {lead:.2f} s before frame {shows}"


def test_every_spoken_press_lands_with_its_effect():
    pressed = 0
    for beat in _emulator_beats():
        marks = beat["measured"]["marks_seconds"]
        for mark, frame in beat.get("press_marks", {}).items():
            spoken = _footage_time(beat, marks[mark])
            assert abs(spoken - FRAMES[frame][0]) <= 0.5, f"{beat['beat_id']} {mark}"
            pressed += 1
    assert pressed == 5


def test_the_take_shows_no_launch_and_no_black_screen():
    # CI started the app with an am start of its LEANBACK_LAUNCHER intent, so no
    # frame shows a D-pad press on a tile. The take shows neither the home screen nor
    # the cold start's black, and no caption claims a launch.
    assert plan_builder.first_frame_shown() == plan_builder.FIRST_SHOWN_FRAME == 19
    assert "first shows" in FRAMES[19][1]
    assert all(not FRAMES[i][1].startswith("black") for i in range(19, 52))
    spoken = " ".join(beat["caption_text"] for beat in _emulator_beats()).lower()
    for phrase in ("home screen", "black", "launch", "opens the"):
        assert phrase not in spoken, phrase


def test_each_emulator_beat_fits_its_measured_words():
    for beat in _emulator_beats():
        assert beat["measured"]["audio_seconds"] + 0.3 <= beat["fixed_hold_seconds"] + 1e-9


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
    for phrase in ["android tv emulator", "public demo", "right", "center",
                   "recorded, no pipeline contacted", "record-only", "handoff"]:
        assert phrase in spoken, phrase


def test_the_cut_to_the_desktop_says_what_changes():
    # At the cut the named commit, the rollback target and the handoff revision all
    # change; the first desktop caption says why.
    desktop = [beat for beat in PLAN["beats"] if beat["source"] == "desktop_capture"]
    first = desktop[0]["caption_text"]
    assert "same board in a desktop browser" in first and "run locally from this commit" in first
    assert "own fixtures, so the commits differ" in first and "revision 1" in first
    assert sum("desktop browser" in beat["caption_text"] for beat in PLAN["beats"]) == 1
    provenance = [beat for beat in desktop if beat["beat_id"] == "beat_09_provenance"][0]
    assert provenance["caption_text"].startswith("On this board, the reading and the commit")


def test_the_footage_label_stamps_the_invented_commits():
    commits = PLAN["emulator_footage"]["fixture_commits"]
    feed_path = REPO / "src" / "infrastructure" / "fixtures" / "deploy_feed_fixture.json"
    feed = json.loads(feed_path.read_text(encoding="utf-8"))
    assert "INVENTED" in feed["note"]
    assert set(commits.values()) <= {deploy["sha"] for deploy in feed["deploys"]}
    assert commits == {"named": "4f1c2ab", "rollback_target": "9b07e3d"}
    facts = compose.footage_facts({
        "workflow_run_url": PLAN["emulator_footage"]["workflow_run_url"],
        "os_version": PLAN["emulator_footage"]["os_version"],
        "public_demo_build_sha": PLAN["emulator_footage"]["public_demo_build_sha"],
    })
    lines = compose.emulator_label_lines(facts, commits)
    assert lines[0] == compose.emulator_label(facts)
    assert lines[1] == ("Commits 4f1c2ab and 9b07e3d are invented records from the demo's fixture feed, "
                        "not real deploys.")


def test_every_desktop_frame_carries_the_desktop_label():
    lines = compose.desktop_label_lines("9620743")
    assert lines[0].startswith("Desktop browser at 1920x1080, local run of 9620743")
    assert "Not the TV." in lines[0] and "Fire TV build's" in lines[1]
    graph = ";".join(compose.content_filters(
        trim_lead=3.2, narration_total=CUES["total_duration_sec"],
        emulator=compose.emulator_plan(_timing_scenes()), subtitle_path="C\\:/x/captions.en.srt"))
    assert "[deskbase][desklabel]overlay=0:0:shortest=1" in graph
    assert "[emubase][emulabel]overlay=0:0:shortest=1" in graph
    # The labels sit between the picture and the two-line caption band (from y=975).
    assert compose.LABEL_Y >= compose.PIC_Y + compose.PIC_H
    assert compose.LABEL_Y + 2 * compose.LABEL_LINE_SPACING <= 970


def test_the_held_out_figures_are_the_ones_the_board_prints():
    from src.infrastructure.trial_summary import naming_accuracy

    accuracy = naming_accuracy()
    captions = " ".join(beat["caption_text"] for beat in PLAN["beats"])
    precision = f"{accuracy['precision_when_it_names_a_commit'] * 100:.1f}%"
    namings = f"{accuracy['namings_measured']} namings"
    assert f"the cause {precision} of the time, if a fault shows" in captions
    assert f"within {int(accuracy['assumed_delay_ceiling_minutes'])} minutes" in captions
    assert f"{namings}, in {accuracy['corpus_cases']} synthetic cases" in captions
    # A figure is named only over the frames that show it: the refusal rate never
    # appears on the board, and the namings count only on the evidence panel, which
    # the Down press in the stage-to-evidence beat opens.
    refused = f"{accuracy['refused_to_name_rate_on_anomalies'] * 100:.1f}%"
    assert refused not in captions and "named nobody" not in captions
    assert captions.count(namings) == 1
    evidence = [beat for beat in PLAN["beats"] if namings in beat["caption_text"]]
    assert [beat["beat_id"] for beat in evidence] == ["beat_10_stage_to_evidence"]
    cue = [c for c in evidence[0]["caption_cues"] if namings in c[0]][0]
    assert cue[1] == "down"


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
        {"id": beat, "source": EMULATOR, "startSeconds": float(i)}
        for i, beat in enumerate(capture.EMULATOR_SCENES)
    ] + [
        {"id": beat, "source": "desktop_capture", "startSeconds": 31.36 + i}
        for i, beat in enumerate(capture.EXPECTED_SCENES)
    ]
    count = len(capture.EMULATOR_SCENES)
    desktop, start = capture.desktop_scenes(scenes)
    assert [scene["id"] for scene in desktop] == capture.EXPECTED_SCENES
    assert start == 31.36
    with pytest.raises(SystemExit):
        capture.desktop_scenes(scenes[count:count + 1] + scenes[:count] + scenes[count + 1:])


def test_a_press_on_a_spoken_mark_lands_on_that_word():
    scene = {"id": "beat_x", "sentenceStartsSeconds": [0.0, 2.5], "marksSeconds": {"center": 1.25}}
    assert capture.planned_offset(scene, 0.4) == 0.4
    assert capture.planned_offset(scene, ("sentence", 1, -0.4)) == pytest.approx(2.1)
    assert capture.planned_offset(scene, ("mark", "center", -0.25)) == pytest.approx(1.0)
    with pytest.raises(SystemExit):
        capture.planned_offset(scene, ("mark", "right", 0.0))
    marked = {beat["beat_id"]: set(beat.get("marks", {})) for beat in PLAN["beats"]}
    for beat_id, steps in capture.JOURNEY.items():
        for when, *_ in steps:
            if isinstance(when, tuple) and when[0] == "mark":
                assert when[1] in marked[beat_id], (beat_id, when)


def test_the_take_is_the_desktop_layout_and_the_tv_layout_is_described():
    assert capture.DEFAULT_VIEWPORT == "desktop"
    assert capture.VIEWPORTS["desktop"] == {"width": 1920, "height": 1080, "scale": 1, "host": False}
    assert capture.VIEWPORTS["tv"] == {"width": 960, "height": 540, "scale": 2, "host": True}
    assert "MercuryHost" in capture.HOST_STUB


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
            scene["footageHoldsSeconds"] = beat["footage_holds_seconds"]
        scenes.append(scene)
        offset += hold
    return scenes


def test_the_compose_plays_the_planned_frames_of_the_footage():
    plan = compose.emulator_plan(_timing_scenes())
    first, last = _emulator_beats()[0], _emulator_beats()[-1]
    assert plan["start_frame"] == round(first["footage_window_seconds"][0] * 25)
    assert plan["end_frame"] == round(last["footage_window_seconds"][1] * 25)
    assert plan["seconds"] == pytest.approx(sum(b["fixed_hold_seconds"] for b in _emulator_beats()), abs=0.002)
    pieces = plan["pieces"]
    assert pieces[0]["start_frame"] == plan["start_frame"] and pieces[-1]["end_frame"] == plan["end_frame"]
    for before, after in zip(pieces, pieces[1:]):
        assert before["end_frame"] == after["start_frame"], "every frame plays once, in order"
    held = [(piece["end_frame"] / 25, piece["hold_frames"] / 25) for piece in pieces if piece["hold_frames"]]
    assert held == [pytest.approx(hold) for hold in plan_builder.FOOTAGE_HOLDS]


def test_the_compose_refuses_a_footage_beat_held_off_its_window():
    scenes = _timing_scenes()
    scenes[0]["holdSeconds"] += 0.5
    with pytest.raises(SystemExit):
        compose.emulator_plan(scenes)
    scenes = _timing_scenes()
    scenes[0]["footageHoldsSeconds"] = [[scenes[0]["footageWindowSeconds"][1] + 1.0, 0.4]]
    scenes[0]["holdSeconds"] += 0.4
    with pytest.raises(SystemExit):
        compose.emulator_plan(scenes)


def test_the_footage_is_spliced_first_and_the_captions_burned_on_the_joined_content():
    emulator = compose.emulator_plan(_timing_scenes())
    total = CUES["total_duration_sec"]
    graph = compose.content_filters(trim_lead=3.2, narration_total=total, emulator=emulator,
                                    subtitle_path="C\\:/x/captions.en.srt")
    joined = ";".join(graph)
    concat = next(part for part in graph if "[emu]" in part and "[desk]" in part and "concat=n=2" in part)
    assert concat.startswith("[emu][desk]concat=n=2"), "the footage comes before the desktop capture"
    assert joined.count("subtitles=") == 1 and "subtitles=" in concat, \
        "captions are burned once, after the footage and the capture are joined"
    footage = [part for part in graph if part.startswith(("[3:v]", "[fp"))]
    assert footage[0].startswith("[3:v]fps=25,split="), "converted to 25 fps before it is cut"
    for part in footage:
        for forbidden in ("setpts=0.", "setpts=2", "minterpolate", "atempo", "setpts=PTS*", "setpts=PTS/"):
            assert forbidden not in part, "the footage plays at 1x and is never retimed"
    pieces = [part for part in footage if part.startswith("[fp")]
    assert len(pieces) == len(emulator["pieces"])
    for part, piece in zip(pieces, emulator["pieces"]):
        assert f"trim=start_frame={piece['start_frame']}:end_frame={piece['end_frame']}" in part
        if piece["hold_frames"]:
            assert part.endswith(f"tpad=stop_mode=clone:stop={piece['hold_frames']}[fq{pieces.index(part)}]")
        else:
            assert "tpad" not in part
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
    assert "Android TV emulator footage, API 34, CI run 37475795991" in title
    assert "local run of 9620743 in a desktop browser at 1920x1080, not the TV layout" in title
    outro = " ".join(text for text, *_ in compose.outro_lines("9620743", facts))
    assert "Desktop browser at 1920x1080" in outro


def test_the_compose_loads_without_pillow_and_checks_its_cards_when_it_draws_them():
    source = (VIDEO / "build-video.py").read_text(encoding="utf-8")
    top = source.split("\ndef ", 1)[0]
    assert "from PIL" not in top and "import PIL" not in top, "Pillow is imported where a card is drawn"
    assert compose.CARD_EDGE_CEILING < 4.5
    assert "card_edge_density(path)" in source and "CARD_EDGE_CEILING" in source.split("def main()", 1)[1]
