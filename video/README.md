# Demo video

**Status: rendered locally, not uploaded.** The last render is the 2026-10-01 take at
`9620743` (table below). The next take is planned and its narration is synthesized,
but it has not been recorded or composed yet. It opens on the Android TV emulator
footage from CI. Nothing has a public link until the owner uploads it, and nothing in
this directory is the video itself.

## The next take: emulator footage first

| Item | Value |
|---|---|
| Plan | `scripts/build_video_plan.py`, which writes `narration.json` and `cue_sheet.json`; `SHOT_LIST.md` lists the beats |
| Content | 162.382 s in 13 beats: 26.64 s of emulator footage in 4 beats, then 135.742 s of desktop take in 9 beats |
| Planned length | 169.382 s with the 4 s title card and the 3 s closing card; the gate allows under 175 s |
| Footage | `journey.mp4` from the artifact `mercury-android-tv-footage-f423ba57ecfe688b8dafe899e06ab29dfdb7a90c`, CI run [37475795991](https://github.com/upgradedev/mercury_amazon/actions/runs/37475795991) |
| Narration | Synthesized 2026-10-06 into the workspace folder `reviews/videos_20261006/mercury_amazon/narration/`, outside git |
| Voice | ElevenLabs premade voice `pNInz6obpgDQGcFmaJgB` (Adam), model `eleven_multilingual_v2` |
| Characters synthesized | 1120 sent to ElevenLabs in all calls (`synthesis-log.jsonl`): 928 in the 7 new or changed beats that ship, plus 192 for a longer closing beat that was replaced to keep the plan under 172 s. The 6 unchanged beats (1273 characters) reuse the `reviews/videos_muse_20261001` audio, copied to their new beat numbers with matching cache keys. 2201 characters are in the planned narration |

### What it shows

* **The title card** (4 s) says what the product is first: "Mercury. An incident board
  for the team's Fire TV. It names the deploy behind a spike only when it can." Two
  smaller lines name the two sources in the order they play: "Android TV emulator, API
  34, CI run 37475795991; local desktop run of `<sha7>`." Then "Offline fixtures,
  record-only rollback."
* **The emulator footage** opens the content: 26.64 s of `journey.mp4`, from 1.00 s to
  its end at 27.64 s, at 1x. It is the debug APK built at `f423ba5`, on an AOSP Android
  TV emulator (x86), Android 14 / API 34, loading the public demo, build `ea2cff5`,
  which is record-only. The journey:
  * the Leanback home screen, where the app is launched with its Leanback launcher
    intent;
  * black while it cold-starts and its WebView loads the demo;
  * the board answering on its own: checkout-api 12.9x, TEMPORAL CANDIDATE, Commit
    4f1c2ab, a deploy from the demo's invented, display-only feed;
  * Right and Center: Rollback staged, the lease counting down;
  * Right and Center: RECORDED, no pipeline contacted;
  * Center: the responder handoff published, SHARED REVISION 13, HTTP 200.

  The D-pad presses are key codes sent by the CI script. A label under the picture
  reads "Android TV emulator (API 34), debug APK, public demo build ea2cff5, CI run
  37475795991" for as long as the footage plays. Four beats of narration fit the
  footage exactly. Each beat is held for its window of the footage, and its words were
  placed on the frames (`SHOT_LIST.md` lists them).
* **The desktop take** follows. The narration says once that it is the same board, run
  locally in a desktop browser at 1080p, so each answer can be read. The local board
  names one of Mercury's own commits, stamped STAND-IN, where the public demo names the
  invented feed's deploy. The desktop journey presses the same keys as the 2026-10-01
  take. The stage, confirm and handoff presses share one beat, because the footage has
  just shown them at a viewer's pace.
* **The closing card** (3 s) repeats the CI run, the demo build and the commit. It says
  the emulator runtime receipt is a separate record.

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
`video/build-video.py` converts it to 25 fps by holding each frame until the next one,
then cuts it by frame number:

* nothing is sped up or slowed;
* no moment is held past its own recorded length, and nothing is cut out of the middle,
  so the 4.6 s cold start stays in;
* the first second of the idle home screen is trimmed, and the launch stays on it.

The cut points are `FOOTAGE_CUTS` in `scripts/build_video_plan.py`, each on a 25 fps
frame, read off the footage's frame times. `video/generate-narration.py` holds each
emulator beat for exactly its window. It refuses a beat whose audio plus 0.3 s does not
fit, rather than stretch the footage. `video/build-video.py` refuses footage whose
provenance (run, commits, OS, device, byte count) differs from the one the plan names.

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
MERCURY_OFFLINE=1 python -m uvicorn src.interfaces.mcp_server:app --port 8873 &
MERCURY_CAPTURE_URL=http://127.0.0.1:8873/ python video/capture-local.py
python video/build-video.py
cd "$MERCURY_VIDEO_ROOT/output" && VIDEO_MANIFEST=video_manifest.json \
  CAPTION_WINDOWS=caption_windows.json python <repo>/scripts/verify_video_sync.py mercury-demo.mp4
```

The narration is already in `narration/`. Rerunning `video/generate-narration.py`
reuses every beat whose words have not changed and calls ElevenLabs for none of them.
The capture skips the four emulator beats: its timeline starts at the first desktop
beat, and its receipt records that start as `narrationStartSeconds`.

## The last render: the 2026-10-01 take

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
to the last, and its closing beat said so. The next take replaces it. Next to the mp4 sit
`video-receipt.json`, `captions.en.srt`, `sync-gate.txt` and the gate's two inputs. The
per-beat audio, `timing.json` and the capture with its own receipt are in the sibling
`narration/` and `capture/` folders.

Its desktop journey is the one the next take keeps:

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
  at the current master, and the next take speaks the same two.
* The product makes no sound. The narration carries the story; Read aloud stays off.
* The picture is shown at 87.5% so the captions sit in a band under it and never cover
  the board. The page itself was captured at full 1920x1080.

Earlier takes, all superseded:

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
   It writes `timing.json` and the captions. Caption cues start at the measured pauses
   in the voice.
3. `python video/capture-local.py` refuses to record unless the server's `/health`
   reports the commit being recorded, waits until all five board rows have answered,
   then drives the desktop journey beat by beat. Every press checks which control took
   focus and every answer is awaited from the server; a journey that drifts aborts.
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
beat without changing its words, set `NARRATION_FORCE=beat_10_stage_to_evidence`.

Any new commit changes what the desktop board shows, because in offline mode the commit
it names is one of this repository's own. Restart the server after committing and record
at that commit; the title card and the Check line both name it.

## Known weaknesses

* The footage is an AOSP Android TV emulator in CI, not a Fire TV device. It loads the
  public demo (`ea2cff5`), not a local run of the recorded commit.
* The desktop take is a desktop browser, not the APK.
* The emulator's cold start is 4.6 s of black on screen, kept at 1x.
* The desktop journey was retimed into fewer beats without a browser probe, because none
  could be run while it was planned. The key sequence is the recorded one, but the merged
  stage, confirm and handoff beat presses faster than the 2026-10-01 take did.
* The named commit is one of this repository's own on the desktop, and a hand-written
  stand-in on the public demo. The metric is generated. The board labels all three.
* The board's headline scramble animation is suppressed in the desktop take: the
  capture emulates `prefers-reduced-motion: reduce`, so no frame shows scrambled glyphs.
  On a real TV with motion enabled the animation still plays for under a second.
* Chromium's screencast drops a frame painted before the previous one is acknowledged,
  and then sends nothing until the page paints again. A very fast answer could be
  missing from the recording although the page shows it. The capture flips a 1x1 px
  marker three times after every press to force those paints.
