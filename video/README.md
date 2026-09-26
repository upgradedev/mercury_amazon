# Demo video

**Status: rendered locally, not uploaded.** One take exists outside this repository.
It has no public link until the owner uploads it, and nothing in this directory is
the video itself.

| Item | Value |
|---|---|
| Recorded commit | `cf4ae181fa3cfda74791b8dfe64666641564f938`, reported by the server's own `/health` during the take |
| File | `mercury-demo.mp4`, on the owner's machine in the workspace folder `reviews/videos_20260926/mercury_amazon/output/`, outside git |
| Length | 170.44 s (ffprobe), 1920x1080, 25 fps, AAC 48 kHz, -16.4 LUFS integrated |
| SHA-256 | `b0c4728045b88266904d5604a25f36ec87f2a7100c6706934e206f4b3272022c` |
| Voice | ElevenLabs premade voice `pNInz6obpgDQGcFmaJgB` (Adam), model `eleven_multilingual_v2` |
| Characters synthesized | 2272 in the final narration; 2710 sent across all calls, because two beats were corrected and synthesized again |
| Sync gate | `scripts/verify_video_sync.py`: all checks passed |

Next to the mp4 sit `video-receipt.json` (commit, duration, SHA-256, voice, characters),
`captions.en.srt` (the sidecar for an upload), `sync-gate.txt` (the gate's output) and
the gate's two inputs. The per-beat audio, `timing.json` and the capture with its own
receipt are in the sibling `narration/` and `capture/` folders.

## What the video shows, and what it does not

* A 4 second title card: "Mercury. Recorded from a local run of commit cf4ae18. Public
  deployment pending." A 3 second closing card repeats the commit and says the public
  deployment and the Fire TV runtime receipt are pending.
* Between them, one continuous take of the page served by
  `MERCURY_OFFLINE=1 python -m uvicorn src.interfaces.mcp_server:app --port 8803`,
  recorded by desktop Chromium at 1920x1080. Every key is sent through
  `window.navigateDpad`, the bridge the Leanback `MainActivity` calls for the remote.
  No mouse, no edits, no speed changes; every screen is the page answering a real
  response from that server.
* The board's own labels stay in frame: OFFLINE FIXTURE on the metric, STAND-IN on the
  commit, record-only on the rollback, and SYNTHETIC on the spend figures.
* It is not a Fire TV or Android TV runtime proof. No device or emulator appears, and
  the narration says so. The candidate Android TV Emulator receipt is still pending.
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
A first take, from commit `924a58c`, was superseded and is kept beside the output as
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
* Panel answers render below their buttons, and the D-pad scrolls only as far as the
  focused control, so some answers come into view only when focus moves past them.
  The handoff's facts stay below the fold; only its next step is shown.
* The named commit is one of this repository's own, standing in for a deploy feed,
  and the metric is generated. The board labels both.
