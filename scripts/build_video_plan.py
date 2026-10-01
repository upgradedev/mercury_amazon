"""Regenerate video/narration.json and video/cue_sheet.json from one beat list.

The two files once described a product that does not exist: an Alexa voice query,
an Echo Show, Datadog and Jira, and a +311% spend figure nobody measured. They are
written here from one list, so the shot list, the narration and the cue sheet
cannot disagree with each other or with the repository.

Each beat carries two texts. ``narration_text`` is what the voice says, with
initialisms spelled out and figures written as words so the text to speech engine
reads them correctly. ``caption_text`` is what is burned on screen, with the exact
product names and figures. ``video/generate-narration.py`` reads both.

The beat order follows what the D-pad actually brings on screen in the page,
probed against a local server on 2026-09-26, not an earlier plan.

``seconds`` is each beat's hold in the render: the measured duration of its
synthesized audio plus a fixed 0.65 s tail, as written to ``timing.json`` by
``video/generate-narration.py``. Word counts and words per minute are computed
here from the text, not typed in.
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

# (beat_id, seconds, narration_text, caption_text or None, visual_action)
BEATS = [
    (
        "beat_01_question", 16.858,
        "Mercury is an incident board for the team's Fire TV. When errors spike, the "
        "room asks which deploy did it. Mercury counts only commits that touch runtime "
        "files, and names one only when exactly one landed before the spike.",
        None,
        "The loaded board at 1920x1080, focus on Ask what changed. No key pressed.",
    ),
    (
        "beat_02_board_on_load", 18.019,
        "It answered on load, before any key was pressed. Most answers are refusals: on "
        "generated cases held out from tuning, it saw a real anomaly and named nobody "
        "ninety percent of the time. A refusal never calls the deploy innocent.",
        "It answered on load, before any key was pressed. Most answers are refusals: on "
        "generated cases held out from tuning, it saw a real anomaly and named nobody "
        "90.0% of the time. A refusal never calls the deploy innocent.",
        "Hold on the board. The five rows read Temporal candidate, Nothing to revert, "
        "Cannot attribute, Cannot attribute and Insufficient data, each from the "
        "server's answer.",
    ),
    (
        "beat_03_crowded_refusal", 17.554,
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
    ),
    (
        "beat_04_named_with_odds", 19.783,
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
    ),
    (
        "beat_05_provenance", 10.635,
        "The reading and the commit each carry a stamp. The metric is an offline "
        "fixture, generated locally. The commit is one of Mercury's own, standing in "
        "for a deploy feed.",
        None,
        "Hold on the OFFLINE FIXTURE stamp under the reading and the dashed STAND-IN "
        "stamp against Mercury's commits. No key pressed.",
    ),
    (
        "beat_06_stage", 11.517,
        "Only a named change can be rolled back. Up, right, center: staging returns a "
        "single use token bound to a hash of this exact proposal, and the lease counts "
        "down on the board.",
        "Only a named change can be rolled back. Up, Right, Center: staging returns a "
        "single-use token bound to a hash of this exact proposal, and the lease counts "
        "down on the board.",
        "D-pad Up, Right to Stage rollback, Center. The board reads Rollback staged, "
        "the lease in seconds as the large figure, and Next reads Staged. Next: "
        "confirm, record-only.",
    ),
    (
        "beat_07_confirm", 14.118,
        "Right, then center confirms. The server spends the token, and the board holds "
        "the result: recorded, no pipeline contacted. The rollback is recorded, not "
        "sent.",
        "Right, then Center confirms. The server spends the token, and the board holds "
        "the result: RECORDED, no pipeline contacted. The rollback is recorded, not "
        "sent.",
        "D-pad Right to Confirm, Center. Nothing scrolls: the large figure reads "
        "RECORDED, no pipeline contacted, under Rollback recorded, not sent, and the "
        "key legend reads Next press: Publish responder handoff.",
    ),
    (
        "beat_08_handoff", 14.257,
        "Center publishes the handoff, and the steps show the token spent: confirming "
        "again is refused. Down reaches the evidence behind the odds: fifty eight "
        "namings, in eleven hundred sixty synthetic cases.",
        "Center publishes the handoff, and the steps show the token spent: confirming "
        "again is refused. Down reaches the evidence behind the odds: 58 namings, in "
        "1160 synthetic cases.",
        "Center on the deferred Publish handoff; the server answers HTTP 200, the "
        "cursor stays on Publish, and the page scrolls until the handoff's responder, "
        "facts and next step clear the key bar, under the rollback steps, where 02 "
        "Confirm reads that the token has been spent and confirming again is refused "
        "by name. D-pad Down lands on "
        "Incident evidence and brings Evidence behind the board into view: 50.0% over "
        "58 namings in 1160 synthetic labelled cases.",
    ),
    (
        "beat_09_dpad", 12.167,
        "The ring jumps to the nearest control in the direction pressed, and the label "
        "at the bottom right names it. Center opens delivery velocity, and Back now "
        "reads: back to the wall.",
        "The ring jumps to the nearest control in the direction pressed, and the label "
        "at the bottom right names it. Center opens Delivery velocity, and BACK now "
        "reads: Back to the wall.",
        "D-pad Right to Delivery velocity, Center. The panel opens and the BACK legend "
        "changes from Exit to the Fire TV launcher to Back to the wall.",
    ),
    (
        "beat_10_fixtures", 12.585,
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
    ),
    (
        "beat_11_build_check", 16.114,
        "Last, the server reports its build: the commit on the opening card, in fixture "
        "mode. This is a desktop browser at Fire TV resolution, driven through the D "
        "pad bridge the Leanback app calls. No device or emulator run is shown.",
        "Last, the server reports its build: the commit on the opening card, in fixture "
        "mode. This is a desktop browser at Fire TV resolution, driven through the "
        "D-pad bridge the Leanback app calls. No device or emulator run is shown.",
        "Down to How it answers, Down to Check, Center. The connection line reads GET "
        "/health returned 200, the build's short SHA, and GitHub live: no, fixture mode.",
    ),
]

STATUS = (
    "RENDERED LOCALLY, NOT UPLOADED. The current take was recorded on 2026-09-28 from a local "
    "run of this repository in desktop Chromium at 1920x1080 with MERCURY_OFFLINE=1, "
    "driven through the D-pad bridge the Leanback app calls. Each beat's seconds are "
    "its measured hold: the length of its synthesized audio plus a 0.65 s tail, from "
    "video/generate-narration.py. The media lives outside the repository; "
    "video/README.md says where. This is not the Fire TV track runtime proof: the "
    "candidate Android TV Emulator receipt is still pending; the event FAQ permits "
    "that route and does not require physical hardware."
)

narration_beats = []
cue_beats = []
start = 0.0
for index, (beat_id, seconds, text, caption, visual) in enumerate(BEATS, start=1):
    end = round(start + seconds, 3)
    caption = caption or text
    words = len(text.split())
    narration_beats.append({
        "beat_id": beat_id,
        "timestamp_start": start,
        "timestamp_end": end,
        "narration_text": text,
        "caption_text": caption,
        "visual_action": visual,
    })
    cue_beats.append({
        "beat_index": index,
        "beat_id": beat_id,
        "timestamp_start": start,
        "timestamp_end": end,
        "duration_sec": round(seconds, 3),
        "words_count": words,
        "words_per_minute": round(words / seconds * 60.0, 1),
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
        "generator. duration_sec is the beat's hold in the render: measured audio "
        "length plus a 0.65 s tail."
    ),
    "total_duration_sec": total,
    "max_allowed_seconds": 180.0,
    "beats": cue_beats,
}

(OUT / "narration.json").write_text(json.dumps(narration, indent=2) + "\n", encoding="utf-8")
(OUT / "cue_sheet.json").write_text(json.dumps(cue_sheet, indent=2) + "\n", encoding="utf-8")
print("total", total, "beats", len(BEATS), "words", sum(len(b[2].split()) for b in BEATS))
print("wpm range", min(b["words_per_minute"] for b in cue_beats), max(b["words_per_minute"] for b in cue_beats))
