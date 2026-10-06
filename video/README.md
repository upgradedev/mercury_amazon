# Demo video

**Status: rendered locally, not uploaded.** The last render is the 2026-10-06 take at
`81d6144`, which opens on the Android TV emulator footage from CI. Nothing has a public
link until the owner uploads it, and nothing in this directory is the video itself.

## The 2026-10-06 take: emulator footage first

| Item | Value |
|---|---|
| Recorded commit | `81d61446f6100a82e3d0e7c23e16e8992178c4ac`, reported by the local server's own `/health` during the take; the board's Check line reads Build 81d6144 |
| File | `mercury-demo.mp4`, in the workspace folder `reviews/videos_20261006/mercury_amazon/output/`, outside git |
| Length | 170.852 s (ffprobe format duration), 1920x1080, 25 fps (4271 frames), AAC 48 kHz, -16.4 LUFS integrated (ffmpeg ebur128) |
| SHA-256 | `e4a79672bec92ffbf188bfa8cdeedf7917ed177e07f628a203e3aefad337066c` (16915138 bytes) |
| Sync gate | `scripts/verify_video_sync.py`, unchanged: "verify_video_sync: ALL SYNC GATES PASSED", 11 of 11 checks PASS, exit 0 (`sync-gate.txt` beside the mp4). `tests/video/verify_gate_selftest.py` passed, exit 0 |
| Capture | desktop Chromium at 1920x1080 CSS, every press on plan, no page errors (`capture/capture-receipt.json`); the raw `production.webm` was deleted after the build |
| Receipt | `video-receipt.json` beside the mp4: ffprobe duration, SHA-256, the recorded commit, the gate output, ElevenLabs characters and the footage provenance |
| Plan | `scripts/build_video_plan.py`, which writes `narration.json` and `cue_sheet.json`; `SHOT_LIST.md` lists the beats and every frame of the footage |
| Content | 163.852 s in 14 beats: 31.36 s of emulator footage in 5 beats (27.32 s played at 1x, 4.04 s of held static frames), then 132.492 s of desktop take in 9 beats |
| Planned length | 170.852 s with the 4 s title card and the 3 s closing card; the gate allows under 175 s |
| Footage | `journey.mp4` from the artifact `mercury-android-tv-footage-f423ba57ecfe688b8dafe899e06ab29dfdb7a90c`, CI run [37475795991](https://github.com/upgradedev/mercury_amazon/actions/runs/37475795991) |
| Desktop picture | Desktop Chromium at 1920x1080 CSS pixels, the desktop layout, not the Fire TV WebView's 960x540 CSS layout (see below) |
| Narration | Synthesized 2026-10-06 into the workspace folder `reviews/videos_20261006/mercury_amazon/narration/`, outside git |
| Voice | ElevenLabs premade voice `pNInz6obpgDQGcFmaJgB` (Adam), model `eleven_multilingual_v2`, through the `with-timestamps` endpoint for the beats synthesized since the first 2026-10-06 run |
| Characters synthesized | 0 for this take: all 14 beats reused by cache key. 2378 were sent to ElevenLabs in all calls on 2026-10-06 (`synthesis-log.jsonl`): the 8 beats whose words changed were synthesized with their alignment; the 6 unchanged beats reuse earlier audio under their new beat numbers, with matching cache keys |

### What it shows

* **The title card** (4 s) says what the product is first: "Mercury. An incident board
  for the team's Fire TV. It names the deploy behind a spike only when it can." Smaller
  lines name the two sources in the order they play: "Android TV emulator footage, API
  34, CI run 37475795991." and "Then a local run of `<sha7>` in a desktop browser at
  1920x1080, not the TV layout." Then "Offline fixtures, record-only rollback."
* **The emulator footage** opens the content: `journey.mp4` from 0.32 s to its end at
  27.64 s, at 1x, with two static frames held longer. It is the debug APK built at
  `f423ba5`, on an AOSP Android TV emulator (x86), Android 14 / API 34, loading the
  public demo, build `ea2cff5`, which is record-only. The journey, by frame (the full
  table is in `SHOT_LIST.md`):
  * the Leanback home screen to 4.169 s (frame 10). The app is launched with its
    Leanback launcher intent, which shows nothing on the home screen;
  * black from 4.228 s (frame 11) while it cold-starts and its WebView loads the demo;
  * the board first shows at 8.856 s (frame 19), Not asked;
  * CHECKING at 10.074 s, ASKING at 10.428 s, then checkout-api 12.9x, TEMPORAL
    CANDIDATE, Commit 4f1c2ab at 11.160 s (frame 24), a deploy from the demo's
    invented, display-only feed; all five rows at 11.630 s;
  * Right at 14.439 s and Center at 15.296 s: Rollback staged at 15.847 s, the lease
    counting down;
  * Right at 20.110 s and Center at 21.250 s (frame 39, still STAGED): RECORDED, no
    pipeline contacted at 21.691 s (frame 40), static until 26.290 s;
  * Center: the page scrolls to Publish handoff at 26.290 s (frame 42), and the
    responder handoff shows at 26.588 s (frame 43), SHARED REVISION 13, HTTP 200.

  The D-pad presses are key codes sent by the CI script. A label under the picture
  reads "Android TV emulator (API 34), debug APK, public demo build ea2cff5, CI run
  37475795991" for as long as the footage plays. Five beats of narration cover it.
* **The desktop take** follows. The narration says once that it is the same board, run
  locally from this commit in a desktop browser at 1080p. The local board names one of
  Mercury's own commits, stamped STAND-IN, where the public demo names the invented
  feed's deploy. The desktop journey presses the same keys as the 2026-10-01 take. The
  stage, confirm and handoff presses share one beat, each on the word that names it.
* **The closing card** (3 s) repeats the CI run, the demo build and the commit, says the
  desktop part is a desktop browser at 1920x1080, and says the emulator runtime receipt
  is a separate record.

### Captions and words follow the picture

No caption names a value or a state, such as 12.9x, RECORDED or the published handoff,
more than 0.5 s before the frame that shows it, and a spoken word naming a press lands
within 0.5 s of the press's visible effect. Over the footage, each beat's caption cues
start on spoken words read off the voice's character alignment (`marks` in the plan),
and `tests/video/test_emulator_open_cut.py` checks every such cue and press against the
frame table. The closest calls: the board beat's first caption names asking 0.47 s
before ASKING shows, and "center" in the confirm beat is spoken 0.42 s before Confirm is
drawn pressed. In the desktop take, `video/capture-local.py` presses each such key on
its spoken word (the stage-to-evidence and build-check beats) or before the caption
that names its result (the release-train, checkout-api and cloud spend presses).

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
The take therefore stays at 1920x1080 CSS pixels, and the title card, the narration and
the closing card call it a desktop browser. `MERCURY_CAPTURE_VIEWPORT=tv` reruns the
rehearsal.

### What the footage is, and what it is not

The emulator footage is footage from CI, not a Fire TV device. The Fire TV track allows
the Android TV Emulator: the official FAQ says "an emulator (Android TV Emulator or the
Fire TV/Vega simulator) is fine". The footage is also not a runtime receipt. Gate J4
rests on the separate receipt, `android_tv_runtime_receipt.json`, which
`.github/workflows/android-tv-emulator.yml` and `scripts/android_tv_smoke.sh` wrote in
run 37464864870. The footage workflow writes no receipt and leaves J4 untouched.

The footage is the one CI run 37475795991 filmed, not this repository at the recorded
commit. It loads the public demo, which served `ea2cff5`, and the desktop take is a
local run of the recorded commit. The title card, the label and the closing card name
both.

### How the footage is cut

The screenrecord writes a frame only when the screen changes (52 frames in 27.62 s).
Its frame times were read by index with ffprobe and each frame was looked at by index
(`select=eq(n\,I)`); seeking it with `-ss` returns a neighbouring frame.
`video/build-video.py` converts it to 25 fps by holding each frame until the next one,
then cuts it by frame number:

* nothing is sped up or slowed, and nothing is cut out of the middle, so the 4.6 s cold
  start stays in;
* two frames the source shows still are held longer: the answered board for 1.52 s at
  12.00 s (still in the source from 11.630 s to 14.439 s) and the last frame, the
  shared handoff, for 2.52 s. `scripts/build_video_plan.py` refuses a hold on a frame
  the source replaces within a second;
* the first 0.32 s of the idle home screen is trimmed.

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
from the first word over the footage.

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
The capture skips the five emulator beats: its timeline starts at the first desktop
beat, and its receipt records that start as `narrationStartSeconds`.

After the compose, frames of the finished file were taken by frame number at every
caption cue that names a value or a press, and half a second later. Each named value
was on screen by then: 12.9x, Rollback staged, RECORDED, the handoff, SHARED REVISION
13, the release-train and checkout-api verdicts, the evidence sentence, SYNTHETIC and
the build line. The black caption leaves before the board first shows.

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
  at the current master, and the 2026-10-06 take speaks the same two.
* The product makes no sound. The narration carries the story; Read aloud stays off.
* The picture is shown at 87.5% so the captions sit in a band under it and never cover
  the board. The page itself was captured at full 1920x1080.

Earlier takes, all superseded:

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
Leanback home screen, the launch, the opening answer, then Stage, Confirm (record-only)
and Publish, paced so a viewer can follow. `screenrecord` is the primary capture. A
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
beat without changing its words, set `NARRATION_FORCE=beat_11_stage_to_evidence`.

Any new commit changes what the desktop board shows, because in offline mode the commit
it names is one of this repository's own. Restart the server after committing and record
at that commit; the title card and the Check line both name it.

## Known weaknesses

* The footage is an AOSP Android TV emulator in CI, not a Fire TV device. It loads the
  public demo (`ea2cff5`), not a local run of the recorded commit.
* The desktop take is a desktop browser, not the APK.
* The emulator's cold start is 4.6 s of black on screen, kept at 1x. Two static frames
  of the footage are held longer, 4.04 s in all, so the words fit before the next press.
* The desktop take is the desktop layout at 1920x1080 CSS pixels, not the Fire TV
  WebView's 960x540 layout, because headless Chromium films that layout at half the
  detail (see above).
* The merged stage, confirm and handoff beat presses faster than the 2026-10-01 take
  did, because each press now lands on the word that names it.
* The named commit is one of this repository's own on the desktop, and a hand-written
  stand-in on the public demo. The metric is generated. The board labels all three.
* The board's headline scramble animation is suppressed in the desktop take: the
  capture emulates `prefers-reduced-motion: reduce`, so no frame shows scrambled glyphs.
  On a real TV with motion enabled the animation still plays for under a second.
* Chromium's screencast drops a frame painted before the previous one is acknowledged,
  and then sends nothing until the page paints again. A very fast answer could be
  missing from the recording although the page shows it. The capture flips a 1x1 px
  marker three times after every press to force those paints.
