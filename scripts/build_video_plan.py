"""Regenerate video/narration.json and video/cue_sheet.json from one beat list.

The two files described a product that does not exist: an Alexa voice query, an
Echo Show, Datadog and Jira, and a +311% spend figure nobody measured. They are
rewritten here from video/SHOT_LIST.md so the plan, the narration and the cue
sheet cannot disagree with each other or with the repository.

Word counts and the words-per-minute column are computed from the narration text,
not typed in.
"""
import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "video"

BEATS = [
    (
        "beat_01_question", 0.0, 12.0,
        "An incident starts. Somebody asks what broke. The answer is spread across "
        "six browser tabs on six different laptops, and the one screen everyone in "
        "the room can see is showing nothing.",
        "Cold open on the loaded cockpit at 1920x1080 in a desktop browser. No click yet.",
    ),
    (
        "beat_02_answer_on_load", 12.0, 30.0,
        "Mercury answers before anyone clicks. On load it calls its own API and puts "
        "one sentence on the screen: the commit that raised the error rate, the "
        "service it raised it on, and how far above baseline the reading is.",
        "Reload the page. The hero renders the correlator's verdict, the anomaly "
        "factor as the large figure, and the offending commit message quoted with its author.",
    ),
    (
        "beat_03_provenance", 30.0, 45.0,
        "Both halves of that answer say where they came from. The metric series is "
        "simulated, and the badge beside it says so. The commits are real, read from "
        "the checkout. The latency is timed in the page, not written into it.",
        "Hold on the two source badges in the hero footer, offline-fixture against "
        "metric series and local-git against commit history, beside the measured latency line.",
    ),
    (
        "beat_04_dpad", 45.0, 62.0,
        "The remote moves in space, not down a list. Focus jumps to the nearest "
        "control in the direction pressed, and the hint bar names whatever the ring "
        "is on. The disabled control is skipped rather than focused.",
        "Press Right, Right, Down, Right, Left. The focus ring moves and the "
        "Focused label in the key hint bar changes with each press.",
    ),
    (
        "beat_05_center_back", 62.0, 78.0,
        "Center drills into a panel. Back returns to the wall before it would ever "
        "close the application, so the war room is not shut by accident during an incident.",
        "Press Enter on the Delivery velocity tile, then Escape. The BACK legend "
        "changes to Back to the wall and then back again.",
    ),
    (
        "beat_06_two_sources", 78.0, 95.0,
        "One screen, two kinds of truth. The velocity panel is serving a recording "
        "because no GitHub token is set, and says so. The spend panel, on a machine "
        "with credentials, is a live Cost Explorer read, and says that too.",
        "Load DORA velocity, then scan AWS spend. Compare the OFFLINE FIXTURE badge "
        "against the LIVE aws-cost-explorer badge. Do not read live spend figures aloud.",
    ),
    (
        "beat_07_refusal", 95.0, 108.0,
        "The only irreversible control on the screen refuses in plain words when the "
        "governance secret is missing. It does not fail silently and it does not pretend.",
        "With the Secret field empty, press Stage governed rollback. The incident "
        "panel shows the refusal text.",
    ),
    (
        "beat_08_staging", 108.0, 125.0,
        "With the secret, staging mints a single-use token bound to a hash of exactly "
        "this rollback. Change the target afterwards and the token stops applying.",
        "Type the secret, stage again. Show PENDING_CONFIRMATION, the payload hash, "
        "the lease countdown as the hero figure, and Confirm becoming enabled.",
    ),
    (
        "beat_09_confirm", 125.0, 142.0,
        "Governance passes, and the product says out loud what it did not do. No "
        "deployment pipeline was contacted. Mercury ships no pipeline integration, "
        "and the moment of success is where it admits that.",
        "Press Confirm rollback. Read the EXECUTED output verbatim, including the "
        "sentence stating no pipeline was contacted.",
    ),
    (
        "beat_10_replay_refused", 142.0, 155.0,
        "Press it again and the server refuses by name. The token was valid once. "
        "Leave a staging past its lease and it expires the same way.",
        "Press Confirm rollback a second time. Show the 409 NOT_PENDING denial and "
        "the reason line saying the token has been spent.",
    ),
    (
        "beat_11_not_built", 155.0, 168.0,
        "What is not built: no APK exists, the Kotlin has never been compiled, and "
        "nothing has run on Fire TV hardware. The navigation, the correlation and the "
        "governance were driven live here. The device was not.",
        "Cut to docs/FIRE_TV_BUILD.md open on the recorded build failure.",
    ),
]

PLAN_NOTE = (
    "PLAN ONLY. No video has been recorded. Durations are intended, not measured "
    "against a take. Every beat is an action that exists in the repository today "
    "and was performed in a desktop browser against a local server. No beat shows "
    "a Fire TV device or the Fire TV emulator, because no APK has been built."
)

narration_beats = []
cue_beats = []
for index, (beat_id, start, end, text, visual) in enumerate(BEATS, start=1):
    words = len(text.split())
    duration = round(end - start, 1)
    narration_beats.append({
        "beat_id": beat_id,
        "timestamp_start": start,
        "timestamp_end": end,
        "narration_text": text,
        "visual_action": visual,
    })
    cue_beats.append({
        "beat_index": index,
        "beat_id": beat_id,
        "timestamp_start": start,
        "timestamp_end": end,
        "duration_sec": duration,
        "words_count": words,
        "words_per_minute": round(words / duration * 60.0, 1),
        "narration_text": text,
        "visual_action": visual,
    })

total = BEATS[-1][2]

narration = {
    "schema": "mercury.video_narration/1",
    "status": PLAN_NOTE,
    "project": "mercury_amazon",
    "title": "Mercury: Fire TV Incident Commander",
    "source_of_truth": "video/SHOT_LIST.md",
    "target_duration_seconds": total,
    "max_allowed_seconds": 180.0,
    "beats": narration_beats,
}

cue_sheet = {
    "schema": "mercury.video_plan/1",
    "status": PLAN_NOTE,
    "project": "mercury_amazon",
    "title": "Mercury: Fire TV Incident Commander",
    "source_of_truth": "video/SHOT_LIST.md",
    "generated_by_command": "python scripts/build_video_plan.py",
    "note": (
        "words_count and words_per_minute are computed from narration_text by the "
        "generator. They describe the script, not a recording."
    ),
    "total_duration_sec": total,
    "max_allowed_seconds": 180.0,
    "beats": cue_beats,
}

(OUT / "narration.json").write_text(json.dumps(narration, indent=2) + "\n", encoding="utf-8")
(OUT / "cue_sheet.json").write_text(json.dumps(cue_sheet, indent=2) + "\n", encoding="utf-8")
print("total", total, "beats", len(BEATS))
print("wpm range", min(b["words_per_minute"] for b in cue_beats), max(b["words_per_minute"] for b in cue_beats))
