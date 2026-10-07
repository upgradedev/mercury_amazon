# Demo video

**Status: rendered locally, not uploaded.** The last render is the take at `f7512bf`,
recorded on 2026-10-07. It is the cut first rendered at `a85056b` (below), with the
desktop part recorded again at the branch head. It opens on the Android TV emulator
footage from CI, and it fixes the problems a judge review found in the take at
`81d6144`. Nothing has a public link until the owner uploads it, and nothing in this
directory is the video itself.

## The take at f7512bf

| Item | Value |
|---|---|
| Recorded commit | `f7512bffaadd231079bfa8c0da540ff5fe7bfc94`, reported by the local server's own `/health` (port 8875, `MERCURY_OFFLINE=1`) before the take and in the capture receipt; the board's Check line reads Build f7512bf |
| File | `mercury-demo.mp4`, in the workspace folder `reviews/videos_20261006/mercury_amazon/output/`, outside git |
| Length | 163.09 s (ffprobe format duration), 1920x1080, 25 fps (4077 frames, ffprobe `-count_frames`), AAC 48 kHz, -16.4 LUFS integrated (ffmpeg ebur128) |
| SHA-256 | `3ef0cc63d998ffd96d701289821b386fe504db7d4dfe5728c61b6574c6c8dafb` (15289926 bytes) |
| Sync gate | `scripts/verify_video_sync.py`, unchanged (git blob `83779fd`), run in the output folder: "verify_video_sync: ALL SYNC GATES PASSED", 11 of 11 checks PASS, exit 0 (`sync-gate.txt` beside the mp4) |
| Gate selftest | `tests/video/verify_gate_selftest.py`, exit 0: the gate passes the good file and fails the mis-ordered, caption-bleeding and out-of-sync ones |
| Capture | desktop Chromium at 1920x1080 CSS, 9 desktop beats, every press consumed and on plan, no page errors, trim lead 2.0 s (`capture/capture-receipt.json`); the raw `production.webm` was deleted after the build |
| Receipt | `video-receipt.json` beside the mp4: ffprobe duration, SHA-256, the recorded commit, the gate output, the selftest result, ElevenLabs characters, the footage provenance and both labels |
| Characters synthesized | 0 for this take. The words of all 13 beats are unchanged since `a85056b`, so every beat reused its audio by cache key; `synthesis-log.jsonl` still has 25 lines and 3398 characters |
| Unchanged from a85056b | the plan, the narration and captions, the footage cut and holds, and the wording of the cards and labels; the cards and the desktop label now name f7512bf |
| Previous take | the take at `a85056b` is kept as `reviews/videos_20261006/mercury_amazon/superseded_a85056b/` |

Checked in this take by frame index (`select=eq(n\,I)`, or `between(n\,A\,B)` for a
run), never by seeking. Frames were extracted at 1, 3, 5, 8, 12, 20 and 28 s, at the
start of each of the 40 caption cues and over the last 5 s, and looked at.

* The title card runs to frame 99 and the closing card from frame 4002 to the last
  frame, 4076. The mean luma of the label band is the same on all 583 emulator frames
  (100 to 682) and on all 3319 desktop frames (683 to 4001), so neither label is ever
  missing or covered. The desktop label reads "Desktop browser at 1920x1080, local run
  of f7512bf, offline fixtures. Not the TV."
* The RECORDED board holds to frame 2810 and the page scrolls on 2811. The handoff,
  SHARED REVISION 1, first shows on frame 2813, 4 frames before "Center publishes the
  handoff." on 2817.
* The evidence sentence first shows on frame 2867, 6 frames before its caption on 2873.
* The release-train verdict first shows on frame 1423 (its caption on 1439), the
  checkout-api verdict on 1857 ("On checkout-api," on 1875), and the Delivery velocity
  panel with Back to the wall on 3212 (its caption on 3223).

## The cut, first rendered at a85056b: emulator footage first, every source labelled

The table and the frame numbers in this section are of the take at `a85056b`, which the
take at f7512bf supersedes.

| Item | Value |
|---|---|
| Recorded commit | `a85056b8469435ca473d95fe6285a04dbfc82534`, reported by the local server's own `/health` during the take; the board's Check line reads Build a85056b |
| File | `mercury-demo.mp4`, now in the workspace folder `reviews/videos_20261006/mercury_amazon/superseded_a85056b/`, outside git |
| Length | 163.09 s (ffprobe format duration), 1920x1080, 25 fps (4077 frames), AAC 48 kHz, -16.4 LUFS integrated (ffmpeg ebur128) |
| SHA-256 | `feef1e70d9da947f006921096cfb1d52f364316feb0bc0edccab67fe101c0e09` (15032768 bytes) |
| Sync gate | `scripts/verify_video_sync.py`, unchanged: "verify_video_sync: ALL SYNC GATES PASSED", 11 of 11 checks PASS, exit 0 (`sync-gate.txt` beside the mp4) |
| Capture | desktop Chromium at 1920x1080 CSS, every press on plan, no page errors (`capture/capture-receipt.json`); the raw `production.webm` was deleted after the build |
| Receipt | `video-receipt.json` beside the mp4: ffprobe duration, SHA-256, the recorded commit, the gate's inputs, ElevenLabs characters, the footage provenance and both labels |
| Plan | `scripts/build_video_plan.py`, which writes `narration.json` and `cue_sheet.json`; `SHOT_LIST.md` lists the beats and every frame of the footage |
| Content | 156.09 s in 13 beats: 23.32 s of emulator footage in 4 beats (18.76 s played at 1x, 4.56 s of held static frames), then 132.77 s of desktop take in 9 beats |
| Planned length | 163.09 s with the 4 s title card and the 3 s closing card; the gate allows under 175 s |
| Footage | `journey.mp4` from the artifact `mercury-android-tv-footage-f423ba57ecfe688b8dafe899e06ab29dfdb7a90c`, CI run [37475795991](https://github.com/upgradedev/mercury_amazon/actions/runs/37475795991), from 8.88 s to its end |
| Desktop picture | Desktop Chromium at 1920x1080 CSS pixels, the desktop layout, not the Fire TV WebView's 960x540 CSS layout (see below) |
| Narration | Synthesized 2026-10-06 into the workspace folder `reviews/videos_20261006/mercury_amazon/narration/`, outside git |
| Voice | ElevenLabs premade voice `pNInz6obpgDQGcFmaJgB` (Adam), model `eleven_multilingual_v2`, through the `with-timestamps` endpoint |
| Characters synthesized | 1020 for this take (`synthesis-log.jsonl`): the 5 beats whose words changed, 941 characters, and 79 for an opener that did not fit its footage and was dropped. The other 8 beats reuse earlier audio by cache key. 3398 characters were sent in all calls on 2026-10-06 |

### What the judge review of the take at 81d6144 found, and what changed

Every frame below is a frame of the take at a85056b, read by index
(`select=eq(n\,I)`), never by seeking. "First" means the frames before it were looked
at and do not show it yet.

* **The launch.** The take showed 3.9 s of an unchanged home screen and implied the app
  was opened from it. CI started it with an `am start` of its LEANBACK_LAUNCHER intent
  (`launcher.txt`), and no frame shows focus on a tile. A re-record that presses Center
  on the tile would also confirm a rollback and publish a handoff on the live public
  demo, so it was not made, and the take still never shows a D-pad launch. It now
  starts at 8.88 s of `journey.mp4`, the first 25 fps frame that shows the board
  (source frame 19 at 8.856 s; frame 100 of the take), and no caption claims a launch.
* **The black screen.** The 4.6 s of black cold start (source frames 11 to 18) is no
  longer shown. Nothing is cut from the middle of the footage.
* **The unlabelled commits on the emulator board.** The board stamps the 12.9x reading
  OFFLINE FIXTURE, not Commit 4f1c2ab or the rollback target 9b07e3d, which are invented
  records in `src/infrastructure/fixtures/deploy_feed_fixture.json`, not commits of any
  repository. A second label line under the footage says so on every emulator frame
  (100 to 682). The provenance beat now says "On this board, the reading and the commit
  each carry a stamp", over the desktop board, where both are stamped.
* **The change at the cut.** The first desktop caption (from frame 683) says the local
  board has its own fixtures, so the commits differ, and its handoff starts again at
  revision 1. On screen the commit goes from 4f1c2ab to f423ba5, the target from 9b07e3d
  to 5891007, and the handoff from SHARED REVISION 13 to SHARED REVISION 1.
* **No desktop label.** A label under the desktop picture, on every desktop frame (683 to
  4001), reads "Desktop browser at 1920x1080, local run of a85056b, offline fixtures.
  Not the TV." and "The key legend is the Fire TV build's; each key goes through the
  same D-pad bridge." The mean luma of the label band is the same on all 583 emulator
  frames and on all 3319 desktop frames, so neither label is ever missing or covered.
* **58 named before it showed.** The odds caption no longer says "over 58 namings". 58
  is said once, on "Down shows the evidence behind the odds". The evidence sentence,
  which reads "over 58 namings in 1160 synthetic labelled cases" at full resolution,
  first shows on frame 2870; that caption starts on frame 2873.
* **90.0% never shown.** The board never prints the held-out refusal rate, so the take
  no longer speaks it. It says "Four of the five rows name no commit" over the board
  that shows four rows naming none (frame 1230).
* **Sub-second order.** "Up, up, up, center" is now spoken and pressed first: focus is
  first on checkout-api on frame 1847 and its verdict first shows on 1855, before "On
  checkout-api," on 1875. Center on Delivery velocity goes 0.35 s before its caption:
  the panel and Back to the wall first show on frame 3211, the caption on 3223. The
  release-train verdict first shows on frame 1423, before its caption on 1439.
* **Publish against its caption.** The judge noted the handoff showing 0.1 s before
  "Center publishes the handoff.". That order is the take's rule, a result before the
  caption that names it, so it is kept: the page scrolls on frame 2810 and the handoff
  first shows on frame 2812, 5 frames before the caption on frame 2817. The RECORDED
  board is up to frame 2809, so its caption's last 7 frames are over the handoff
  section, which still reads 03 RECORDED ONLY.

Speech onsets from silencedetect match the caption starts that follow a pause, within
0.18 s. Cues inside continuous speech start on their aligned words: "Four of the five
rows" 0.09 s after the word, "A refusal" 0.19 s before it, and every other new cue within
0.06 s.

Checked and unchanged: the emulator presses, the 12.9x, RECORDED and SHARED REVISION 13
cues (the footage from 14.40 s on is cut and worded as before), the title and closing
cards, and the closing line "The emulator footage came from CI, not a Fire TV device."

### What it shows

* **The title card** (4 s) says what the product is first: "Mercury. An incident board
  for the team's Fire TV. It names the deploy behind a spike only when it can." Smaller
  lines name the two sources in the order they play: "Android TV emulator footage, API
  34, CI run 37475795991." and "Then a local run of `<sha7>` in a desktop browser at
  1920x1080, not the TV layout." Then "Offline fixtures, record-only rollback."
* **The emulator footage** opens the content: `journey.mp4` from 8.88 s to its end at
  27.64 s, at 1x, with two static frames held longer. It is the debug APK built at
  `f423ba5`, on an AOSP Android TV emulator (x86), Android 14 / API 34, loading the
  public demo, build `ea2cff5`, which is record-only. The journey, by source frame (the
  full table is in `SHOT_LIST.md`):
  * the board as it first shows at 8.856 s (frame 19), Not asked;
  * CHECKING at 10.074 s, ASKING at 10.428 s, then checkout-api 12.9x, TEMPORAL
    CANDIDATE, Commit 4f1c2ab at 11.160 s (frame 24), a record from the demo's
    invented, display-only feed; all five rows at 11.630 s;
  * Right at 14.439 s and Center at 15.296 s: Rollback staged at 15.847 s, the lease
    counting down;
  * Right at 20.110 s and Center at 21.250 s (frame 39, still STAGED): RECORDED, no
    pipeline contacted at 21.691 s (frame 40), static until 26.290 s;
  * Center: the page scrolls to Publish handoff at 26.290 s (frame 42), and the
    responder handoff shows at 26.588 s (frame 43), SHARED REVISION 13, HTTP 200.

  The D-pad presses are key codes sent by the CI script. The label under the picture
  names the emulator, the APK, the demo build and the CI run, and says the commits are
  invented records. Four beats of narration cover it.
* **The desktop take** follows, with its own label. Its first caption says it is the
  same board in a desktop browser, run locally from this commit, with its own fixtures.
  The local board names one of Mercury's own commits, stamped STAND-IN. The desktop
  journey presses the same keys as the 2026-10-01 take. The stage, confirm and handoff
  presses share one beat, each on the word that names it.
* **The closing card** (3 s) repeats the CI run, the demo build and the commit, says the
  desktop part is a desktop browser at 1920x1080, and says the emulator runtime receipt
  is a separate record.

### Captions and words follow the picture

No caption names a value or a state, such as 12.9x, RECORDED or the published handoff,
more than 0.5 s before the frame that shows it, and a spoken word naming a press lands
within 0.5 s of the press's visible effect. Over the footage, each beat's caption cues
start on spoken words read off the voice's character alignment (`marks` in the plan),
and `tests/video/test_emulator_open_cut.py` checks every such cue and press against the
frame table. The closest calls: "center" in the confirm beat is spoken 0.42 s before
Confirm is drawn pressed, and the publish caption names the handoff 0.39 s before it
shows. In the desktop take every named result shows before its caption. At f7512bf that
is by 6 frames for the evidence sentence, 4 for the handoff, 11 for the Delivery
velocity panel and 16 or more for the verdicts; at a85056b it was 3, 5 and 12 or more.
`video/capture-local.py` presses each such key on its spoken
word (the odds, stage-to-evidence and build-check beats) or before the caption that
names its result (the release-train, Delivery velocity and cloud spend presses).

### Why the desktop part is not at the TV viewport

The Fire TV WebView lays the page out at 960x540 CSS pixels at a device scale factor of
2, and the Leanback app injects `MercuryHost`, which turns on `html.tv-host` and the key
bar. The emulator footage shows that layout. On 2026-10-06 the whole scripted journey
was rehearsed at that viewport, with DSF 2, the `MercuryHost` stub the browser tests
use, a 1920x1080 recording and a local server on port 8875 at `e76e6da`. Every press,
focus check and awaited answer passed unchanged, with no page errors
(`reviews/videos_20261006/mercury_amazon/rehearsal_tv/capture/capture-receipt.json`).
The frames did not read well. Headless Chromium films CSS pixels: Playwright's recorder
wrote the 960x540 page into the top-left quarter of the 1920x1080 file, and a raw CDP
screencast, in old and new headless, also returned 960x540 frames. The TV layout would
reach the video as a 960x540 picture upscaled, with half the detail of the desktop take.
The take therefore stays at 1920x1080 CSS pixels, and the title card, the label, the
narration and the closing card call it a desktop browser. `MERCURY_CAPTURE_VIEWPORT=tv`
reruns the rehearsal.

### What the footage is, and what it is not

The emulator footage is footage from CI, not a Fire TV device. The Fire TV track allows
the Android TV Emulator: the official FAQ says "an emulator (Android TV Emulator or the
Fire TV/Vega simulator) is fine". The footage is also not a runtime receipt. Gate J4
rests on the separate receipt, `android_tv_runtime_receipt.json`, which
`.github/workflows/android-tv-emulator.yml` and `scripts/android_tv_smoke.sh` wrote in
run 37464864870. The footage workflow writes no receipt and leaves J4 untouched.

The footage is the one CI run 37475795991 filmed, not this repository at the recorded
commit. It loads the public demo, which served `ea2cff5`, and the desktop take is a
local run of the recorded commit. The title card, both labels and the closing card name
both.

### How the footage opens Mercury

A judge review of the take at `f7512bf` found that the footage never shows Mercury
being opened from the Leanback home screen. `scripts/android_tv_footage.sh` started it
with `am start` of the `LEANBACK_LAUNCHER` intent, and the cut starts on the loaded
board. The script now opens it the way a viewer would, with the key codes a TV remote
emits:

* After the install it waits 5 s, presses Home, and records the home activity
  (`home-activity.txt`).
* It takes a `uiautomator dump` and `scripts/android_tv_tile_focus.py` reads it. The
  helper finds the focused node and the node whose label contains "Mercury" (the app
  label is "Mercury Incident Board"), and returns the D-pad key that moves focus
  towards the tile: Up or Down until the rows overlap, then Left or Right. When no tile
  names Mercury, it moves to the launcher's Apps entry and opens it with Center, or
  sweeps along the rows. Each move is followed by half of `FOOTAGE_PACE_SECONDS`, then
  the next dump.
* Once a dump shows that the focused node, or a node inside it, names Mercury, the
  script holds that frame for `FOOTAGE_PACE_SECONDS` and presses `KEYCODE_DPAD_CENTER`.
  It then waits up to 30 s for Mercury's activity to be resumed before it waits for
  the page, and writes the resumed-activity line to `launcher.txt`.
* The walk is bounded: at most `FOOTAGE_MAX_DPAD_PRESSES` presses (default 20) and
  75 s. If the tile is not focused within that bound, or Center does not start Mercury,
  the script falls back to `am start` as before. It does not hide the fallback.

Which path was used is recorded twice. `timeline.tsv` gets a row
`launch path: dpad (...)` or `launch path: am start fallback (<reason>)`, and
`footage-provenance.json` gets `launch_path` (`dpad` or `am_start_fallback`),
`launch_presses`, `launch_detail` and `home_activity`. Every dump is kept as
`ui/NN.xml`, with each decision in `ui/decisions.tsv`. The rest of the journey (the
opening answer, then Stage, Confirm and Publish) is unchanged.

The first run of this script, CI run
[37572841698](https://github.com/upgradedev/mercury_amazon/actions/runs/37572841698)
(pull request merge commit `6cc72f8`, branch head `c2264fb`), took the D-pad path.
Its home activity was `com.google.android.tvlauncher/.MainActivity`. The dumps chose
Up to the Home tab, Right to the Apps tab, then Down twice, from Live TV onto the tile
labelled "Mercury Incident Board": 4 moves, then Center, so `launch_presses` is 5. Its
`journey.mp4` has 81 variable-rate frames in 57.34 s, read by index with ffprobe and
`select=eq(n\,I)`. Frame 32 (16.05 s) has focus on Live TV in the Apps tab. Frame 33
(21.00 s) has focus on the Mercury tile, with its label shown. The launcher answers
Center at frame 39 (28.81 s), the screen is black from frame 45 (32.86 s) while
Mercury starts, and the board is drawn by frame 50 (33.19 s). The rest of the journey
follows as before and ends with the shared handoff. The focused tile is on screen for
7.8 s, not the 3 s pace: the half pace after the last move and the dump that confirms
focus come before it.

The take at `f7512bf` still uses the footage of run 37475795991, which was launched
with `am start`. `FOOTAGE_CUTS`, `FOOTAGE_HOLDS` and the expected provenance in
`scripts/build_video_plan.py` belong to that footage and are unchanged. A take that
shows the D-pad launch needs those cut again against a new footage run.

### How the footage is cut

The screenrecord writes a frame only when the screen changes (52 frames in 27.62 s).
Its frame times were read by index with ffprobe and each frame was looked at by index
(`select=eq(n\,I)`); seeking it with `-ss` returns a neighbouring frame.
`video/build-video.py` converts it to 25 fps by holding each frame until the next one,
then cuts it by frame number:

* it starts at 8.88 s, the first 25 fps frame showing the board; the home screen and
  the black cold start before it are not shown;
* from there nothing is sped up or slowed, and nothing is cut out of the middle;
* two frames the source shows still are held longer: the answered board for 2.04 s at
  12.00 s (still in the source from 11.630 s to 14.439 s) and the last frame, the
  shared handoff, for 2.52 s. `scripts/build_video_plan.py` refuses a hold on a frame
  the source replaces within a second.

The cut points are `FOOTAGE_CUTS` and the holds `FOOTAGE_HOLDS` in
`scripts/build_video_plan.py`, each on a 25 fps frame. `video/generate-narration.py`
holds each emulator beat for exactly its window plus its holds. It refuses a beat whose
audio plus 0.3 s does not fit, rather than stretch the footage. `video/build-video.py`
refuses footage whose provenance (run, commits, OS, device, byte count) differs from
the one the plan names.

### Recording and composing it

The compose splices the footage at the start of the gate's `screencast` segment, so the
segments stay title, screencast, web and outro. The pixel probes still read card,
content, content and card: the screencast's midpoint falls in the desktop take. The
captions are burned once, on the joined content, so they run on the narration's clock
from the first word over the footage. Both pictures are 1568x882 at the top of the
frame, with their labels under them and the captions under those.

```bash
export MERCURY_VIDEO_ROOT=C:/dev/solutions/private_amazon_devpost/reviews/videos_20261006/mercury_amazon
export MERCURY_EMULATOR_FOOTAGE=<the unpacked mercury-android-tv-footage-f423ba5... artifact folder>
export MERCURY_RELEASE_SHA=$(git rev-parse HEAD)    # the commit the local server reports
export FFMPEG=/path/to/ffmpeg FFPROBE=/path/to/ffprobe
MERCURY_OFFLINE=1 python -m uvicorn src.interfaces.mcp_server:app --port 8875 &
MERCURY_CAPTURE_URL=http://127.0.0.1:8875/ python video/capture-local.py
python video/build-video.py
cd "$MERCURY_VIDEO_ROOT/output" && VIDEO_MANIFEST=video_manifest.json \
  CAPTION_WINDOWS=caption_windows.json python <repo>/scripts/verify_video_sync.py mercury-demo.mp4
```

The narration is already in `narration/`. Rerunning `video/generate-narration.py`
reuses every beat whose words have not changed and calls ElevenLabs for none of them.
The capture skips the four emulator beats: its timeline starts at the first desktop
beat, and its receipt records that start as `narrationStartSeconds`.

## The previous render: the 2026-10-01 take

| Item | Value |
|---|---|
| Recorded commit | `9620743b848d041fbfc098ae371177ee5af80937` (master), reported by the server's own `/health` during the take |
| File | `mercury-demo.mp4`, in the workspace folder `reviews/videos_muse_20261001/mercury_amazon/output/`, outside git |
| Length | 170.61 s (ffprobe), 1920x1080, 25 fps, AAC 48 kHz, -16.3 LUFS integrated |
| SHA-256 | `792cee861c1789bee7daa63ab94dfe791aad148b8ed597ed1180af0aa53db47c` |
| Voice | ElevenLabs premade voice `pNInz6obpgDQGcFmaJgB` (Adam), model `eleven_multilingual_v2` |
| Characters synthesized | 2249 in the final narration, 0 new: all 11 beats reused from the `reviews/videos_muse_20260929` cache |
| Sync gate | `scripts/verify_video_sync.py`: all checks passed |

It predates the emulator footage: its picture is the desktop capture from the first beat
to the last, and its closing beat said so. The 2026-10-06 take replaces it. Next to the mp4 sit
`video-receipt.json`, `captions.en.srt`, `sync-gate.txt` and the gate's two inputs. The
per-beat audio, `timing.json` and the capture with its own receipt are in the sibling
`narration/` and `capture/` folders.

Its desktop journey is the one the 2026-10-06 take keeps:

* One continuous take of the page served by
  `MERCURY_OFFLINE=1 python -m uvicorn src.interfaces.mcp_server:app --port 8873`,
  recorded by desktop Chromium at 1920x1080. Every key is sent through
  `window.navigateDpad`, the bridge the Leanback `MainActivity` calls for the remote. No
  mouse, no edits, no speed changes. The capture adds one 1x1 px marker in the
  bottom-right corner and flips its colour after each press, only so the recorder is
  sent the frame the page is showing (see Known weaknesses).
* The board's own labels stay in frame: OFFLINE FIXTURE on the metric, STAND-IN on the
  commit, record-only on the rollback, and SYNTHETIC on the spend figures.
* After Confirm the board stays where it is: the large figure reads RECORDED, no
  pipeline contacted, under Rollback recorded, not sent, and the key legend reads Next
  press: Publish responder handoff. The capture refuses to continue unless the page is
  still at the top at that moment. Center then publishes the handoff, and Down lands
  on the evidence sentence, 50.0% over 58 namings in 1160 synthetic labelled cases.
* The runtime filter is named on the board: the checkout-api verdict reads Only runtime
  change, and release-train reads 5 runtime changes landed.
* The held-out figures are the ones the board and the README print: 90.0% refusals, and
  50.0% precision over 58 namings if a fault shows within 75 minutes. They are unchanged
  at the current master. The take at a85056b speaks 50.0% where the board prints it and
  58 over the evidence sentence, and does not speak 90.0%, which the board never prints.
* The product makes no sound. The narration carries the story; Read aloud stays off.
* The picture was shown at 87.5% so the captions sit in a band under it and never
  cover the board. The page itself was captured at full 1920x1080.

Earlier takes, all superseded:

* `81d6144`, the first take reviewed by a judge, 170.852 s, SHA-256
  `e4a79672bec92ffbf188bfa8cdeedf7917ed177e07f628a203e3aefad337066c`, kept as
  `reviews/videos_20261006/mercury_amazon/superseded_81d6144/`. It showed the home
  screen and 4.6 s of black, and the problems listed above.
* `f862edb` and `6ef9d75`, composed and verified on 2026-10-06 but not kept. In the
  first the handoff and the evidence sentence came up 0.4 s and 0.2 s after their
  captions; in the second 0.48 s and 0.40 s before them, with 14 frames of the RECORDED
  caption over the handoff section. The publish and Down presses were moved to 0.15 s
  before their words.
* `48010c9`, the first 2026-10-06 take with the same plan and narration, 170.852 s,
  SHA-256 `6d8c0d457fa77dd49160e7c65cf52dc9ba630f5a2718a1c7bcf55b17b51690da`, kept as
  `reviews/videos_20261006/mercury_amazon/superseded_48010c9/`.
* `0aed20a` (audit branch), 170.61 s, SHA-256
  `8f5f3c34db92a1a8b7fec8225839836e7d40a02fcb9ea397c779f301f7983ca2`, in
  `reviews/videos_muse_20260929/mercury_amazon/output/`. It shows the pre-candidate
  board ("Attributed" headline), so it must not be uploaded.
* `df5db06`, in `reviews/videos_20260928/`. It predates the audit build (no parked ring
  after Confirm). It was captured without reduced-motion emulation, so headline frames
  in the scramble window show scrambled glyphs.
* `bcadcdc`, kept as `superseded_bcadcdc/`. Its last beat held "Sending GET .../health"
  throughout, because the recorder missed the frame (fixed by the repaint marker).
* `ad12202`, in `reviews/videos_20260927/`. It showed the page scrolling to the rollback
  steps after Confirm, and How it answers as prose under the board.
* `cf4ae18`, in `reviews/videos_20260926/`. It spoke the in-sample 81.1% and 52.2% over
  113 namings and showed a 60 minute window, which the board no longer prints.
* `924a58c`, kept as `superseded_924a58c/`. Its captions were burned 4 s late, because
  the subtitles filter ran before the title card was joined. One beat gave the wrong
  reason for the spend fixture.

## How it is produced

The pipeline is the submission kit's, adapted to this repository. Each beat is
synthesized alone and measured. A desktop beat's picture is held to that measured
length; an emulator beat's audio must fit its footage window. Either way the voice
cannot drift from the picture.

1. `python scripts/build_video_plan.py` writes `video/narration.json` and
   `video/cue_sheet.json` from one beat list. Each beat has the spoken text, the
   caption text, the action on screen and its source (emulator footage or desktop).
2. `python video/generate-narration.py` synthesizes each beat with ElevenLabs, measures
   it with ffprobe, and holds it for its length plus 0.65 s, or for its footage window.
   It writes `timing.json` and the captions. A caption cue starts on its spoken mark,
   read off the voice's character alignment, or else at a measured pause in the voice.
3. `python video/capture-local.py` refuses to record unless the server's `/health`
   reports the commit being recorded, waits until all five board rows have answered,
   then drives the desktop journey beat by beat, each named press on its spoken word.
   Every press checks which control took focus and every answer is awaited from the
   server; a journey that drifts aborts.
4. `python video/build-video.py` cuts the footage, trims the capture to the rest of the
   narration, joins them, adds the two cards, burns the captions, mixes the beats at
   their measured starts, normalises to -16 LUFS, and checks the result is within one
   frame of the planned length.
5. `python scripts/verify_video_sync.py mercury-demo.mp4`, run in the output folder,
   measures the finished file: audio against video length, caption windows, and the
   card, content, content, card order read from the pixels. The screencast segment is
   the footage then the desktop take; web is the last desktop beat.
   `python tests/video/verify_gate_selftest.py` proves the gate still fails on a
   mis-ordered, caption-bleeding or out-of-sync file.

The environment for steps 2 to 5: `MERCURY_VIDEO_ROOT` (the output folder),
`MERCURY_RELEASE_SHA` (the recorded commit), `MERCURY_EMULATOR_FOOTAGE` (step 4), `FFMPEG`,
`FFPROBE`, and for step 2 `ELEVENLABS_API_KEY`, which is read from the environment and
never printed or stored. The capture reads `MERCURY_CAPTURE_URL` (default port 8803).

## The footage workflow

`.github/workflows/android-tv-footage.yml` films the D-pad journey on the Android TV
emulator in hosted CI, using `scripts/android_tv_footage.sh`. The journey is the
Leanback home screen, the launch (an `am start` of the LEANBACK_LAUNCHER intent, not a
D-pad press on a tile, so the take does not show it), the opening answer, then Stage,
Confirm (record-only) and Publish, paced so a viewer can follow. A run confirms a
rollback and publishes a handoff on the live public demo, so it is not rerun casually. `screenrecord` is the primary capture. A
1 fps screencap sequence is assembled as a fallback, because the emulator's software
GPU can break `screenrecord`.

The artifact `mercury-android-tv-footage-<sha>` holds `journey.mp4`, `frames-1fps.mp4`,
`timeline.tsv` (seconds per key press and per answer, on the script's clock) and
`footage-provenance.json`. The provenance file names the build the public demo served
while it was recorded. The footage workflow lives in its own files, because editing
the runtime receipt's workflow or script would invalidate the committed J4 receipt.

## Re-rendering one beat

Edit the beat in `scripts/build_video_plan.py` and rerun it. `generate-narration.py`
then re-synthesizes only the beat whose words changed and reuses the rest, so every
other beat keeps its measured length. For a desktop beat, record again and compose
again. For an emulator beat, the new words must fit its footage window. To re-roll a
beat without changing its words, set `NARRATION_FORCE=beat_10_stage_to_evidence`.

Any new commit changes what the desktop board shows, because in offline mode the commit
it names is one of this repository's own. Restart the server after committing and record
at that commit; the title card and the Check line both name it.

## Known weaknesses

* The footage is an AOSP Android TV emulator in CI, not a Fire TV device. It loads the
  public demo (`ea2cff5`), not a local run of the recorded commit.
* The desktop take is a desktop browser, not the APK.
* The footage never shows the app being opened from the launcher: CI opened it by
  intent, and the take starts on the board. Two static frames of the footage are held
  longer, 4.56 s in all, so the words fit before the next press.
* The desktop take is the desktop layout at 1920x1080 CSS pixels, not the Fire TV
  WebView's 960x540 layout, because headless Chromium films that layout at half the
  detail (see above).
* The merged stage, confirm and handoff beat presses faster than the 2026-10-01 take
  did, because each press now lands on the word that names it.
* The named commit is one of this repository's own on the desktop, and a hand-written
  stand-in on the public demo. The metric is generated. The board stamps the metric
  and the desktop commit; the public demo's board stamps only the metric, so the label
  under the footage stamps its commits.
* The desktop page's footer still says "Fire TV remote:" and "Exit to the Fire TV
  launcher". The desktop label says the picture is not the TV.
* The board's headline scramble animation is suppressed in the desktop take: the
  capture emulates `prefers-reduced-motion: reduce`, so no frame shows scrambled glyphs.
  On a real TV with motion enabled the animation still plays for under a second.
* Chromium's screencast drops a frame painted before the previous one is acknowledged,
  and then sends nothing until the page paints again. A very fast answer could be
  missing from the recording although the page shows it. The capture flips a 1x1 px
  marker three times after every press to force those paints.
