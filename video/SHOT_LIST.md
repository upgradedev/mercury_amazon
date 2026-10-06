# Mercury demo video: shot list

**Status: RENDERED LOCALLY, NOT UPLOADED.** The last render, recorded 2026-10-01 at
`9620743`, is described in `video/README.md`, which also says where it lives. This list
is the plan for the next take, which has not been recorded yet. The take opens on the
Android TV emulator footage from CI run 37475795991, then plays the desktop take. The
desktop beat order was probed on 2026-09-28 by driving the page with the D-pad bridge
against a local server and reading what each press brings on screen. Beat lengths are
set by the narration, not by this file. `video/generate-narration.py` measures each
desktop beat's synthesized audio, and the capture holds every desktop beat for exactly
that length. Each emulator beat is held for its window of the footage instead.

The words spoken and the words captioned for each beat live in
`scripts/build_video_plan.py`, which writes `video/narration.json` and
`video/cue_sheet.json`. Edit the beat there and rerun it; never edit the JSON.

## The rule this list follows

Every beat is the page reacting to a real response from a running server, reached with
the remote's keys. No beat asks for a screen that has to be built first, no beat
narrates something the frame does not show, and no beat claims a number that is not on
screen or in `attribution_holdout_summary.json`.

## Platform shown, and what that costs

**The content opens on the Android TV emulator footage.** It is `journey.mp4` from the
artifact `mercury-android-tv-footage-f423ba57ecfe688b8dafe899e06ab29dfdb7a90c`,
filmed by `.github/workflows/android-tv-footage.yml` in CI run
[37475795991](https://github.com/upgradedev/mercury_amazon/actions/runs/37475795991):

* the debug APK built at `f423ba5`;
* on an AOSP Android TV emulator (x86), Android 14 / API 34;
* loading the public demo, build `ea2cff5`, which is record-only;
* launched with its Leanback launcher intent over the home screen, then driven with
  D-pad key codes sent by the CI script.

It plays at 1x. The screenrecord writes a frame only when the screen changes, so it is
converted to 25 fps by holding each frame until the next one. Nothing is sped up, and
no moment is held past its own recorded length. The first second of the idle home
screen is trimmed. The launch from the home screen, the cold start (black while the
WebView loads the demo) and every answer stay in. A small label under the picture
reads "Android TV emulator (API 34), debug APK, public demo build ea2cff5, CI run
37475795991" for as long as the footage plays.

This is emulator footage from CI, not a Fire TV device, and it is not a runtime
receipt. Gate J4 rests on the separate runtime receipt, `android_tv_runtime_receipt.json`,
written by `.github/workflows/android-tv-emulator.yml` and `scripts/android_tv_smoke.sh`.

**Then the desktop take.** Desktop Chromium at 1920x1080 against a local server
started with `MERCURY_OFFLINE=1 python -m uvicorn src.interfaces.mcp_server:app
--port 8873`. It is driven by calling `window.navigateDpad` with `UP`, `DOWN`, `LEFT`,
`RIGHT`, `SELECT` and `BACK`, the bridge the Leanback `MainActivity` calls for each
remote key. No mouse is used. The narration says once that this is the same board in a
desktop browser at 1080p, so each answer can be read. Its data differs from the public
demo's in one place: the local board names one of Mercury's own commits (stamped
STAND-IN), while the public demo names a deploy from an invented, display-only feed.

**The desktop rehearsal is not the final Fire TV track proof.** The event FAQ accepts
the Android TV Emulator. The proof for the track is the APK on the emulator: the footage
above for the video, and the runtime receipt for gate J4.

## What the page does that shaped the order

* The D-pad navigator scrolls only as far as the focused control. Nothing is focusable
  above **Ask what changed**, so once the page has scrolled down, the board's top row
  does not come back into view. The staging beat therefore comes before any beat that
  scrolls down.
* Confirm leaves the board where it is. The large figure reads **RECORDED, no pipeline
  contacted**, and **Publish handoff** is the next stop without a ring. The capture
  refuses to go on unless the page is still at the top, with the legend reading Next
  press: Publish responder handoff. Center then publishes, and the page shows the
  handoff's answer under the rollback steps.
* The desktop take presses the same keys in the same order as the 2026-10-01 take, with
  the same focus checks and the same awaited answers. Its stage, confirm and handoff
  presses now share one shorter beat, because the footage has already shown them at a
  viewer's pace. `tests/video/test_emulator_open_cut.py` holds the key sequence to
  the recorded one.
* How it answers and Who it is for open from a fourth tile, on its own row under the
  three evidence tiles. Down from Publish handoff still lands on Incident evidence, and
  Right from there lands on Delivery velocity.
* A panel's answer renders below its buttons, and Center brings the top of it into
  view. An open panel holds the remote until Back closes it. Down at its foot scrolls
  the rest into view, and the cursor stays on the panel's button. Check, in the
  Connection section, is reached from the wall, under the How it answers tile.
* `DPAD_RECORD_ONLY_DEMO` and the `NONE` external effect are in the server's response
  but are not rendered on the page, so no beat claims to show them.
* Never press Center on **Read aloud** or **Setup**; the video has no product audio.

## Beats

Seconds are content time; the 4 s title card comes before beat 1. The footage times
are `journey.mp4`'s own clock.

| # | Beat | Source | Seconds | Keys | On screen |
|---|---|---|---|---|---|
| 1 | `beat_01_tv_launch` | emulator 1.00 to 8.60 s | 7.60 | none (launch intent) | The Leanback home screen, then black while the app cold-starts and loads the public demo |
| 2 | `beat_02_tv_board` | emulator 8.60 to 14.32 s | 5.72 | none | The board appears, CHECKING, then checkout-api 12.9x, TEMPORAL CANDIDATE, Commit 4f1c2ab (invented feed), then all five rows |
| 3 | `beat_03_tv_stage` | emulator 14.32 to 19.32 s | 5.00 | Right, Center | Rollback staged, the lease counting down from 300 s |
| 4 | `beat_04_tv_confirm_publish` | emulator 19.32 to 27.64 s | 8.32 | Right, Center, Center | RECORDED, no pipeline contacted; then Publish handoff and the shared handoff, SHARED REVISION 13, HTTP 200 |
| 5 | `beat_05_desktop_board` | desktop | 14.814 | none | The same board in desktop Chromium at 1920x1080, focus on Ask what changed |
| 6 | `beat_06_board_on_load` | desktop | 18.019 | none | Five rows answered on load: Temporal candidate, Nothing to revert, Cannot attribute, Cannot attribute, Insufficient data |
| 7 | `beat_07_crowded_refusal` | desktop | 17.554 | Down x4, Center | release-train: Cannot attribute this, N runtime changes landed; Next: No rollback offered; Stage and Confirm disabled |
| 8 | `beat_08_named_with_odds` | desktop | 19.783 | Up x3, Center | checkout-api: the commit named as the only runtime change, its message quoted, 50.0% held-out precision (synthetic, at most 75 minutes of lag) |
| 9 | `beat_09_provenance` | desktop | 10.635 | none | OFFLINE FIXTURE stamp under the reading, dashed STAND-IN against Mercury's commits |
| 10 | `beat_10_stage_to_evidence` | desktop | 18.529 | Up, Right, Center, Right, Center, Center, Down | Rollback staged; RECORDED, no pipeline contacted, board not scrolled; the handoff's answer; Incident evidence under the held-out sentence: 50.0% over 58 namings in 1160 synthetic labelled cases |
| 11 | `beat_11_dpad` | desktop | 12.167 | Right, Center | Delivery velocity opens; the BACK legend changes to Back to the wall |
| 12 | `beat_12_fixtures` | desktop | 12.585 | Down, Back, Right, Center, Back | DORA answer with OFFLINE FIXTURE, scrolled within the panel; Back to the wall; Cloud spend answer with OFFLINE FIXTURE and SYNTHETIC figures; Back to the wall |
| 13 | `beat_13_build_check` | desktop | 11.656 | Down, Down, Center on Check | GET /health returned 200, the build's short SHA, GitHub live: no, fixture mode |

Content: 162.382 s. With the 4 s title card and the 3 s closing card the planned video
is 169.382 s, under the 175 s the sync gate allows.

The emulator words were placed on the footage's frames (times in `journey.mp4`):

| Words | Spoken from | The frame |
|---|---|---|
| "loads the public demo" | about 6.2 s | black, the cold start, until the board at 8.86 s |
| "The board answers" | 8.60 s | the board at 8.86 s, CHECKING at 10.07 s |
| "checkout-api at 12.9x baseline" | 9.86 s | checkout-api 12.9x at 11.16 s, all rows at 11.63 s |
| "Right, then Center stages a rollback" | 14.32 s | focus on Stage at 14.44 s, staged at 15.85 s |
| "Its lease counts down" | 16.48 s | the lease counting from 300 s |
| "Right, Center confirms" | 19.32 s | focus on Confirm at 20.11 s, Center at 21.25 s |
| "RECORDED, no pipeline contacted" | 21.49 s | RECORDED at 21.69 s |
| "Center publishes the handoff" | 25.35 s | Center at 26.29 s, the handoff at 26.59 s |

The title card before beat 1 says what the product is first: Mercury. An incident board
for the team's Fire TV. It names the deploy behind a spike only when it can. Two smaller
lines under it name the two sources of the picture, in the order they play: Android TV
emulator, API 34, CI run 37475795991; local desktop run of `<sha7>`. Then: offline
fixtures, record-only rollback. The closing card repeats the run, the demo build and
the commit, and says the emulator runtime receipt is a separate record.

## Numbers policy for the recording

Numbers on screen are read off the screen, and they vary per run: the reading, the
number of changes in the release-train window, the lease, the latency and the SHA.
The spend figures are synthetic and are not read aloud. The emulator beats read one
figure off the footage, the 12.9x reading.

Two figures are spoken from the script, because they describe the labelled corpus, not
this run. Both are on the held-out split of the synthetic corpus, with the runtime
filter shipped on 2026-09-27:

* 90.0% named nobody on a real anomaly (beat 6);
* 50.0% precision over 58 namings (beat 8). Beat 8 also says the precision holds only
  if a fault shows within 75 minutes, the generator's delay ceiling, which the window
  equals.

Both are written by `python scripts/attribution_split.py` into
`attribution_holdout_summary.json`. The board prints the same two at the current
master, and the README quotes them. Beat 10 reads the 58 namings and the 1160
synthetic cases off the evidence sentence on screen, which prints the same summary.
`tests/video/test_emulator_open_cut.py` compares the captions with the summary.

Earlier takes quoted the in-sample 81.1% and 52.2% over 113 namings, and then the
pre-filter held-out 93.1% and 62.5% over 40. Neither is current, and the takes that
spoke them are superseded. If a re-run moves the figures, change the beat in
`scripts/build_video_plan.py`, rerun it, and re-render that beat.
`video/generate-narration.py` synthesizes only the beats whose words changed.
