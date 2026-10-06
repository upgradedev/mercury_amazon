"""Regenerate video/narration.json and video/cue_sheet.json from one beat list.

The two files once described a product that does not exist: an Alexa voice query,
an Echo Show, Datadog and Jira, and a +311% spend figure nobody measured. They are
written here from one list, so the shot list, the narration and the cue sheet
cannot disagree with each other or with the repository.

Each beat carries two texts. ``narration_text`` is what the voice says, with
initialisms spelled out and figures written as words so the text to speech engine
reads them correctly. ``caption_cues`` is what is burned on screen, with the exact
product names and figures, split into the cues that appear one after another; their
joined text is ``caption_text``. ``video/generate-narration.py`` reads both.

A beat may name ``marks``: spoken phrases whose start time the generator reads off
ElevenLabs' character alignment and writes to ``timing.json``. A caption cue that
names a mark starts on that word, so a caption that names a value or a state
appears with the frame that shows it, not before. The capture presses a key on a
mark, so the word naming a press lands with the press.

Each beat also names its ``source``, the picture it plays over:

* ``android_tv_emulator``: the footage the ``android-tv-footage.yml`` workflow filmed
  in CI run 37475795991, the debug APK built at ``f423ba5`` on an AOSP Android TV
  emulator (Android 14, API 34) loading the public demo, build ``ea2cff5``. These
  beats open the content. Their hold is fixed by the footage, not by the voice: each
  beat covers one window of ``journey.mp4`` (``FOOTAGE_CUTS``) plus any hold of a
  static frame inside it (``FOOTAGE_HOLDS``), and the generator refuses a beat whose
  audio does not fit.
* ``desktop_capture``: the local desktop take, recorded by ``video/capture-local.py``
  with the same D-pad bridge. These beats follow the footage.

``seconds`` is each desktop beat's hold in the render: the measured duration of its
synthesized audio plus a fixed 0.65 s tail, as written to ``timing.json`` by
``video/generate-narration.py``. For an emulator beat it is its footage window plus
its holds. Word counts and words per minute are computed here from the text.
"""
import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "video"

#: One neutral English voice for the whole video. The id is ElevenLabs' premade
#: voice "Adam", the default in the submission kit's narration template.
TTS = {
    "provider": "elevenlabs",
    "elevenLabs": {
        "voiceId": "pNInz6obpgDQGcFmaJgB",
        "voiceName": "Adam (ElevenLabs premade)",
        "modelId": "eleven_multilingual_v2",
        "outputFormat": "mp3_44100_128",
    },
}

EMULATOR = "android_tv_emulator"
DESKTOP = "desktop_capture"
FPS = 25

#: The emulator footage this plan was cut against, from footage-provenance.json.
FOOTAGE = {
    "artifact": "mercury-android-tv-footage-f423ba57ecfe688b8dafe899e06ab29dfdb7a90c",
    "workflow_run_url": "https://github.com/upgradedev/mercury_amazon/actions/runs/37475795991",
    "workflow_sha": "f423ba57ecfe688b8dafe899e06ab29dfdb7a90c",
    "public_demo_build_sha": "ea2cff580962f408b17973c0e0b349ada9b6062c",
    "os_version": "Android 14 / API 34",
    "device_model": "AOSP TV on x86",
    "rollback_dispatch": "record-only",
    "file": "journey.mp4",
    "frames_at_25_fps": 691,
}

#: Every frame of journey.mp4, by index: (index, pts in seconds, what is visible).
#: The screenrecord is variable frame rate, 52 frames, and writes a frame only when
#: the screen changes, so each frame stays on screen until the next one. The times
#: were read by index, never by seeking:
#:   ffprobe -v error -select_streams v:0 -show_entries frame=pts_time -of csv=p=0 journey.mp4
#: and each frame was looked at with
#:   ffmpeg -i journey.mp4 -vf "select=eq(n\,I)" -fps_mode passthrough -frames:v 1 fI.png
#: Seeking with -ss lands on a neighbouring frame of this file and has produced false
#: claims before.
FOOTAGE_FRAMES = [
    (0, 0.000, "Leanback home screen"),
    (1, 0.755, "home screen, unchanged to the eye"),
    (2, 1.565, "home screen, unchanged to the eye"),
    (3, 1.783, "home screen, unchanged to the eye"),
    (4, 2.032, "home screen, unchanged to the eye"),
    (5, 2.188, "home screen, unchanged to the eye"),
    (6, 2.402, "home screen, the favourites label redrawn"),
    (7, 2.492, "home screen, unchanged to the eye"),
    (8, 3.994, "home screen, unchanged to the eye"),
    (9, 4.131, "home screen, unchanged to the eye"),
    (10, 4.169, "home screen, its last frame"),
    (11, 4.228, "black: the app cold-starts"),
    (12, 4.390, "black"),
    (13, 4.723, "black"),
    (14, 4.793, "black"),
    (15, 4.883, "black"),
    (16, 4.981, "black"),
    (17, 5.061, "black"),
    (18, 5.109, "black, on screen until the board appears"),
    (19, 8.856, "the board first shows: Not asked, What broke?, API NOT CHECKED"),
    (20, 9.056, "the same board, repainted"),
    (21, 10.074, "CHECKING; focus ring on Ask what changed"),
    (22, 10.277, "CHECKING"),
    (23, 10.428, "API REACHABLE; checkout-api ASKING, call in flight"),
    (24, 11.160, "checkout-api 12.9x, TEMPORAL CANDIDATE, Commit 4f1c2ab; other rows ASKING"),
    (25, 11.282, "payments-worker NOTHING TO REVERT"),
    (26, 11.403, "search-indexer CANNOT ATTRIBUTE"),
    (27, 11.513, "release-train CANNOT ATTRIBUTE"),
    (28, 11.630, "quiet-service INSUFFICIENT DATA: all five rows answered; static until 14.439"),
    (29, 14.439, "Right: focus on Stage rollback"),
    (30, 15.296, "Center: Stage rollback drawn pressed"),
    (31, 15.847, "ROLLBACK STAGED, Roll back to 9b07e3d, lease 300s"),
    (32, 15.879, "lease 300s, focus settles on Stage rollback"),
    (33, 16.901, "lease 299s"),
    (34, 17.691, "lease 298s"),
    (35, 18.600, "lease 297s"),
    (36, 19.907, "lease 296s"),
    (37, 20.110, "Right: focus on Confirm"),
    (38, 20.765, "lease 295s"),
    (39, 21.250, "Center: Confirm drawn pressed; still ROLLBACK STAGED"),
    (40, 21.691, "RECORDED, no pipeline contacted; ROLLBACK RECORDED, NOT SENT"),
    (41, 21.812, "the same, legend Next press: Publish responder handoff; static until 26.290"),
    (42, 26.290, "Center: scrolled to the handoff section, focus on Publish handoff, no handoff yet"),
    (43, 26.588, "the shared handoff: SHARED REVISION 13, HTTP 200 in 210 ms"),
    (44, 26.616, "the same handoff; the page finishes scrolling"),
    (45, 26.791, "the same handoff; the page finishes scrolling"),
    (46, 26.870, "the same handoff; the page finishes scrolling"),
    (47, 26.960, "the same handoff; the page finishes scrolling"),
    (48, 27.086, "the same handoff; the page finishes scrolling"),
    (49, 27.138, "the same handoff; the page finishes scrolling"),
    (50, 27.245, "the same handoff; the page finishes scrolling"),
    (51, 27.434, "the same handoff, the last frame; the clip ends at 27.64 at 25 fps"),
]

#: Cut points in journey.mp4's own clock, in seconds, each on a 25 fps frame, chosen
#: against FOOTAGE_FRAMES and the measured word times of each beat:
#:   0.32  trims the first 0.32 s of the idle home screen, so the launch beat's last
#:         words end at 8.82, before the board first shows at 8.856 (frame 19).
#:   9.96  the board beat starts 0.47 s before ASKING (frame 23, 10.428); its caption
#:         names 12.9x from the spoken "checkout", after frame 24 (11.160).
#:   14.40 "Right" is spoken 0.04 s before focus reaches Stage rollback (frame 29,
#:         14.439); "center" 0.23 s after Stage rollback is drawn pressed (frame 30).
#:   20.28 "Right" is spoken 0.17 s after focus reaches Confirm (frame 37, 20.110);
#:         "center" 0.42 s before Confirm is drawn pressed (frame 39, 21.250); the
#:         RECORDED caption starts on the spoken "Recorded", 0.18 s after frame 40.
#:   26.20 "Center" is spoken 0.09 s before the publish press scrolls the page
#:         (frame 42, 26.290); its caption names the handoff 0.39 s before it shows
#:         (frame 43, 26.588).
#:   27.64 the end of the clip at 25 fps (691 frames; the last frame is 51 at 27.434).
FOOTAGE_CUTS = [0.32, 9.96, 14.40, 20.28, 26.20, 27.64]

#: Holds of a static frame, (footage second, seconds held), each on 25 fps frames.
#: The frame shown just before the hold point is repeated; nothing else is frozen,
#: slowed or sped up. Both sit where the source itself is static:
#:   12.00 inside 11.630 to 14.439, all five rows answered and nothing moving (frame
#:         28), so the board beat's words fit before the Right press.
#:   27.64 the last frame (51), the shared handoff, so the publish beat's words end
#:         over the handoff they name.
FOOTAGE_HOLDS = [(12.00, 1.52), (27.64, 2.52)]

# Each beat: beat_id, source, seconds (desktop: measured audio plus 0.65 s; emulator:
# None, set by the footage), narration_text, caption_cues [[text, mark or None]],
# marks {name: spoken phrase, exact and unique in narration_text}, visual_action.
#
# An emulator beat also records what it was cut against, so the timing can be checked
# without the media (tests/video/test_emulator_open_cut.py):
# * a caption cue's third item is the index of the first frame that shows the value or
#   state it names, or None;
# * ``press_marks`` maps a mark that names a press to the first frame showing that
#   press's effect;
# * ``measured`` is the synthesized audio's length and its marks' start times, read
#   from timing.json as written by video/generate-narration.py on 2026-10-06.
BEATS = [
    {
        "beat_id": "beat_01_tv_launch", "source": EMULATOR, "seconds": None,
        "narration_text": "From the home screen, the debug A P K opens the public demo on an Android TV "
                          "emulator. The screen stays black while it loads.",
        "caption_cues": [
            ["From the home screen, the debug APK opens the public demo on an Android TV emulator.", None, 0],
            ["The screen stays black while it loads.", "black", 11],
        ],
        "marks": {"black": "The screen stays"},
        "measured": {"audio_seconds": 8.499, "marks_seconds": {"black": 6.2}},
        "visual_action": "Emulator footage from 0.32 s of journey.mp4 at 1x: the Leanback home screen "
                         "to 4.169 s (frame 10), then black from 4.228 s (frame 11) while the app "
                         "cold-starts; the board first shows at 8.856 s (frame 19).",
    },
    {
        "beat_id": "beat_02_tv_board", "source": EMULATOR, "seconds": None,
        "narration_text": "The board asks on its own: checkout A P I, twelve point nine times baseline.",
        "caption_cues": [
            ["The board asks on its own:", None, 23],
            ["checkout-api, 12.9x baseline.", "value", 24],
        ],
        "marks": {"asks": "asks", "value": "checkout A P I"},
        "measured": {"audio_seconds": 5.619, "marks_seconds": {"asks": 0.499, "value": 1.95}},
        "visual_action": "Emulator footage from 9.96 s: CHECKING at 10.074 s (frame 21), checkout-api "
                         "ASKING at 10.428 s (frame 23), checkout-api 12.9x, TEMPORAL CANDIDATE, Commit "
                         "4f1c2ab from the demo's invented deploy feed at 11.160 s (frame 24), all five "
                         "rows at 11.630 s (frame 28). That static board is held 1.52 s at 12.00 s.",
    },
    {
        "beat_id": "beat_03_tv_stage", "source": EMULATOR, "seconds": None,
        "narration_text": "Right, then center. A rollback is staged, and its lease counts down.",
        "caption_cues": [
            ["Right, then Center.", None, None],
            ["A rollback is staged, and its lease counts down.", "staged", 31],
        ],
        "marks": {"right": "Right", "center": "center", "staged": "A rollback"},
        "press_marks": {"right": 29, "center": 30},
        "measured": {"audio_seconds": 5.016, "marks_seconds": {"right": 0.0, "center": 1.126, "staged": 2.009}},
        "visual_action": "Emulator footage from 14.40 s: D-pad Right moves focus to Stage rollback at "
                         "14.439 s (frame 29), Center at 15.296 s (frame 30), ROLLBACK STAGED with a "
                         "300 s lease at 15.847 s (frame 31), counting down to 296 s.",
    },
    {
        "beat_id": "beat_04_tv_confirm", "source": EMULATOR, "seconds": None,
        "narration_text": "Right, then center confirms. Recorded, no pipeline contacted: this demo is "
                          "record only.",
        "caption_cues": [
            ["Right, then Center confirms.", None, None],
            ["RECORDED, no pipeline contacted: this demo is record-only.", "recorded", 40],
        ],
        "marks": {"right": "Right", "center": "center", "recorded": "Recorded"},
        "press_marks": {"right": 37, "center": 39},
        "measured": {"audio_seconds": 5.341, "marks_seconds": {"right": 0.0, "center": 0.546, "recorded": 1.591}},
        "visual_action": "Emulator footage from 20.28 s: focus on Confirm since 20.110 s (frame 37), "
                         "Center at 21.250 s (frame 39), RECORDED, no pipeline contacted at 21.691 s "
                         "(frame 40), static on the board until 26.290 s.",
    },
    {
        "beat_id": "beat_05_tv_publish", "source": EMULATOR, "seconds": None,
        "narration_text": "Center publishes the handoff: shared revision thirteen.",
        "caption_cues": [
            ["Center publishes the handoff:", None, 43],
            ["SHARED REVISION 13.", "revision", 43],
        ],
        "marks": {"center": "Center", "revision": "shared revision"},
        "press_marks": {"center": 42},
        "measured": {"audio_seconds": 3.622, "marks_seconds": {"center": 0.0, "revision": 1.741}},
        "visual_action": "Emulator footage from 26.20 s to the end: Center scrolls to the handoff with "
                         "focus on Publish handoff at 26.290 s (frame 42), the shared handoff, SHARED "
                         "REVISION 13, HTTP 200 at 26.588 s (frame 43). The last frame is held 2.52 s.",
    },
    {
        "beat_id": "beat_06_desktop_board", "source": DESKTOP, "seconds": 12.028,
        "narration_text": "The rest is the same board, run locally from this commit in a desktop browser "
                          "at ten eighty p. Mercury names a commit only when exactly one runtime change "
                          "landed before the spike.",
        "caption_cues": [
            ["The rest is the same board, run locally from this commit in a desktop browser at 1080p.", None],
            ["Mercury names a commit only when exactly one runtime change landed before the spike.", None],
        ],
        "visual_action": "The desktop take begins: the loaded board in desktop Chromium at 1920x1080 "
                         "CSS (the desktop layout, not the Fire TV WebView's 960x540), focus on Ask "
                         "what changed. No key pressed.",
    },
    {
        "beat_id": "beat_07_board_on_load", "source": DESKTOP, "seconds": 18.019,
        "narration_text": "It answered on load, before any key was pressed. Most answers are refusals: on "
                          "generated cases held out from tuning, it saw a real anomaly and named nobody "
                          "ninety percent of the time. A refusal never calls the deploy innocent.",
        "caption_cues": [
            ["It answered on load, before any key was pressed.", None],
            ["Most answers are refusals: on generated cases held out from tuning, it saw a real "
             "anomaly and named nobody 90.0% of the time.", None],
            ["A refusal never calls the deploy innocent.", None],
        ],
        "visual_action": "Hold on the board. The five rows read Temporal candidate, Nothing to revert, "
                         "Cannot attribute, Cannot attribute and Insufficient data, each from the "
                         "server's answer.",
    },
    {
        "beat_id": "beat_08_crowded_refusal", "source": DESKTOP, "seconds": 17.554,
        "narration_text": "Down walks the rows. Release train shows a spike well above its baseline, but "
                          "several runtime changes landed in the window before it, and no metric says "
                          "which one did it. Mercury cannot attribute this, and offers no rollback. "
                          "Rolling back would be a guess.",
        "caption_cues": [
            ["Down walks the rows.", None],
            ["release-train shows a spike well above its baseline, but several runtime changes "
             "landed in the window before it, and no metric says which one did it.", None],
            ["Mercury cannot attribute this, and offers no rollback.", None],
            ["Rolling back would be a guess.", None],
        ],
        "visual_action": "D-pad Down four times to release-train, then Center, all before the second "
                         "caption. The verdict reads Cannot attribute this with the number of changes "
                         "that landed, Next reads No rollback offered, and Stage rollback and Confirm "
                         "are disabled.",
    },
    {
        "beat_id": "beat_09_named_with_odds", "source": DESKTOP, "seconds": 19.783,
        "narration_text": "On checkout A P I, exactly one runtime change landed before the spike, so "
                          "Mercury names it, and prints its own odds: on held-out generated cases a named "
                          "commit is the cause fifty percent of the time, over fifty eight namings, if a "
                          "fault shows within seventy five minutes.",
        "caption_cues": [
            ["On checkout-api,", None],
            ["exactly one runtime change landed before the spike, so Mercury names it, and prints "
             "its own odds:", None],
            ["on held-out generated cases a named commit is the cause 50.0% of the time, over 58 "
             "namings, if a fault shows within 75 minutes.", None],
        ],
        "visual_action": "D-pad Up three times to checkout-api, then Center, inside the first caption. "
                         "The verdict names the commit as the only runtime change, quotes its message, "
                         "and reads 50.0% held-out precision (synthetic, ≤75m lag).",
    },
    {
        "beat_id": "beat_10_provenance", "source": DESKTOP, "seconds": 10.635,
        "narration_text": "The reading and the commit each carry a stamp. The metric is an offline "
                          "fixture, generated locally. The commit is one of Mercury's own, standing in "
                          "for a deploy feed.",
        "caption_cues": [
            ["The reading and the commit each carry a stamp.", None],
            ["The metric is an offline fixture, generated locally.", None],
            ["The commit is one of Mercury's own, standing in for a deploy feed.", None],
        ],
        "visual_action": "Hold on the OFFLINE FIXTURE stamp under the reading and the dashed STAND-IN "
                         "stamp against Mercury's commits. No key pressed. (The public demo in the "
                         "emulator footage names a deploy from an invented feed instead.)",
    },
    {
        "beat_id": "beat_11_stage_to_evidence", "source": DESKTOP, "seconds": 16.904,
        "narration_text": "Up, right, center: the rollback is staged. Right, center confirms it, and the "
                          "board holds recorded, not sent. Center publishes the handoff. Down shows the "
                          "evidence behind the odds: fifty eight namings, in eleven hundred sixty "
                          "synthetic cases.",
        "caption_cues": [
            ["Up, Right, Center:", None],
            ["the rollback is staged.", "staged"],
            ["Right, Center confirms it,", "confirm_right"],
            ["and the board holds RECORDED, not sent.", "recorded"],
            ["Center publishes the handoff.", "publish"],
            ["Down shows the evidence behind the odds: 58 namings, in 1160 synthetic cases.", "down"],
        ],
        "marks": {
            "up": "Up,", "stage_right": "right,", "stage_center": "center:", "staged": "the rollback",
            "confirm_right": "Right,", "confirm_center": "center confirms", "recorded": "and the board",
            "publish": "Center publishes", "down": "Down shows",
        },
        "visual_action": "Each press on its spoken word. Up, Right to Stage rollback, Center: Rollback "
                         "staged. Right to Confirm, Center: nothing scrolls, the large figure reads "
                         "RECORDED, no pipeline contacted, and the legend reads Next press: Publish "
                         "responder handoff. Center publishes: HTTP 200, the handoff's responder, facts "
                         "and next step clear the key bar under the rollback steps. Down lands on "
                         "Incident evidence: 50.0% over 58 namings in 1160 synthetic labelled cases.",
    },
    {
        "beat_id": "beat_12_dpad", "source": DESKTOP, "seconds": 12.167,
        "narration_text": "The ring jumps to the nearest control in the direction pressed, and the label "
                          "at the bottom right names it. Center opens delivery velocity, and Back now "
                          "reads: back to the wall.",
        "caption_cues": [
            ["The ring jumps to the nearest control in the direction pressed, and the label at the "
             "bottom right names it.", None],
            ["Center opens Delivery velocity, and BACK now reads: Back to the wall.", None],
        ],
        "visual_action": "D-pad Right to Delivery velocity, Center. The panel opens and the BACK legend "
                         "changes from Exit to the Fire TV launcher to Back to the wall.",
    },
    {
        "beat_id": "beat_13_fixtures", "source": DESKTOP, "seconds": 12.585,
        "narration_text": "Its answer is a recording, stamped offline fixture, because no GitHub token is "
                          "set. Back returns to the wall, not out of the app. Cloud spend is a fixture "
                          "too, marked synthetic.",
        "caption_cues": [
            ["Its answer is a recording, stamped OFFLINE FIXTURE, because no GitHub token is set.", None],
            ["BACK returns to the wall, not out of the app.", None],
            ["Cloud spend is a fixture too, marked SYNTHETIC.", None],
        ],
        "visual_action": "D-pad Down scrolls the rest of the DORA answer into view with its OFFLINE "
                         "FIXTURE stamp; the cursor stays in the panel. Back returns to the wall and the "
                         "legend changes back. Right to Cloud spend and Center before the third caption: "
                         "the spend answer carries OFFLINE FIXTURE and says its figures are SYNTHETIC. "
                         "Back to the wall.",
    },
    {
        "beat_id": "beat_14_build_check", "source": DESKTOP, "seconds": 12.817,
        "narration_text": "Down, down, center: the server reports its build, the commit on the opening "
                          "card, in fixture mode. The emulator footage came from C I, not a Fire TV device.",
        "caption_cues": [
            ["Down, Down, Center:", None],
            ["the server reports its build, the commit on the opening card, in fixture mode.", "build"],
            ["The emulator footage came from CI, not a Fire TV device.", "footage"],
        ],
        "marks": {"down": "Down,", "down_again": "down,", "center": "center:", "build": "the server",
                  "footage": "The emulator"},
        "visual_action": "Down to How it answers, Down to Check, Center, each on its spoken word. The "
                         "connection line reads GET /health returned 200, the build's short SHA, and "
                         "GitHub live: no, fixture mode.",
    },
]

STATUS = (
    "RENDERED LOCALLY, NOT UPLOADED. This plan is for the next take. Its content opens on "
    "Android TV emulator footage from CI run 37475795991: the debug APK built at f423ba5 on "
    "an AOSP Android TV emulator, Android 14 / API 34, loading the public demo (build "
    "ea2cff5, record-only), at 1x, with two holds of a static frame. That is footage, not a "
    "Fire TV device and not a runtime receipt; the Android TV emulator runtime receipt is a "
    "separate file, android_tv_runtime_receipt.json. The rest is a local run of this "
    "repository in desktop Chromium at 1920x1080 CSS (the desktop layout, not the Fire TV "
    "WebView's 960x540 CSS) with MERCURY_OFFLINE=1, driven through the D-pad bridge the "
    "Leanback app calls. An emulator beat's seconds are its footage window plus its holds; "
    "a desktop beat's seconds are its measured hold, the length of its synthesized audio "
    "plus a 0.65 s tail, from video/generate-narration.py. The media lives outside the "
    "repository; video/README.md says where. The event FAQ permits the Android TV Emulator "
    "and does not require physical hardware."
)


def on_frame(seconds: float) -> bool:
    return abs(seconds * FPS - round(seconds * FPS)) < 1e-6


def static_hold(at: float) -> bool:
    """A hold at ``at`` repeats the source frame on screen just before it; that frame
    must stay on screen at least a second in the source, or be the last frame."""
    shown = [frame for frame in FOOTAGE_FRAMES if frame[1] < at]
    if not shown:
        return False
    index = shown[-1][0]
    if index == FOOTAGE_FRAMES[-1][0]:
        return True
    return FOOTAGE_FRAMES[index + 1][1] - FOOTAGE_FRAMES[index][1] >= 1.0


def footage_windows() -> dict[str, dict[str, object]]:
    """Each emulator beat's window in journey.mp4 and the holds inside it."""
    emulator = [beat["beat_id"] for beat in BEATS if beat["source"] == EMULATOR]
    if len(emulator) != len(FOOTAGE_CUTS) - 1:
        raise SystemExit("every emulator beat needs exactly one footage window")
    for cut in FOOTAGE_CUTS:
        if not on_frame(cut):
            raise SystemExit(f"cut {cut} is not on a 25 fps frame")
    windows = {}
    for i, beat_id in enumerate(emulator):
        first, last = FOOTAGE_CUTS[i], FOOTAGE_CUTS[i + 1]
        holds = [[at, seconds] for at, seconds in FOOTAGE_HOLDS if first < at <= last]
        windows[beat_id] = {"window": [first, last], "holds": holds}
    placed = sum(len(item["holds"]) for item in windows.values())
    if placed != len(FOOTAGE_HOLDS):
        raise SystemExit("every hold must sit inside one emulator beat's window")
    for at, seconds in FOOTAGE_HOLDS:
        if not (on_frame(at) and on_frame(seconds)) or seconds <= 0:
            raise SystemExit(f"hold {at}, {seconds} is not on 25 fps frames")
        if not static_hold(at):
            raise SystemExit(f"hold at {at} does not repeat a static frame")
    return windows


def main() -> None:
    windows = footage_windows()
    sources = [beat["source"] for beat in BEATS]
    if sources != sorted(sources, key=lambda source: source != EMULATOR):
        raise SystemExit("the emulator beats must open the content, before any desktop beat")
    if FOOTAGE_CUTS[-1] * FPS > FOOTAGE["frames_at_25_fps"] + 1e-6:
        raise SystemExit("the last cut is past the end of the footage")
    if len(FOOTAGE_FRAMES) != 52 or [frame[0] for frame in FOOTAGE_FRAMES] != list(range(52)):
        raise SystemExit("the frame table must list all 52 frames by index")

    narration_beats = []
    cue_beats = []
    start = 0.0
    for index, beat in enumerate(BEATS, start=1):
        beat_id, source, text = beat["beat_id"], beat["source"], beat["narration_text"]
        seconds = beat["seconds"]
        marks = beat.get("marks", {})
        for name, phrase in marks.items():
            if text.count(phrase) != 1:
                raise SystemExit(f"{beat_id}: mark {name} must name a phrase spoken exactly once")
        for cue in beat["caption_cues"]:
            mark = cue[1]
            if mark is not None and mark not in marks:
                raise SystemExit(f"{beat_id}: caption cue names an unknown mark {mark}")
        if beat["caption_cues"][0][1] is not None:
            raise SystemExit(f"{beat_id}: the first caption cue starts with the beat")
        if source == EMULATOR:
            window = windows[beat_id]
            first, last = window["window"]
            seconds = round(last - first + sum(hold for _, hold in window["holds"]), 3)
        end = round(start + seconds, 3)
        caption = " ".join(cue[0] for cue in beat["caption_cues"])
        words = len(text.split())
        entry = {
            "beat_id": beat_id,
            "source": source,
            "timestamp_start": start,
            "timestamp_end": end,
            "narration_text": text,
            "caption_text": caption,
            "caption_cues": beat["caption_cues"],
            "visual_action": beat["visual_action"],
        }
        if marks:
            entry["marks"] = marks
        for key in ("press_marks", "measured"):
            if key in beat:
                entry[key] = beat[key]
        if source == EMULATOR:
            entry["fixed_hold_seconds"] = seconds
            entry["footage_window_seconds"] = list(windows[beat_id]["window"])
            entry["footage_holds_seconds"] = windows[beat_id]["holds"]
        narration_beats.append(entry)
        cue_beats.append({
            "beat_index": index,
            "beat_id": beat_id,
            "source": source,
            "timestamp_start": start,
            "timestamp_end": end,
            "duration_sec": round(seconds, 3),
            "words_count": words,
            "words_per_minute": round(words / seconds * 60.0, 1) if seconds else None,
            "narration_text": text,
            "visual_action": beat["visual_action"],
        })
        start = end

    total = start

    narration = {
        "schema": "mercury.video_narration/1",
        "status": STATUS,
        "project": "mercury_amazon",
        "title": "Mercury: Fire TV incident board",
        "source_of_truth": "scripts/build_video_plan.py",
        "tts": TTS,
        "emulator_footage": FOOTAGE,
        "target_duration_seconds": total,
        "max_allowed_seconds": 180.0,
        "beats": narration_beats,
    }

    cue_sheet = {
        "schema": "mercury.video_plan/1",
        "status": STATUS,
        "project": "mercury_amazon",
        "title": "Mercury: Fire TV incident board",
        "source_of_truth": "scripts/build_video_plan.py",
        "generated_by_command": "python scripts/build_video_plan.py",
        "note": (
            "words_count and words_per_minute are computed from narration_text by the "
            "generator. duration_sec is the beat's hold in the render: for an "
            "android_tv_emulator beat its window of the CI footage plus its holds of a "
            "static frame, for a desktop_capture beat the measured audio length plus a "
            "0.65 s tail. total_duration_sec is the content only; the title card (4 s) and "
            "the closing card (3 s) are added by video/build-video.py."
        ),
        "emulator_footage": FOOTAGE,
        "emulator_footage_frames": [list(frame) for frame in FOOTAGE_FRAMES],
        "total_duration_sec": total,
        "max_allowed_seconds": 180.0,
        "beats": cue_beats,
    }

    (OUT / "narration.json").write_text(json.dumps(narration, indent=2) + "\n", encoding="utf-8")
    (OUT / "cue_sheet.json").write_text(json.dumps(cue_sheet, indent=2) + "\n", encoding="utf-8")
    print("total", total, "with cards", round(total + 7.0, 3), "beats", len(BEATS),
          "words", sum(len(b["narration_text"].split()) for b in BEATS))
    rates = [b["words_per_minute"] for b in cue_beats if b["words_per_minute"]]
    print("wpm range", min(rates), max(rates))


if __name__ == "__main__":
    main()
