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
        "beat_01_question", 15.139,
        "An incident starts, and someone asks what we just deployed. Half the time "
        "that is the wrong question. Mercury, an incident board for the team TV, asks "
        "a narrower one: can this spike be pinned on one change?",
        None,
        "The loaded board at 1920x1080, focus on Ask what changed. No key pressed.",
    ),
    (
        "beat_02_board_on_load", 18.297,
        "It answered as the page loaded, before any key was pressed. Most answers are "
        "refusals: on eleven hundred and sixty generated, labelled cases, it saw a real "
        "anomaly and named nobody eighty one percent of the time. A refusal never calls "
        "the deploy innocent.",
        "It answered as the page loaded, before any key was pressed. Most answers are "
        "refusals: on 1160 generated, labelled cases, it saw a real anomaly and named "
        "nobody 81.1% of the time. A refusal never calls the deploy innocent.",
        "Hold on the board. The five rows read Attributed, Nothing to revert, Cannot "
        "attribute, Cannot attribute and Insufficient data, each from the server's answer.",
    ),
    (
        "beat_03_crowded_refusal", 16.718,
        "Down walks the rows. Release train has a real spike, but several changes landed "
        "in the hour before it, and no metric says which one did it. Mercury cannot "
        "attribute this, and offers no rollback. Rolling back would be a guess.",
        "Down walks the rows. release-train has a real spike, but several changes landed "
        "in the hour before it, and no metric says which one did it. Mercury cannot "
        "attribute this, and offers no rollback. Rolling back would be a guess.",
        "D-pad Down four times to release-train, then Center. The verdict reads Cannot "
        "attribute this with the number of changes that landed, Next reads No rollback "
        "offered, and Stage rollback and Confirm are disabled.",
    ),
    (
        "beat_04_named_with_odds", 16.393,
        "On checkout A P I, exactly one change landed before the spike, so Mercury names "
        "it, and prints its own odds: on that corpus a named commit is the cause fifty "
        "two percent of the time, over one hundred and thirteen namings.",
        "On checkout-api, exactly one change landed before the spike, so Mercury names "
        "it, and prints its own odds: on that corpus a named commit is the cause 52.2% "
        "of the time, over 113 namings.",
        "D-pad Up three times to checkout-api, then Center. The verdict names the commit, "
        "quotes its message, and reads 52.2% naming precision.",
    ),
    (
        "beat_05_provenance", 14.071,
        "Each half says where it came from. The metric is an offline fixture, generated "
        "locally, and the striped stamp says so. The commit is one of Mercury's own, "
        "standing in for a deploy feed, and the dashed stamp says that too.",
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
        "D-pad Up, Right to Stage rollback, Center. The board reads Rollback staged, the "
        "lease in seconds as the large figure, and Next reads Staged. Next: confirm, "
        "record-only.",
    ),
    (
        "beat_07_confirm", 11.656,
        "Right, then center confirms. The server spends the token, and the recorded only "
        "card says it plainly: no deployment pipeline was contacted. Confirming again is "
        "refused.",
        "Right, then Center confirms. The server spends the token, and the Recorded only "
        "card says it plainly: no deployment pipeline was contacted. Confirming again is "
        "refused.",
        "D-pad Right to Confirm, Center. Focus moves to Publish handoff and the page "
        "scrolls to the rollback steps: 03 Recorded only states that no deployment "
        "pipeline was contacted, and 02 Confirm says the token has been spent.",
    ),
    (
        "beat_08_handoff", 9.752,
        "Center publishes a fixed responder handoff. Its next step repeats the boundary: "
        "this fixture never contacts a deployment pipeline.",
        None,
        "Center on Publish handoff; the server answers HTTP 200. D-pad Down brings the "
        "handoff's next step into view on the way to the evidence tiles.",
    ),
    (
        "beat_09_dpad", 12.167,
        "The ring jumps to the nearest control in the direction pressed, and the label at "
        "the bottom right names it. Center opens delivery velocity, and Back now reads: "
        "back to the wall.",
        "The ring jumps to the nearest control in the direction pressed, and the label at "
        "the bottom right names it. Center opens Delivery velocity, and BACK now reads: "
        "Back to the wall.",
        "D-pad Right to Delivery velocity, Center. The panel opens and the BACK legend "
        "changes from Exit to the Fire TV launcher to Back to the wall.",
    ),
    (
        "beat_10_fixtures", 16.811,
        "Down brings the answer into view: a recording, because no GitHub token is set. "
        "Back returns to the wall, not out of the app. Cloud spend is a fixture too, "
        "marked synthetic, because this run has no AWS credentials.",
        None,
        "D-pad Down reveals the DORA answer with its OFFLINE FIXTURE stamp. Back returns "
        "to the wall and the legend changes back. Right to Cloud spend, Center, Down: "
        "the spend answer carries OFFLINE FIXTURE and says its figures are SYNTHETIC.",
    ),
    (
        "beat_11_build_check", 19.458,
        "Last, the server reports its build: the commit on the opening card, in fixture "
        "mode. This take is a desktop browser at Fire TV resolution, driven through the "
        "D pad bridge the Leanback app calls. No device or emulator run is shown, and a "
        "public deployment is pending.",
        "Last, the server reports its build: the commit on the opening card, in fixture "
        "mode. This take is a desktop browser at Fire TV resolution, driven through the "
        "D-pad bridge the Leanback app calls. No device or emulator run is shown, and a "
        "public deployment is pending.",
        "Center on Check. The connection line reads GET /health returned 200, the build's "
        "short SHA, and GitHub live: no, fixture mode.",
    ),
]

STATUS = (
    "PLAN ONLY. No video has been recorded yet. The beats follow what the D-pad "
    "brings on screen in the page, probed against a local server on 2026-09-26. "
    "Each beat's seconds are its measured hold: the length of its synthesized audio "
    "plus a 0.65 s tail, from video/generate-narration.py. This is "
    "not the Fire TV track runtime proof: the candidate Android TV Emulator receipt "
    "is still pending; the event FAQ permits that route and does not require "
    "physical hardware."
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
