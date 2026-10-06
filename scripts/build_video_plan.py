"""Regenerate video/narration.json and video/cue_sheet.json from one beat list.

The two files once described a product that does not exist: an Alexa voice query,
an Echo Show, Datadog and Jira, and a +311% spend figure nobody measured. They are
written here from one list, so the shot list, the narration and the cue sheet
cannot disagree with each other or with the repository.

Each beat carries two texts. ``narration_text`` is what the voice says, with
initialisms spelled out and figures written as words so the text to speech engine
reads them correctly. ``caption_text`` is what is burned on screen, with the exact
product names and figures. ``video/generate-narration.py`` reads both.

Each beat also names its ``source``, the picture it plays over:

* ``android_tv_emulator``: the footage the ``android-tv-footage.yml`` workflow filmed
  in CI run 37475795991, the debug APK built at ``f423ba5`` on an AOSP Android TV
  emulator (Android 14, API 34) loading the public demo, build ``ea2cff5``. These
  beats open the content. Their hold is fixed by the footage, not by the voice: each
  beat covers one window of ``journey.mp4`` (``FOOTAGE_CUTS``, read off its frames),
  and the generator refuses a beat whose audio does not fit its window.
* ``desktop_capture``: the local desktop take, recorded by ``video/capture-local.py``
  with the same D-pad bridge. These beats follow the footage.

The desktop beat order follows what the D-pad actually brings on screen in the page,
probed against a local server on 2026-09-26, not an earlier plan.

``seconds`` is each beat's hold in the render. For a desktop beat it is the measured
duration of its synthesized audio plus a fixed 0.65 s tail, as written to
``timing.json`` by ``video/generate-narration.py``. For an emulator beat it is the
footage window. Word counts and words per minute are computed here from the text,
not typed in.
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

#: Cut points in journey.mp4's own clock, in seconds, each on a 25 fps frame. Read
#: off the frames of the screenrecord (its frame times, ffprobe):
#:   0.00 to 4.23   the Leanback home screen (the launch intent is issued near 1.9 s)
#:   4.23 to 8.86   black while the app cold-starts and the WebView loads the demo
#:   8.86           the board, Not asked; 10.07 CHECKING; 11.16 checkout-api 12.9x,
#:                  TEMPORAL CANDIDATE, Commit 4f1c2ab; 11.63 all five rows answered
#:   14.44          Right: focus on Stage rollback; 15.85 Rollback staged, 300 s lease
#:   20.11          Right: focus on Confirm; 21.69 RECORDED, no pipeline contacted
#:   26.29          Center on Publish handoff; 26.59 SHARED REVISION 13, HTTP 200
#:   27.64          the end of the clip at 25 fps (691 frames; last change at 27.43)
#: The first cut trims 1 s of the idle home screen and keeps the launch on it. The
#: second sits in the cold-start black, 0.26 s before the board appears, so the
#: board beat's measured audio fits its window. The third sits just before the Right
#: press its beat narrates. The fourth sits 0.79 s before the Right to Confirm, so the
#: confirm beat's measured audio fits; its words then land on the frames: "recorded"
#: from 21.49 s (RECORDED shows at 21.69 s) and "Center publishes the handoff" from
#: 25.35 s to 27.06 s (the press lands at 26.29 s).
FOOTAGE_CUTS = [1.00, 8.60, 14.32, 19.32, 27.64]

# (beat_id, seconds, narration_text, caption_text or None, visual_action, source)
BEATS = [
    (
        "beat_01_tv_launch", None,
        "From the home screen, the debug A P K starts on an Android TV emulator and "
        "loads the public demo.",
        "From the home screen, the debug APK starts on an Android TV emulator and "
        "loads the public demo.",
        "Emulator footage, 1.00 s to 8.60 s of journey.mp4 at 1x: the Leanback home "
        "screen, then black while the app cold-starts and its WebView loads the demo.",
        EMULATOR,
    ),
    (
        "beat_02_tv_board", None,
        "The board answers: checkout A P I at twelve point nine times baseline.",
        "The board answers: checkout-api at 12.9x baseline.",
        "Emulator footage, 8.60 s to 14.32 s: the end of the cold start, the board appears, CHECKING, then "
        "checkout-api 12.9x, TEMPORAL CANDIDATE, Commit 4f1c2ab from the demo's "
        "invented deploy feed, then all five rows.",
        EMULATOR,
    ),
    (
        "beat_03_tv_stage", None,
        "Right, then center stages a rollback. Its lease counts down.",
        "Right, then Center stages a rollback. Its lease counts down.",
        "Emulator footage, 14.32 s to 19.32 s: D-pad Right to Stage rollback, Center. "
        "Rollback staged, the lease counting down from 300 s.",
        EMULATOR,
    ),
    (
        "beat_04_tv_confirm_publish", None,
        "Right, center confirms: recorded, no pipeline contacted, record only. Center "
        "publishes the handoff.",
        "Right, Center confirms: RECORDED, no pipeline contacted, record-only. Center "
        "publishes the handoff.",
        "Emulator footage, 19.32 s to the end at 27.64 s: D-pad Right to Confirm, "
        "Center. RECORDED, no pipeline contacted, held on the board; then Center on "
        "Publish handoff and the shared handoff, SHARED REVISION 13, HTTP 200.",
        EMULATOR,
    ),
    (
        "beat_05_desktop_board", 14.814,
        "The rest is the same board, run locally in a desktop browser at ten eighty p, "
        "so each answer can be read. Mercury counts only commits that touch runtime "
        "files, and names one only when exactly one landed before the spike.",
        "The rest is the same board, run locally in a desktop browser at 1080p, so "
        "each answer can be read. Mercury counts only commits that touch runtime "
        "files, and names one only when exactly one landed before the spike.",
        "The desktop take begins: the loaded board at 1920x1080, focus on Ask what "
        "changed. No key pressed.",
        DESKTOP,
    ),
    (
        "beat_06_board_on_load", 18.019,
        "It answered on load, before any key was pressed. Most answers are refusals: on "
        "generated cases held out from tuning, it saw a real anomaly and named nobody "
        "ninety percent of the time. A refusal never calls the deploy innocent.",
        "It answered on load, before any key was pressed. Most answers are refusals: on "
        "generated cases held out from tuning, it saw a real anomaly and named nobody "
        "90.0% of the time. A refusal never calls the deploy innocent.",
        "Hold on the board. The five rows read Temporal candidate, Nothing to revert, "
        "Cannot attribute, Cannot attribute and Insufficient data, each from the "
        "server's answer.",
        DESKTOP,
    ),
    (
        "beat_07_crowded_refusal", 17.554,
        "Down walks the rows. Release train shows a spike well above its baseline, but "
        "several runtime changes landed in the window before it, and no metric says "
        "which one did it. Mercury cannot attribute this, and offers no rollback. "
        "Rolling back would be a guess.",
        "Down walks the rows. release-train shows a spike well above its baseline, but "
        "several runtime changes landed in the window before it, and no metric says "
        "which one did it. Mercury cannot attribute this, and offers no rollback. "
        "Rolling back would be a guess.",
        "D-pad Down four times to release-train, then Center. The verdict reads Cannot "
        "attribute this with the number of changes that landed, Next reads No rollback "
        "offered, and Stage rollback and Confirm are disabled.",
        DESKTOP,
    ),
    (
        "beat_08_named_with_odds", 19.783,
        "On checkout A P I, exactly one runtime change landed before the spike, so "
        "Mercury names it, and prints its own odds: on held-out generated cases a named "
        "commit is the cause fifty percent of the time, over fifty eight namings, if a "
        "fault shows within seventy five minutes.",
        "On checkout-api, exactly one runtime change landed before the spike, so "
        "Mercury names it, and prints its own odds: on held-out generated cases a named "
        "commit is the cause 50.0% of the time, over 58 namings, if a fault shows "
        "within 75 minutes.",
        "D-pad Up three times to checkout-api, then Center. The verdict names the "
        "commit as the only runtime change, quotes its message, and reads 50.0% "
        "held-out precision (synthetic, ≤75m lag).",
        DESKTOP,
    ),
    (
        "beat_09_provenance", 10.635,
        "The reading and the commit each carry a stamp. The metric is an offline "
        "fixture, generated locally. The commit is one of Mercury's own, standing in "
        "for a deploy feed.",
        None,
        "Hold on the OFFLINE FIXTURE stamp under the reading and the dashed STAND-IN "
        "stamp against Mercury's commits. No key pressed. (The public demo in the "
        "emulator footage names a deploy from an invented feed instead.)",
        DESKTOP,
    ),
    (
        "beat_10_stage_to_evidence", 18.529,
        "Up, right, center stages the rollback; right, center confirms it, and the board "
        "holds recorded, not sent. Center publishes the handoff. Down reaches the "
        "evidence behind the odds: fifty eight namings, in eleven hundred sixty "
        "synthetic cases.",
        "Up, Right, Center stages the rollback; Right, Center confirms it, and the board "
        "holds RECORDED, not sent. Center publishes the handoff. Down reaches the "
        "evidence behind the odds: 58 namings, in 1160 synthetic cases.",
        "D-pad Up, Right to Stage rollback, Center: Rollback staged. Right to Confirm, "
        "Center: nothing scrolls, the large figure reads RECORDED, no pipeline "
        "contacted, and the legend reads Next press: Publish responder handoff. Center "
        "publishes: HTTP 200, the handoff's responder, facts and next step clear the "
        "key bar under the rollback steps. Down lands on Incident evidence: 50.0% over "
        "58 namings in 1160 synthetic labelled cases.",
        DESKTOP,
    ),
    (
        "beat_11_dpad", 12.167,
        "The ring jumps to the nearest control in the direction pressed, and the label "
        "at the bottom right names it. Center opens delivery velocity, and Back now "
        "reads: back to the wall.",
        "The ring jumps to the nearest control in the direction pressed, and the label "
        "at the bottom right names it. Center opens Delivery velocity, and BACK now "
        "reads: Back to the wall.",
        "D-pad Right to Delivery velocity, Center. The panel opens and the BACK legend "
        "changes from Exit to the Fire TV launcher to Back to the wall.",
        DESKTOP,
    ),
    (
        "beat_12_fixtures", 12.585,
        "Its answer is a recording, stamped offline fixture, because no GitHub token is "
        "set. Back returns to the wall, not out of the app. Cloud spend is a fixture "
        "too, marked synthetic.",
        "Its answer is a recording, stamped OFFLINE FIXTURE, because no GitHub token is "
        "set. BACK returns to the wall, not out of the app. Cloud spend is a fixture "
        "too, marked SYNTHETIC.",
        "D-pad Down scrolls the rest of the DORA answer into view with its OFFLINE "
        "FIXTURE stamp; the cursor stays in the panel. Back returns to the wall and the "
        "legend changes back. Right to Cloud spend, Center: the spend answer carries "
        "OFFLINE FIXTURE and says its figures are SYNTHETIC. Back to the wall.",
        DESKTOP,
    ),
    (
        "beat_13_build_check", 11.656,
        "Last, the server reports its build: the commit on the opening card, in fixture "
        "mode. The emulator footage came from C I, not a Fire TV device.",
        "Last, the server reports its build: the commit on the opening card, in fixture "
        "mode. The emulator footage came from CI, not a Fire TV device.",
        "Down to How it answers, Down to Check, Center. The connection line reads GET "
        "/health returned 200, the build's short SHA, and GitHub live: no, fixture mode.",
        DESKTOP,
    ),
]

STATUS = (
    "RENDERED LOCALLY, NOT UPLOADED. This plan is for the next take, not yet recorded. "
    "Its content opens on Android TV emulator footage from CI run 37475795991: the "
    "debug APK built at f423ba5 on an AOSP Android TV emulator, Android 14 / API 34, "
    "loading the public demo (build ea2cff5, record-only), at 1x. That is footage, not "
    "a Fire TV device and not a runtime receipt; the Android TV emulator runtime "
    "receipt is a separate file, android_tv_runtime_receipt.json. The rest is a local "
    "run of this repository in desktop Chromium at 1920x1080 with MERCURY_OFFLINE=1, "
    "driven through the D-pad bridge the Leanback app calls. An emulator beat's "
    "seconds are its footage window; a desktop beat's seconds are its measured hold, "
    "the length of its synthesized audio plus a 0.65 s tail, from "
    "video/generate-narration.py. The media lives outside the repository; "
    "video/README.md says where. The event FAQ permits the Android TV Emulator and "
    "does not require physical hardware."
)


def footage_windows() -> dict[str, tuple[float, float]]:
    """Each emulator beat's window in journey.mp4, in beat order."""
    emulator = [beat[0] for beat in BEATS if beat[5] == EMULATOR]
    if len(emulator) != len(FOOTAGE_CUTS) - 1:
        raise SystemExit("every emulator beat needs exactly one footage window")
    return {
        beat_id: (FOOTAGE_CUTS[i], FOOTAGE_CUTS[i + 1]) for i, beat_id in enumerate(emulator)
    }


def main() -> None:
    windows = footage_windows()
    sources = [beat[5] for beat in BEATS]
    if sources != sorted(sources, key=lambda source: source != EMULATOR):
        raise SystemExit("the emulator beats must open the content, before any desktop beat")
    if FOOTAGE_CUTS[-1] * 25 > FOOTAGE["frames_at_25_fps"] + 1e-6:
        raise SystemExit("the last cut is past the end of the footage")

    narration_beats = []
    cue_beats = []
    start = 0.0
    for index, (beat_id, seconds, text, caption, visual, source) in enumerate(BEATS, start=1):
        if source == EMULATOR:
            first, last = windows[beat_id]
            seconds = round(last - first, 3)
        end = round(start + seconds, 3)
        caption = caption or text
        words = len(text.split())
        beat = {
            "beat_id": beat_id,
            "source": source,
            "timestamp_start": start,
            "timestamp_end": end,
            "narration_text": text,
            "caption_text": caption,
            "visual_action": visual,
        }
        if source == EMULATOR:
            beat["fixed_hold_seconds"] = seconds
            beat["footage_window_seconds"] = list(windows[beat_id])
        narration_beats.append(beat)
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
            "visual_action": visual,
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
            "android_tv_emulator beat its window of the CI footage, for a "
            "desktop_capture beat the measured audio length plus a 0.65 s tail. "
            "total_duration_sec is the content only; the title card (4 s) and the "
            "closing card (3 s) are added by video/build-video.py."
        ),
        "emulator_footage": FOOTAGE,
        "total_duration_sec": total,
        "max_allowed_seconds": 180.0,
        "beats": cue_beats,
    }

    (OUT / "narration.json").write_text(json.dumps(narration, indent=2) + "\n", encoding="utf-8")
    (OUT / "cue_sheet.json").write_text(json.dumps(cue_sheet, indent=2) + "\n", encoding="utf-8")
    print("total", total, "with cards", round(total + 7.0, 3), "beats", len(BEATS),
          "words", sum(len(b[2].split()) for b in BEATS))
    rates = [b["words_per_minute"] for b in cue_beats if b["words_per_minute"]]
    print("wpm range", min(rates), max(rates))


if __name__ == "__main__":
    main()
