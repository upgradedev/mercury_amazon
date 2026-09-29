# Demo video

**Status: rendered locally, not uploaded.** The current take is the audit-build take below. It has no public link until the owner uploads it, and nothing in this directory is the video itself.

| Item | Value |
|---|---|
| Recorded commit | `0aed20ab83ab5af6cb2af41b33b85fd5f1414f3c` (audit branch `muse/audit-mercury-20260928`), reported by the server's own `/health` during the take |
| File | `mercury-demo.mp4`, in the workspace folder `reviews/videos_muse_20260929/mercury_amazon/output/`, outside git |
| Length | 170.61 s (ffprobe), 1920x1080, 25 fps, AAC 48 kHz, -16.3 LUFS integrated |
| SHA-256 | `8f5f3c34db92a1a8b7fec8225839836e7d40a02fcb9ea397c779f301f7983ca2` |
| Voice | ElevenLabs premade voice `pNInz6obpgDQGcFmaJgB` (Adam), model `eleven_multilingual_v2` |
| Characters synthesized | 2249 in the final narration, 0 new: all 11 beats reused from the `reviews/videos_20260928` cache (cache keys match), generated with no ElevenLabs key in the environment, so no synthesis call was possible |
| Sync gate | `scripts/verify_video_sync.py`: all checks passed |

Next to the mp4 sit `video-receipt.json` (commit, duration, SHA-256, voice, characters),
`captions.en.srt` (the sidecar for an upload), `sync-gate.txt` (the gate's output) and
the gate's two inputs. The per-beat audio, `timing.json` and the capture with its own
receipt are in the sibling `narration/` and `capture/` folders.

## What the video shows, and what it does not

* A 4 second title card that says what the product is before where the take came
  from: "Mercury. An incident board for the team's Fire TV. It names the deploy behind
  a spike only when it can." One smaller line under it reads: local run of commit
  0aed20a in desktop Chromium, offline fixtures, record-only rollback, public
  deployment pending. A 3 second closing card repeats the commit and says the public
  deployment and the Fire TV runtime receipt are pending.
* Between them, one continuous take of the page served by
  `MERCURY_OFFLINE=1 python -m uvicorn src.interfaces.mcp_server:app --port 8873`,
  recorded by desktop Chromium at 1920x1080. Every key is sent through
  `window.navigateDpad`, the bridge the Leanback `MainActivity` calls for the remote.
  No mouse, no edits, no speed changes; every screen is the page answering a real
  response from that server. The capture adds one 1x1 px marker in the bottom-right
  corner and flips its colour after each press, only so the recorder is sent the frame
  the page is showing (see Known weaknesses).
* The board's own labels stay in frame: OFFLINE FIXTURE on the metric, STAND-IN on the
  commit, record-only on the rollback, and SYNTHETIC on the spend figures.
* It is not a Fire TV or Android TV runtime proof. No device or emulator appears, and
  the narration says so. The candidate Android TV Emulator receipt is still pending.
* After Confirm the board stays where it is: the large figure reads RECORDED, no
  pipeline contacted, under Rollback recorded, not sent, and the key legend reads Next
  press: Publish responder handoff (from 99.4 s to 112.8 s). The capture refuses
  to continue unless the page is still at the top at that moment. Center then
  publishes the handoff and the page shows the rollback steps, where 02 Confirm says
  the token has been spent; Down lands on the evidence sentence, 50.0% over 58
  namings in 1160 synthetic labelled cases (from 119.3 s).
* The runtime filter is named in the opening beat and on the board: the checkout-api
  verdict reads Only runtime change, and release-train reads 5 runtime changes landed.
* The held-out figures are the ones the board and the README print: 90.0% refusals
  (beat 2), 50.0% precision over 58 namings if a fault shows within 75 minutes
  (beat 4, and on the board as 50.0% held-out precision, synthetic, at most 75
  minutes of lag).
* This take matches the current build: Down from the open Delivery velocity panel,
  and later from Cloud spend, scrolls the rest of the answer into view while the
  remote stays inside the panel, and the journey shows Back, Down, Down to Check.
  After Confirm the parked board draws the amber ring (the audit fix), so a ring is
  visible while the RECORDED payoff stays on screen.
* The product makes no sound. The narration carries the story; Read aloud stays off.
* The picture is shown at 87.5% so the captions sit in a band under it and never
  cover the board. The page itself was captured at full 1920x1080.

## How it was produced

The pipeline is the submission kit's, adapted to this repository. Each beat is
synthesized alone and measured, and the picture is held to that measured length, so
the voice cannot drift from the picture.

1. `python scripts/build_video_plan.py` writes `video/narration.json` and
   `video/cue_sheet.json` from one beat list. Each beat has the spoken text, the
   caption text and the action on screen.
2. `python video/generate-narration.py` synthesizes each beat with ElevenLabs, measures
   it with ffprobe, holds it for its length plus 0.65 s, and writes `timing.json` and
   the captions. Caption cues start at the measured pauses in the voice.
3. `python video/capture-local.py` refuses to record unless the server's `/health`
   reports the commit being recorded, waits until all five board rows have answered,
   then drives the journey beat by beat. Every press checks which control took focus
   and every answer is awaited from the server; a journey that drifts aborts.
4. `python video/build-video.py` trims the capture to the narration, adds the two
   cards, burns the captions, mixes the beats at their measured starts, normalises to
   -16 LUFS and checks the result is within one frame of the planned length.
5. `python scripts/verify_video_sync.py mercury-demo.mp4`, run in the output folder,
   measures the finished file: audio against video length, caption windows, and the
   card, content, content, card order read from the pixels. The screencast and web
   segments it checks are two windows of the same continuous take; web is the last
   beat. `python tests/video/verify_gate_selftest.py` proves the gate still fails on
   a mis-ordered, caption-bleeding or out-of-sync file.

The environment for steps 2 to 5: `MERCURY_VIDEO_ROOT` (the output folder),
`MERCURY_RELEASE_SHA` (the recorded commit), `FFMPEG`, `FFPROBE`, and for step 2
`ELEVENLABS_API_KEY`, which is read from the environment and never printed or stored.
The capture reads `MERCURY_CAPTURE_URL` (default port 8803; this take used
`http://127.0.0.1:8873/`).
The take before this one, from commit `df5db06`, is kept in `reviews/videos_20260928/`
and is superseded: it predates the audit build (no parked ring after Confirm) and
was captured without reduced-motion emulation, so headline frames in the scramble
window show scrambled glyphs. The take before that, from commit `ad12202`, is kept in `reviews/videos_20260927/`
and is superseded: it showed the page scrolling to the rollback steps after Confirm,
and How it answers as prose under the board. A first take at `bcadcdc` on 2026-09-28
is kept beside this output as `superseded_bcadcdc/`: its last beat held "Sending GET
.../health" throughout, although the page showed the build line, because the recorder
missed the frame (fixed by the repaint marker). An earlier take, from commit `cf4ae18`, is kept in `reviews/videos_20260926/` and is
superseded: it spoke the in-sample 81.1% and 52.2% over 113 namings and showed a
60 minute window, which the board and the README no longer print. This take speaks the
held-out 90.0% refusals and 50.0% over 58 namings that the board prints after the
runtime filter. A first take, from commit `924a58c`, was superseded and is kept beside the output as
`superseded_924a58c/`. Reviewing it found two faults, both fixed before this take: the
captions were burned 4 s late, because the subtitles filter runs before the title
card is joined, and one beat gave the wrong reason for the spend fixture (the run is
in offline mode; the machine does have AWS credentials).

## Re-rendering one beat

Edit the beat in `scripts/build_video_plan.py` and rerun it. `generate-narration.py`
then re-synthesizes only the beat whose words changed and reuses the rest, so every
other beat keeps its measured length. Record again and compose again. To re-roll a
beat without changing its words, set `NARRATION_FORCE=beat_07_confirm`.

Any new commit changes what the board shows, because in offline mode the commit it
names is one of this repository's own. Restart the server after committing and
record at that commit; the title card and the Check line both name it.

## Known weaknesses of this take

* It is a desktop browser, not the APK on an allowed Fire TV target.
* The D-pad scrolls only as far as the focused control. Center on Publish handoff
  brings the rollback steps into view, and Down then passes the handoff's own answer on
  the way to the evidence, so the handoff's facts and next step never appear on screen.
  The current build differs here too: the cursor stays on Publish handoff and the page
  scrolls until the handoff's answer clears the key bar.
  The Delivery velocity and Cloud spend answers come into view when Center opens them.
* The named commit is one of this repository's own, standing in for a deploy feed,
  and the metric is generated. The board labels both.
* The board's headline scramble animation is suppressed in this take: the capture
  emulates `prefers-reduced-motion: reduce`, so no frame shows scrambled glyphs.
  (On a real TV with motion enabled the animation still plays for under a second.)
* Chromium's screencast drops a frame painted before the previous one is
  acknowledged and then sends nothing until the page paints again, so a very fast
  answer could be missing from the recording although the page shows it. The capture
  flips a 1x1 px marker three times after every press to force those paints. Every
  beat boundary, every press and every caption cue of this take was extracted and
  looked at; each shows the answer the narration describes.
