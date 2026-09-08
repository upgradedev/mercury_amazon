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
        "beat_01_question", 0.0, 13.0,
        "An incident starts. Somebody asks what broke, and the first answer everyone "
        "reaches for is: what did we just deploy. Half the time that is the wrong "
        "question, and reverting on it costs an hour.",
        "Cold open on the loaded cockpit at 1920x1080 in a desktop browser. No click yet.",
    ),
    (
        "beat_02_refusal_first", 13.0, 31.0,
        "Mercury answers before anyone clicks, and its most common answer is a "
        "refusal. Against eleven hundred and sixty labelled incidents it sees a real "
        "anomaly and names nobody eighty one percent of the time. The refusal says "
        "what Mercury cannot attribute and why. It never calls the deploy innocent.",
        "Reload the page. The hero renders the correlator's verdict and the anomaly "
        "factor as the large figure. Do not click anything yet.",
    ),
    (
        "beat_03_crowded_refusal", 31.0, 47.0,
        "The refusal that matters. Several changes landed in the hour before this "
        "spike, and nothing in a metric series says which of them did it. Mercury "
        "cannot attribute this, names none of them, and the rollback stays disabled. "
        "Rolling back here would be a guess.",
        "Press release-train. The hero reads Cannot attribute this, names the number "
        "of changes in the window, and both rollback buttons stay disabled with their "
        "reason lines visible.",
    ),
    (
        "beat_04_named_with_odds", 47.0, 68.0,
        "It names a change only when exactly one landed in the window. And when it "
        "does, it prints its own odds: against that same corpus the commit it names "
        "is the one that caused the reading fifty two percent of the time, over one "
        "hundred and thirteen namings. The screen says so beside the name.",
        "Press checkout-api. The hero names the commit, quotes its message, and the "
        "line under it reads the measured precision and the number of namings it was "
        "measured over.",
    ),
    (
        "beat_05_provenance", 68.0, 84.0,
        "Both halves of that answer say where they came from, next to the number "
        "rather than under the fold. The metric series is generated locally and the "
        "badge in the card reads OFFLINE FIXTURE. The commits are real, read from the "
        "checkout.",
        "Hold on the two source badges inside the hero card beside the anomaly "
        "factor, OFFLINE FIXTURE against metric series and LIVE against commit "
        "history. Do not scroll.",
    ),
    (
        "beat_06_dpad", 84.0, 101.0,
        "The remote moves in space, not down a list. Focus jumps to the nearest "
        "control in the direction pressed, disabled controls are skipped rather than "
        "focused, and Back returns to the wall before it would ever close the "
        "application.",
        "Press Right, Right, Down, Right, Left, then Enter on the Delivery velocity "
        "tile and Escape. The Focused label and the BACK legend change with each press.",
    ),
    (
        "beat_07_two_sources", 101.0, 116.0,
        "One screen, two kinds of truth. The velocity panel is serving a recording "
        "because no GitHub token is set, and says so. The spend panel, on a machine "
        "with credentials, is a live Cost Explorer read, and says that too.",
        "Load DORA velocity, then scan AWS spend. Compare the OFFLINE FIXTURE badge "
        "against the LIVE aws-cost-explorer badge. Do not read live spend figures aloud.",
    ),
    (
        "beat_08_refusal", 116.0, 129.0,
        "The only irreversible control on the screen refuses in plain words when the "
        "governance secret is missing. It does not fail silently and it does not pretend.",
        "Go back to checkout-api. With the Secret field empty, press Stage governed "
        "rollback. The incident panel shows the refusal text.",
    ),
    (
        "beat_09_staging", 129.0, 140.0,
        "With the secret, staging mints a single-use token bound to a hash of exactly "
        "this rollback. Change the target afterwards and the token stops applying.",
        "Type the secret, stage again. Show PENDING_CONFIRMATION, the payload hash, "
        "the lease countdown as the hero figure, and Confirm becoming enabled.",
    ),
    (
        "beat_10_confirm_and_replay", 140.0, 154.0,
        "Governance passes, and the product says out loud what it did not do. No "
        "deployment pipeline was contacted. Press it again and the server refuses by "
        "name: the token was valid once.",
        "Press Confirm rollback and read the EXECUTED output verbatim, including the "
        "sentence stating no pipeline was contacted. Press it a second time and show "
        "the 409 NOT_PENDING denial.",
    ),
    (
        "beat_11_not_built", 154.0, 168.0,
        "What is not built: no APK exists, the Kotlin has never been compiled, and "
        "nothing has run on Fire TV hardware. The refusals, the correlation and the "
        "governance were driven live here. The device was not.",
        "Cut to docs/FIRE_TV_BUILD.md open on the recorded build failure.",
    ),
]

PLAN_NOTE = (
    "PLAN ONLY. No video has been recorded. Durations are intended, not measured "
    "against a take. Every beat is an action that exists in the repository today "
    "and was performed in a desktop browser against a local server. No beat shows "
    "a Fire TV device, because no APK has been built, and no Fire TV emulator exists "
    "to stand in for one."
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
