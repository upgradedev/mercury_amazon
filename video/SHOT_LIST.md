# Mercury demo video: shot list

**Status: RENDERED LOCALLY, NOT UPLOADED.** `video/README.md` says which take was last
rendered and where it lives. The take opens on the Android TV emulator footage from CI
run 37475795991, then plays the desktop take. The desktop beat order was probed on
2026-09-28 by driving the page with the D-pad bridge against a local server and
reading what each press brings on screen. Beat lengths are set by the narration, not
by this file. `video/generate-narration.py` measures each desktop beat's synthesized
audio, and the capture holds every desktop beat for exactly that length. Each emulator
beat is held for its window of the footage plus its holds of a static frame instead.

The words spoken and the words captioned for each beat live in
`scripts/build_video_plan.py`, which writes `video/narration.json` and
`video/cue_sheet.json`. Edit the beat there and rerun it; never edit the JSON.

## The rule this list follows

Every beat is the page reacting to a real response from a running server, reached with
the remote's keys. No beat asks for a screen that has to be built first, no beat
narrates something the frame does not show, and no beat claims a number that is not on
screen or in `attribution_holdout_summary.json`.

No caption names a value or a state (12.9x, RECORDED, the published handoff) more than
0.5 s before the frame that shows it, and a spoken word naming a press lands within
0.5 s of that press's visible effect. Over the footage this is checked against the
frame table below and the voice's measured alignment
(`tests/video/test_emulator_open_cut.py`). In the desktop take the capture presses each
such key on its spoken word, or before the caption that names its result.

## Platform shown, and what that costs

**The content opens on the Android TV emulator footage.** It is `journey.mp4` from the
artifact `mercury-android-tv-footage-f423ba57ecfe688b8dafe899e06ab29dfdb7a90c`,
filmed by `.github/workflows/android-tv-footage.yml` in CI run
[37475795991](https://github.com/upgradedev/mercury_amazon/actions/runs/37475795991):

* the debug APK built at `f423ba5`;
* on an AOSP Android TV emulator (x86), Android 14 / API 34;
* loading the public demo, build `ea2cff5`, which is record-only;
* launched with its Leanback launcher intent over the home screen, then driven with
  D-pad key codes sent by the CI script. The launch itself shows nothing on the home
  screen; the first visible change is the black of the cold start at 4.228 s.

It plays at 1x. The screenrecord writes a frame only when the screen changes, so it is
converted to 25 fps by holding each frame until the next one. Nothing is sped up or
slowed. Two frames are held longer, both where the source itself is still: the answered
board, held 1.52 s at 12.00 s (it is on screen from 11.630 s to 14.439 s in the source),
and the last frame, the shared handoff, held 2.52 s at the end. The first 0.32 s of the
idle home screen is trimmed. The home screen, the cold start (4.6 s of black while the
WebView loads the demo) and every answer stay in. A small label under the picture reads
"Android TV emulator (API 34), debug APK, public demo build ea2cff5, CI run
37475795991" for as long as the footage plays.

This is emulator footage from CI, not a Fire TV device, and it is not a runtime
receipt. Gate J4 rests on the separate runtime receipt, `android_tv_runtime_receipt.json`,
written by `.github/workflows/android-tv-emulator.yml` and `scripts/android_tv_smoke.sh`.

**Then the desktop take.** Desktop Chromium at 1920x1080 CSS pixels against a local
server started with `MERCURY_OFFLINE=1 python -m uvicorn src.interfaces.mcp_server:app
--port 8875`. It is driven by calling `window.navigateDpad` with `UP`, `DOWN`, `LEFT`,
`RIGHT`, `SELECT` and `BACK`, the bridge the Leanback `MainActivity` calls for each
remote key. No mouse is used. The narration says once that this is the same board in a
desktop browser at 1080p, and the title card says it is not the TV layout. Its data
differs from the public demo's in one place: the local board names one of Mercury's own
commits (stamped STAND-IN), while the public demo names a deploy from an invented,
display-only feed.

**Why the desktop take is not at the TV viewport.** The Fire TV WebView lays the page
out at 960x540 CSS pixels at a device scale factor of 2, with `MercuryHost` injected,
which turns on `html.tv-host` and the key bar; the emulator footage shows that layout.
On 2026-10-06 the whole scripted journey was rehearsed at that viewport (DSF 2, the
`MercuryHost` stub the browser tests use, a 1920x1080 recording, a local server on port
8875 at `e76e6da`). Every press, focus check and awaited answer passed unchanged, with
no page errors. The frames did not read well: headless Chromium films CSS pixels, so
Playwright's recorder wrote the 960x540 page into the top-left quarter of the 1920x1080
file, and a raw CDP screencast (old and new headless) also returned 960x540 frames. The
TV layout would reach the video as a 960x540 picture upscaled, with half the detail of
the desktop take, so the take stays at 1920x1080 and is labelled as a desktop browser.
`MERCURY_CAPTURE_VIEWPORT=tv` reruns that rehearsal.

**The desktop rehearsal is not the final Fire TV track proof.** The event FAQ accepts
the Android TV Emulator. The proof for the track is the APK on the emulator: the footage
above for the video, and the runtime receipt for gate J4.

## The footage, frame by frame

Every frame of `journey.mp4`, by index. The times come from
`ffprobe -v error -select_streams v:0 -show_entries frame=pts_time -of csv=p=0 journey.mp4`,
and each frame was looked at after extracting it by index with
`ffmpeg -i journey.mp4 -vf "select=eq(n\,I)" -fps_mode passthrough -frames:v 1 fI.png`.
Never seek this file with `-ss`: it returns a neighbouring frame, which produced a false
defect and off-by-one claims on 2026-10-06. Each frame stays on screen until the next.
The same table is `FOOTAGE_FRAMES` in `scripts/build_video_plan.py`.

| Frame | pts (s) | Visible |
|---|---|---|
| 0 | 0.000 | Leanback home screen |
| 1 | 0.755 | home screen, unchanged to the eye |
| 2 | 1.565 | home screen, unchanged to the eye |
| 3 | 1.783 | home screen, unchanged to the eye |
| 4 | 2.032 | home screen, unchanged to the eye |
| 5 | 2.188 | home screen, unchanged to the eye |
| 6 | 2.402 | home screen, the favourites label redrawn |
| 7 | 2.492 | home screen, unchanged to the eye |
| 8 | 3.994 | home screen, unchanged to the eye |
| 9 | 4.131 | home screen, unchanged to the eye |
| 10 | 4.169 | home screen, its last frame |
| 11 | 4.228 | black: the app cold-starts |
| 12 | 4.390 | black |
| 13 | 4.723 | black |
| 14 | 4.793 | black |
| 15 | 4.883 | black |
| 16 | 4.981 | black |
| 17 | 5.061 | black |
| 18 | 5.109 | black, on screen until the board appears |
| 19 | 8.856 | the board first shows: Not asked, What broke?, API NOT CHECKED |
| 20 | 9.056 | the same board, repainted |
| 21 | 10.074 | CHECKING; focus ring on Ask what changed |
| 22 | 10.277 | CHECKING |
| 23 | 10.428 | API REACHABLE; checkout-api ASKING, call in flight |
| 24 | 11.160 | checkout-api 12.9x, TEMPORAL CANDIDATE, Commit 4f1c2ab; other rows ASKING |
| 25 | 11.282 | payments-worker NOTHING TO REVERT |
| 26 | 11.403 | search-indexer CANNOT ATTRIBUTE |
| 27 | 11.513 | release-train CANNOT ATTRIBUTE |
| 28 | 11.630 | quiet-service INSUFFICIENT DATA: all five rows answered; static until 14.439 |
| 29 | 14.439 | Right: focus on Stage rollback |
| 30 | 15.296 | Center: Stage rollback drawn pressed |
| 31 | 15.847 | ROLLBACK STAGED, Roll back to 9b07e3d, lease 300s |
| 32 | 15.879 | lease 300s, focus settles on Stage rollback |
| 33 | 16.901 | lease 299s |
| 34 | 17.691 | lease 298s |
| 35 | 18.600 | lease 297s |
| 36 | 19.907 | lease 296s |
| 37 | 20.110 | Right: focus on Confirm |
| 38 | 20.765 | lease 295s |
| 39 | 21.250 | Center: Confirm drawn pressed; still ROLLBACK STAGED |
| 40 | 21.691 | RECORDED, no pipeline contacted; ROLLBACK RECORDED, NOT SENT |
| 41 | 21.812 | the same, legend Next press: Publish responder handoff; static until 26.290 |
| 42 | 26.290 | Center: scrolled to the handoff section, focus on Publish handoff, no handoff yet |
| 43 | 26.588 | the shared handoff: SHARED REVISION 13, HTTP 200 in 210 ms |
| 44 | 26.616 | the same handoff; the page finishes scrolling |
| 45 | 26.791 | the same handoff; the page finishes scrolling |
| 46 | 26.870 | the same handoff; the page finishes scrolling |
| 47 | 26.960 | the same handoff; the page finishes scrolling |
| 48 | 27.086 | the same handoff; the page finishes scrolling |
| 49 | 27.138 | the same handoff; the page finishes scrolling |
| 50 | 27.245 | the same handoff; the page finishes scrolling |
| 51 | 27.434 | the same handoff, the last frame; the clip ends at 27.64 at 25 fps |

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
  presses share one shorter beat, because the footage has already shown them at a
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

Seconds are content time; the 4 s title card comes before beat 1. Footage times are
`journey.mp4`'s own clock.

| # | Beat | Source | Seconds | Keys | On screen |
|---|---|---|---|---|---|
| 1 | `beat_01_tv_launch` | emulator 0.32 to 9.96 s | 9.64 | none (launch intent) | The Leanback home screen to 4.169 s, black from 4.228 s while the app cold-starts, the board from 8.856 s |
| 2 | `beat_02_tv_board` | emulator 9.96 to 14.40 s, 12.00 s held 1.52 s | 5.96 | none | CHECKING, checkout-api ASKING, then checkout-api 12.9x, TEMPORAL CANDIDATE, Commit 4f1c2ab (invented feed), then all five rows |
| 3 | `beat_03_tv_stage` | emulator 14.40 to 20.28 s | 5.88 | Right, Center | Focus on Stage rollback, Rollback staged, the lease counting down from 300 s |
| 4 | `beat_04_tv_confirm` | emulator 20.28 to 26.20 s | 5.92 | Right, Center | Focus on Confirm, RECORDED, no pipeline contacted, static on the board |
| 5 | `beat_05_tv_publish` | emulator 26.20 to 27.64 s, last frame held 2.52 s | 3.96 | Center | Publish handoff, the shared handoff, SHARED REVISION 13, HTTP 200 |
| 6 | `beat_06_desktop_board` | desktop | 12.028 | none | The same board in desktop Chromium at 1920x1080 CSS, focus on Ask what changed |
| 7 | `beat_07_board_on_load` | desktop | 18.019 | none | Five rows answered on load: Temporal candidate, Nothing to revert, Cannot attribute, Cannot attribute, Insufficient data |
| 8 | `beat_08_crowded_refusal` | desktop | 17.554 | Down x4, Center | release-train: Cannot attribute this, N runtime changes landed; Next: No rollback offered; Stage and Confirm disabled |
| 9 | `beat_09_named_with_odds` | desktop | 19.783 | Up x3, Center | checkout-api: the commit named as the only runtime change, its message quoted, 50.0% held-out precision (synthetic, at most 75 minutes of lag) |
| 10 | `beat_10_provenance` | desktop | 10.635 | none | OFFLINE FIXTURE stamp under the reading, dashed STAND-IN against Mercury's commits |
| 11 | `beat_11_stage_to_evidence` | desktop | 16.904 | Up, Right, Center, Right, Center, Center, Down | Rollback staged; RECORDED, no pipeline contacted, board not scrolled; the handoff's answer; Incident evidence: 50.0% over 58 namings in 1160 synthetic labelled cases |
| 12 | `beat_12_dpad` | desktop | 12.167 | Right, Center | Delivery velocity opens; the BACK legend changes to Back to the wall |
| 13 | `beat_13_fixtures` | desktop | 12.585 | Down, Back, Right, Center, Back | DORA answer with OFFLINE FIXTURE, scrolled within the panel; Back to the wall; Cloud spend answer with OFFLINE FIXTURE and SYNTHETIC figures; Back to the wall |
| 14 | `beat_14_build_check` | desktop | 12.817 | Down, Down, Center on Check | GET /health returned 200, the build's short SHA, GitHub live: no, fixture mode |

Content: 163.852 s, 31.36 s of it emulator footage (27.32 s played at 1x and 4.04 s of
held static frames). With the 4 s title card and the 3 s closing card the planned video
is 170.852 s, under the 175 s the sync gate allows.

## Words on the footage

Times are `journey.mp4`'s clock: a beat's start plus the measured start of the word in
the voice's ElevenLabs alignment, mapped through the holds. A caption cue that names a
value starts on the word that names it.

| Words | Caption from | Spoken from | The frame |
|---|---|---|---|
| "From the home screen" | 0.32 s | 0.32 s | the home screen, to 4.169 s (frame 10) |
| "The screen stays black while it loads" | 6.52 s | 6.52 s, ends 8.82 s | black from 4.228 s (frame 11); the board first shows at 8.856 s (frame 19) |
| "The board asks on its own" | 9.96 s | "asks" 10.46 s | CHECKING at 10.074 s (frame 21), ASKING at 10.428 s (frame 23) |
| "checkout-api, 12.9x baseline" | 11.91 s | 11.91 s | 12.9x at 11.160 s (frame 24), all rows at 11.630 s (frame 28) |
| "Right" | 14.40 s | 14.40 s | focus on Stage rollback at 14.439 s (frame 29) |
| "then Center" | 14.40 s | "center" 15.53 s | Stage rollback drawn pressed at 15.296 s (frame 30) |
| "A rollback is staged" | 16.41 s | 16.41 s | ROLLBACK STAGED, 300 s lease at 15.847 s (frame 31) |
| "Right" | 20.28 s | 20.28 s | focus on Confirm at 20.110 s (frame 37) |
| "then Center confirms" | 20.28 s | "center" 20.83 s | Confirm drawn pressed at 21.250 s (frame 39), still STAGED |
| "RECORDED, no pipeline contacted" | 21.87 s | 21.87 s | RECORDED at 21.691 s (frame 40) |
| "Center publishes the handoff" | 26.20 s | "Center" 26.20 s | the press scrolls to Publish handoff at 26.290 s (frame 42); the handoff at 26.588 s (frame 43) |
| "SHARED REVISION 13" | in the last frame's hold | in the hold | SHARED REVISION 13 since 26.588 s (frame 43) |

The title card before beat 1 says what the product is first: Mercury. An incident board
for the team's Fire TV. It names the deploy behind a spike only when it can. Smaller
lines under it name the two sources of the picture, in the order they play: Android TV
emulator footage, API 34, CI run 37475795991. Then a local run of `<sha7>` in a desktop
browser at 1920x1080, not the TV layout. Then: offline fixtures, record-only rollback.
The closing card repeats the run, the demo build and the commit, says the desktop part
is a desktop browser at 1920x1080, and says the emulator runtime receipt is a separate
record.

## Numbers policy for the recording

Numbers on screen are read off the screen, and they vary per run: the reading, the
number of changes in the release-train window, the lease, the latency and the SHA.
The spend figures are synthetic and are not read aloud. The emulator beats read two
figures off the footage: the 12.9x reading and SHARED REVISION 13.

Two figures are spoken from the script, because they describe the labelled corpus, not
this run. Both are on the held-out split of the synthetic corpus, with the runtime
filter shipped on 2026-09-27:

* 90.0% named nobody on a real anomaly (beat 7);
* 50.0% precision over 58 namings (beat 9). Beat 9 also says the precision holds only
  if a fault shows within 75 minutes, the generator's delay ceiling, which the window
  equals.

Both are written by `python scripts/attribution_split.py` into
`attribution_holdout_summary.json`. The board prints the same two at the current
master, and the README quotes them. Beat 11 reads the 58 namings and the 1160
synthetic cases off the evidence sentence on screen, which prints the same summary.
`tests/video/test_emulator_open_cut.py` compares the captions with the summary.

Earlier takes quoted the in-sample 81.1% and 52.2% over 113 namings, and then the
pre-filter held-out 93.1% and 62.5% over 40. Neither is current, and the takes that
spoke them are superseded. If a re-run moves the figures, change the beat in
`scripts/build_video_plan.py`, rerun it, and re-render that beat.
`video/generate-narration.py` synthesizes only the beats whose words changed.
