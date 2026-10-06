#!/usr/bin/env python3
"""Synthesize each narration beat, measure it, and write timing and captions.

Adapted from the submission kit's video/generate-narration.py. The timing model is
the kit's and is unchanged: every beat is synthesized on its own, its real length
is measured with ffprobe, and the beat is held for that length plus a fixed 0.65 s
tail. Nothing downstream invents a timestamp. What changed for this repository:

  1. It reads this repository's narration format, ``mercury.video_narration/1``,
     written by ``scripts/build_video_plan.py``: ``beats`` with ``beat_id``,
     ``narration_text`` (spoken) and ``caption_text`` (burned on screen), and the
     voice under ``tts``.
  2. Environment names are ``MERCURY_VIDEO_ROOT`` for the media folder, which lives
     outside the repository.
  3. Every text to speech call is appended to ``narration/synthesis-log.jsonl`` with
     the beat and the number of characters sent, so the billed total is counted,
     including re-rolls.
  4. Caption lines are wrapped at 84 characters, because the composition puts them
     in a band under the picture instead of over it, and a sentence longer than two
     lines is split after a colon or semicolon.
  5. Cue boundaries start from the kit's character share of the measured length and
     then move to the measured pause in the voice within 1.2 s, found with ffmpeg's
     silencedetect. ``timing.json`` records each cue's start as
     ``sentenceStartsSeconds``, which the capture uses to time key presses.
  6. A beat may carry ``fixed_hold_seconds``. The emulator beats do: they play over
     a window of footage filmed in CI, so the footage, not the voice, sets how long
     they last. Such a beat is held for exactly that window, and the generator
     refuses it when its measured audio plus ``FIXED_HOLD_MARGIN_SECONDS`` does not
     fit, rather than stretch or cut the footage. Every other beat keeps the kit's
     measured hold. Each scene in ``timing.json`` also carries the beat's
     ``source``, so the capture and the compose know which beats are footage, and
     an emulator beat's footage window and its holds of a static frame.
  7. Every beat is synthesized with ElevenLabs' ``with-timestamps`` endpoint, the
     same voice and settings, so its character alignment is kept beside the audio
     (``NN-beat.alignment.json``). A beat may name ``marks``, spoken phrases; their
     start times go to ``timing.json`` as ``marksSeconds``. A beat's
     ``caption_cues`` are its caption pieces in order; a cue that names a mark
     starts on that word, so a caption naming a value or a state appears with the
     frame that shows it, and the capture presses a key on a mark. Cues without a
     mark keep the pause-based boundaries of point 5.

Kept from the kit: per-beat caching keyed on the speech text and voice settings, so
changing one beat costs one call; the 3 to 40 s per beat and 90 to 174 s total
limits; the refusal of an unfilled ``<PLACEHOLDER>``.

Run from the repository root:

    MERCURY_VIDEO_ROOT=/path/outside/git FFPROBE=ffprobe ELEVENLABS_API_KEY=... \\
        python video/generate-narration.py

``NARRATION_FORCE=beat_10_stage_to_evidence`` re-rolls one beat; ``NARRATION_FORCE=all`` all.
The key is read from the environment and never printed or written anywhere.
"""

from __future__ import annotations

import base64
import datetime
import hashlib
import json
import os
import pathlib
import re
import subprocess
import time
import urllib.request

SPEC = pathlib.Path(__file__).with_name("narration.json")
TAIL_SECONDS = 0.65
#: The least silence a fixed-hold beat keeps after its last word.
FIXED_HOLD_MARGIN_SECONDS = 0.3
SOURCES = ("android_tv_emulator", "desktop_capture")
CAPTION_WIDTH = 84

# Whichever is set is used. The value is never printed and never written to a receipt.
ELEVENLABS_KEY_ENV_NAMES = ("ELEVENLABS_API_KEY", "XI_API_KEY", "ELEVEN_LABS_KEY")


def run(args: list[str]) -> str:
    result = subprocess.run(args, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def duration(path: pathlib.Path) -> float:
    return float(
        run(
            [
                os.environ.get("FFPROBE", "ffprobe"),
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ]
        )
    )


def timestamp(value: float) -> str:
    millis = round(max(0.0, value) * 1000)
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    seconds, millis = divmod(millis, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def wrapped(text: str, width: int = CAPTION_WIDTH) -> str:
    words = text.split()
    lines: list[str] = []
    line = ""
    for word in words:
        candidate = f"{line} {word}".strip()
        if line and len(candidate) > width:
            lines.append(line)
            line = word
        else:
            line = candidate
    if line:
        lines.append(line)
    if len(lines) <= 2:
        return "\n".join(lines)
    midpoint = max(1, len(words) // 2)
    return " ".join(words[:midpoint]) + "\n" + " ".join(words[midpoint:])


def sentences(caption: str) -> list[str]:
    """Caption cues: one per sentence, and a sentence too long for two caption lines
    is split once more after a colon or semicolon, so no cue needs a third line."""
    cues: list[str] = []
    for part in (p.strip() for p in re.split(r"(?<=[.!?])\s+", caption)):
        if not part:
            continue
        if len(part) > 2 * CAPTION_WIDTH:
            pieces = [piece.strip() for piece in re.split(r"(?<=[:;])\s+", part) if piece.strip()]
            cues.extend(pieces)
        else:
            cues.append(part)
    return cues


def pauses(path: pathlib.Path) -> list[tuple[float, float]]:
    """Measured pauses in one beat's audio: (start, end) of every stretch quieter than
    -45 dB for at least 0.3 s. Used to put caption cue boundaries where the voice
    actually pauses, instead of where a share of the characters says it should."""
    result = subprocess.run(
        [os.environ.get("FFMPEG", "ffmpeg"), "-hide_banner", "-nostats", "-i", str(path),
         "-af", "silencedetect=noise=-45dB:d=0.3", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    starts = [float(v) for v in re.findall(r"silence_start:\s*([0-9.]+)", result.stderr)]
    ends = [float(v) for v in re.findall(r"silence_end:\s*([0-9.]+)", result.stderr)]
    return list(zip(starts, ends))


def cue_bounds(parts: list[str], seconds: float, quiet: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Each cue's (start, end) inside the beat. The first estimate is the kit's: a
    share of the measured length by characters. A boundary is then moved to the
    measured pause within 1.2 s of it, if there is one."""
    weight = sum(len(part) for part in parts) or 1
    edges = [0.0]
    for part in parts:
        edges.append(edges[-1] + seconds * len(part) / weight)
    bounds = [(edges[i], edges[i + 1]) for i in range(len(parts))]
    for i in range(1, len(parts)):
        estimate = edges[i]
        near = [(abs((a + b) / 2 - estimate), a, b) for a, b in quiet if a < estimate + 1.2 and b > estimate - 1.2 and b < seconds - 0.05]
        if near:
            _, pause_start, pause_end = min(near)
            if bounds[i - 1][0] < pause_start and pause_end < bounds[i][1]:
                bounds[i - 1] = (bounds[i - 1][0], pause_start)
                bounds[i] = (pause_end, bounds[i][1])
    return bounds


def elevenlabs_key() -> str:
    for name in ELEVENLABS_KEY_ENV_NAMES:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    raise SystemExit("no ElevenLabs key: set one of " + ", ".join(ELEVENLABS_KEY_ENV_NAMES))


def synthesize_elevenlabs(text: str, config: dict[str, object], retries: int = 3) -> tuple[bytes, dict]:
    """The request body and retry loop are the kit's. The endpoint is the kit's with
    ``/with-timestamps``, which returns the same audio and its character alignment."""
    voice_id = str(config.get("voiceId", ""))
    model_id = str(config.get("modelId", "eleven_multilingual_v2"))
    output_format = str(config.get("outputFormat", "mp3_44100_128"))
    if not re.fullmatch(r"[A-Za-z0-9]{16,40}", voice_id):
        raise SystemExit("tts.elevenLabs.voiceId is missing or malformed")
    if not re.fullmatch(r"[a-z0-9_]{4,40}", model_id):
        raise SystemExit("tts.elevenLabs.modelId is malformed")
    if not re.fullmatch(r"[a-z0-9_]{4,32}", output_format):
        raise SystemExit("tts.elevenLabs.outputFormat is malformed")
    key = elevenlabs_key()
    url = (
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/with-timestamps"
        f"?output_format={output_format}"
    )
    body = json.dumps(
        {
            "text": text,
            "model_id": model_id,
            "voice_settings": {
                "stability": 0.45,
                "similarity_boost": 0.8,
                "use_speaker_boost": True,
            },
        }
    ).encode("utf-8")
    last: Exception | None = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(
                url,
                data=body,
                headers={
                    "xi-api-key": key,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )
            with urllib.request.urlopen(request, timeout=90) as response:
                payload = json.load(response)
            data = base64.b64decode(payload["audio_base64"])
            if len(data) < 3000:
                raise RuntimeError(f"tiny audio ({len(data)} bytes)")
            alignment = payload["alignment"]
            return data, {
                "characters": alignment["characters"],
                "starts": alignment["character_start_times_seconds"],
                "ends": alignment["character_end_times_seconds"],
            }
        except Exception as error:  # noqa: BLE001
            # Only the exception type and HTTP status reach the log, never headers.
            last = error
            time.sleep(2 * (attempt + 1))
    raise SystemExit(f"ElevenLabs failed after {retries} tries: {type(last).__name__}: {getattr(last, 'code', '')}")


def voice_signature(tts: dict[str, object]) -> str:
    """Everything except the text that changes how a beat sounds. Part of the cache
    key, so changing the voice re-synthesizes every beat rather than mixing voices."""
    config = dict(tts.get("elevenLabs") or {})
    config.pop("voiceName", None)  # a label for readers, not a synthesis setting
    return json.dumps({"elevenLabs": config}, sort_keys=True, separators=(",", ":"))


def cache_key(speech: str, tts: dict[str, object]) -> str:
    payload = json.dumps(
        {"provider": "elevenlabs", "speech": speech, "voice": voice_signature(tts)},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def cached_key(sidecar: pathlib.Path) -> str | None:
    try:
        recorded = json.loads(sidecar.read_text(encoding="utf-8")).get("cacheKey")
    except (OSError, ValueError):
        return None
    return recorded if isinstance(recorded, str) else None


def mark_times(identifier: str, speech: str, marks: dict[str, str], alignment: dict | None) -> dict[str, float]:
    """The start of each marked phrase, read off the character alignment."""
    if not marks:
        return {}
    if not alignment or "".join(alignment.get("characters", [])) != speech:
        raise SystemExit(f"beat {identifier} names marks but has no alignment for its words")
    times = {}
    for name, phrase in marks.items():
        if speech.count(phrase) != 1:
            raise SystemExit(f"beat {identifier}: mark {name} is not spoken exactly once")
        times[name] = round(float(alignment["starts"][speech.index(phrase)]), 3)
    return times


def caption_bounds(identifier: str, cues: list[list[object]], seconds: float,
                   quiet: list[tuple[float, float]], marks: dict[str, float]) -> list[tuple[float, float]]:
    """Each caption cue's (start, end) inside the beat. With marks, a cue starts on its
    mark and ends where the next starts; without, the pause-based bounds of point 5."""
    pieces = [str(cue[0]) for cue in cues]
    named = [cue[1] for cue in cues]
    if not any(named):
        return cue_bounds(pieces, seconds, quiet)
    if named[0] is not None or any(mark is None for mark in named[1:]):
        raise SystemExit(f"beat {identifier}: with marks, every cue but the first starts on a mark")
    starts = [0.0] + [marks[str(mark)] for mark in named[1:]]
    if starts != sorted(starts) or len(set(starts)) != len(starts):
        raise SystemExit(f"beat {identifier}: its marked cues are not in spoken order")
    return [(starts[i], starts[i + 1] if i + 1 < len(starts) else seconds) for i in range(len(starts))]


def beat_hold(identifier: str, seconds: float, fixed: object) -> float:
    """How long a beat is held: its measured audio plus the kit's tail, or, for a
    beat that plays over footage, exactly its footage window if the audio fits."""
    if fixed is None:
        return seconds + TAIL_SECONDS
    if not isinstance(fixed, (int, float)) or isinstance(fixed, bool) or fixed <= 0:
        raise SystemExit(f"beat {identifier} has an invalid fixed_hold_seconds")
    if seconds + FIXED_HOLD_MARGIN_SECONDS > float(fixed):
        raise SystemExit(
            f"beat {identifier} speaks for {seconds:.3f}s but its footage window is "
            f"{float(fixed):.3f}s; shorten the words, do not stretch the footage"
        )
    return float(fixed)


def main() -> None:
    root = pathlib.Path(os.environ["MERCURY_VIDEO_ROOT"])
    out = root / "narration"
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    beats = spec.get("beats")
    tts = spec.get("tts")
    if spec.get("schema") != "mercury.video_narration/1" or not isinstance(beats, list):
        raise SystemExit("narration contract is invalid")
    if not isinstance(tts, dict) or tts.get("provider") != "elevenlabs":
        raise SystemExit("narration.json must name tts.provider elevenlabs")
    forced = {
        item.strip()
        for item in os.environ.get("NARRATION_FORCE", "").split(",")
        if item.strip()
    }
    out.mkdir(parents=True, exist_ok=True)
    log = out / "synthesis-log.jsonl"
    timing: list[dict[str, object]] = []
    cues: list[tuple[float, float, str]] = []
    offset = 0.0
    for index, beat in enumerate(beats, start=1):
        identifier = beat.get("beat_id")
        speech = beat.get("narration_text")
        caption = beat.get("caption_text") or speech
        if not isinstance(identifier, str) or not re.fullmatch(r"[a-z][a-z0-9_]{1,40}", identifier):
            raise SystemExit("beat identifier is invalid")
        source = beat.get("source", "desktop_capture")
        if source not in SOURCES:
            raise SystemExit(f"beat {identifier} names an unknown source: {source!r}")
        if not all(isinstance(value, str) and 20 <= len(value) <= 800 for value in (speech, caption)):
            raise SystemExit(f"beat text is invalid: {identifier}")
        if "<" in f"{speech}{caption}" or ">" in f"{speech}{caption}":
            raise SystemExit(f"beat {identifier} still contains a <PLACEHOLDER>; fill it in first")
        audio = out / f"{index:02d}-{identifier}.mp3"
        sidecar = out / f"{index:02d}-{identifier}.cache.json"
        aligned = out / f"{index:02d}-{identifier}.alignment.json"
        marks = beat.get("marks") or {}
        key = cache_key(speech, tts)
        reuse = (
            identifier not in forced
            and "all" not in forced
            and audio.is_file()
            and cached_key(sidecar) == key
            and (not marks or cached_key(aligned) == key)
        )
        if reuse:
            print(f"reused {audio.name}")
        else:
            data, alignment = synthesize_elevenlabs(speech, tts["elevenLabs"])
            audio.write_bytes(data)
            aligned.write_text(json.dumps({"cacheKey": key, **alignment}) + "\n", encoding="utf-8")
            sidecar.write_text(
                json.dumps({"cacheKey": key, "provider": "elevenlabs"}, indent=2) + "\n",
                encoding="utf-8",
            )
            with log.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({
                    "beat": identifier,
                    "characters": len(speech),
                    "voiceId": tts["elevenLabs"].get("voiceId"),
                    "at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                }) + "\n")
            print(f"synthesized {audio.name} ({len(speech)} characters)")
        seconds = duration(audio)
        if seconds < 3 or seconds > 40:
            raise SystemExit(f"beat audio duration is unsafe: {identifier} {seconds:.3f}s")
        hold = beat_hold(identifier, seconds, beat.get("fixed_hold_seconds"))
        alignment = json.loads(aligned.read_text(encoding="utf-8")) if aligned.is_file() else None
        if alignment is not None and alignment.get("cacheKey") != key:
            alignment = None
        marked = mark_times(identifier, speech, marks, alignment)
        caption_cues = beat.get("caption_cues") or [[part, None] for part in sentences(caption)]
        if " ".join(str(cue[0]) for cue in caption_cues) != caption:
            raise SystemExit(f"beat {identifier}: its caption cues do not join to its caption text")
        sentence_starts = []
        bounds = caption_bounds(identifier, caption_cues, seconds, pauses(audio), marked)
        for cue, (begin, finish) in zip(caption_cues, bounds):
            cues.append((offset + begin, offset + finish, wrapped(str(cue[0]))))
            sentence_starts.append(round(begin, 3))
        timing.append(
            {
                "id": identifier,
                "source": source,
                "audio": audio.name,
                "durationSeconds": round(seconds, 3),
                "holdSeconds": round(hold, 3),
                "startSeconds": round(offset, 3),
                "speechCharacters": len(speech),
                "sentenceStartsSeconds": sentence_starts,
                "marksSeconds": marked,
            }
        )
        window = beat.get("footage_window_seconds")
        if window is not None:
            # Where in the footage this beat plays, and which static frames it holds;
            # the compose cuts the clip from them.
            timing[-1]["footageWindowSeconds"] = [float(window[0]), float(window[1])]
            timing[-1]["footageHoldsSeconds"] = [
                [float(at), float(held)] for at, held in beat.get("footage_holds_seconds") or []
            ]
        offset += hold
    if not 90 <= offset < 175:
        raise SystemExit(f"narration must be 90-174 seconds, observed {offset:.3f}")
    billed = 0
    if log.is_file():
        for line in log.read_text(encoding="utf-8").splitlines():
            if line.strip():
                billed += int(json.loads(line)["characters"])
    (out / "timing.json").write_text(
        json.dumps(
            {
                "schemaVersion": "mercury.video-timing/1",
                "totalSeconds": round(offset, 3),
                "tailSeconds": TAIL_SECONDS,
                "voiceId": tts["elevenLabs"].get("voiceId"),
                "modelId": tts["elevenLabs"].get("modelId"),
                "charactersInNarration": sum(int(item["speechCharacters"]) for item in timing),
                "charactersSentAllCalls": billed,
                "scenes": timing,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    srt: list[str] = []
    for number, (start, end, text) in enumerate(cues, start=1):
        srt.extend([str(number), f"{timestamp(start)} --> {timestamp(end)}", text, ""])
    (out / "captions.en.srt").write_text("\n".join(srt), encoding="utf-8")
    print(f"Generated {len(timing)} scenes across {offset:.3f} seconds")


if __name__ == "__main__":
    main()
