#!/usr/bin/env python3
"""Compose the capture, the measured narration and the captions into the demo mp4.

Adapted from the submission kit's video/build-video.py. Kept from the kit: one
continuous capture trimmed to exactly the measured narration, each beat's audio
delayed to its measured start, burned captions derived from that same timing,
loudnorm at -16 LUFS, 1920x1080 at 25 fps, and a hard failure when the composed
length differs from the planned length by more than one frame.

What changed for this repository, so the kit's pixel-reading sync gate
(``scripts/verify_video_sync.py``) runs on the result unchanged:

  1. A silent title card opens the video and a silent closing card ends it, both
     rendered here with Pillow. The title card says what Mercury does first, then in
     one smaller line the commit that was recorded, that the metrics are offline
     fixtures and the rollback record-only, and that the public cockpit is live with
an emulator receipt landed.
  2. The capture is scaled to 87.5% and placed at the top of the frame, and the
     captions sit in the band underneath it, so no caption ever covers what the
     board shows. The page itself was captured at 1920x1080.
  3. It writes ``video_manifest.json`` and ``caption_windows.json`` for the gate.
     The gate's four segments are the title card, the capture up to the last beat
     (``screencast``), the last beat (``web``) and the closing card. The last two
     content segments are windows of one continuous capture.
  4. The receipt records the voice, the characters synthesized, the card lengths
     and the capture's own receipt.

Environment: ``MERCURY_VIDEO_ROOT`` (media folder outside the repository),
``MERCURY_RELEASE_SHA`` (the 40 character commit the local server reported while
it was recorded), ``FFMPEG`` and ``FFPROBE``.
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import subprocess

from PIL import Image, ImageDraw, ImageFont

ROOT = pathlib.Path(os.environ["MERCURY_VIDEO_ROOT"])
RELEASE_SHA = os.environ["MERCURY_RELEASE_SHA"]
NARRATION = ROOT / "narration"
CAPTURE = ROOT / "capture" / "production.webm"
OUTPUT = ROOT / "output"
CARDS = ROOT / "cards"
FPS = 25
FRAME_SECONDS = 1 / FPS
TITLE_SECONDS = 4.0
OUTRO_SECONDS = 3.0
# The capture is shown at 1680x945, top-centred; captions live in the band below.
PIC_W, PIC_H, PIC_X, PIC_Y = 1680, 945, 120, 8
BACKGROUND = (14, 15, 17)
AMBER = (255, 178, 63)
INK = (238, 231, 216)
INK_2 = (171, 165, 151)
FONT_DIR = pathlib.Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
FINAL_NAME = "mercury-demo.mp4"


def run(args: list[str]) -> str:
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(result.stderr[-3000:] or "media command failed")
    return result.stdout.strip()


def probe(path: pathlib.Path) -> dict[str, object]:
    return json.loads(
        run([os.environ["FFPROBE"], "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)])
    )


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_DIR / name), size)


def card(path: pathlib.Path, lines: list[tuple[str, str, int, tuple[int, int, int]]]) -> None:
    """A solid card with left-aligned lines: (text, font file, size, colour)."""
    image = Image.new("RGB", (1920, 1080), BACKGROUND)
    draw = ImageDraw.Draw(image)
    heights = [size * 1.45 for _, _, size, _ in lines]
    y = (1080 - sum(heights)) / 2
    draw.rectangle([160, y - 40, 168, y + sum(heights) - 20], fill=AMBER)
    for (text, face, size, colour), height in zip(lines, heights):
        draw.text((210, y), text, font=font(face, size), fill=colour)
        y += height
    image.save(path)


def srt_windows(text: str) -> list[tuple[float, float, str]]:
    def seconds(stamp: str) -> float:
        hours, minutes, rest = stamp.split(":")
        whole, millis = rest.split(",")
        return int(hours) * 3600 + int(minutes) * 60 + int(whole) + int(millis) / 1000

    windows = []
    for block in text.strip().split("\n\n"):
        rows = block.splitlines()
        start, end = (part.strip() for part in rows[1].split("-->"))
        windows.append((seconds(start), seconds(end), "\n".join(rows[2:])))
    return windows


def stamp(value: float) -> str:
    millis = round(max(0.0, value) * 1000)
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    whole, millis = divmod(millis, 1_000)
    return f"{hours:02d}:{minutes:02d}:{whole:02d},{millis:03d}"


def main() -> None:
    timing = json.loads((NARRATION / "timing.json").read_text(encoding="utf-8"))
    capture_receipt = json.loads((ROOT / "capture" / "capture-receipt.json").read_text(encoding="utf-8"))
    if capture_receipt.get("releaseSha") != RELEASE_SHA:
        raise SystemExit("the capture was recorded at a different commit than MERCURY_RELEASE_SHA")
    scenes = timing["scenes"]
    narration_total = float(timing["totalSeconds"])
    total = TITLE_SECONDS + narration_total + OUTRO_SECONDS
    trim_lead = float(capture_receipt["trimLeadSeconds"])
    if not 0 <= trim_lead <= 30:
        raise SystemExit("capture trim lead is outside the bounded contract")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    CARDS.mkdir(parents=True, exist_ok=True)

    short = RELEASE_SHA[:7]
    title_png = CARDS / "title.png"
    outro_png = CARDS / "outro.png"
    # The product first: a judge reads what Mercury does before where the take came
    # from. The provenance stays on the card, in one smaller line, and again on the
    # closing card.
    card(title_png, [
        ("Mercury", "bahnschrift.ttf", 120, AMBER),
        ("An incident board for the team's Fire TV.", "segoeui.ttf", 58, INK),
        ("It names the deploy behind a spike only when it can.", "segoeui.ttf", 58, INK),
        ("", "segoeui.ttf", 30, INK_2),
        (f"Local run of commit {short} in desktop Chromium: offline fixtures, record-only rollback.",
         "segoeui.ttf", 34, INK_2),
        ("Public cockpit live; emulator receipt landed.", "segoeui.ttf", 34, INK_2),
    ])
    card(outro_png, [
        ("Mercury", "bahnschrift.ttf", 110, AMBER),
        ("One deploy, or why not.", "segoeui.ttf", 54, INK),
        (f"Recorded from a local run of commit {short}, with offline fixtures.", "segoeui.ttf", 40, INK_2),
        ("Public cockpit live; emulator receipt landed.", "segoeui.ttf", 40, INK_2),
    ])

    # In the finished file every caption starts after the title card: shift each window.
    source = srt_windows((NARRATION / "captions.en.srt").read_text(encoding="utf-8"))
    shifted = [(start + TITLE_SECONDS, end + TITLE_SECONDS, text) for start, end, text in source]
    captions_out = OUTPUT / "captions.en.srt"
    blocks = []
    for number, (start, end, text) in enumerate(shifted, start=1):
        blocks.extend([str(number), f"{stamp(start)} --> {stamp(end)}", text, ""])
    captions_out.write_text("\n".join(blocks), encoding="utf-8")

    args = [
        os.environ["FFMPEG"], "-y",
        "-i", str(CAPTURE),
        "-loop", "1", "-framerate", str(FPS), "-t", str(TITLE_SECONDS), "-i", str(title_png),
        "-loop", "1", "-framerate", str(FPS), "-t", str(OUTRO_SECONDS), "-i", str(outro_png),
    ]
    filters: list[str] = []
    labels: list[str] = []
    first_audio_input = 3
    for index, scene in enumerate(scenes):
        args.extend(["-i", str(NARRATION / str(scene["audio"]))])
        delay = round((TITLE_SECONDS + float(scene["startSeconds"])) * 1000)
        hold = float(scene["holdSeconds"])
        label = f"a{index}"
        filters.append(
            f"[{first_audio_input + index}:a]aresample=48000,apad=pad_dur={hold},atrim=0:{hold},"
            f"adelay={delay}:all=1[{label}]"
        )
        labels.append(f"[{label}]")
    # The subtitles filter runs on the capture chain before the title card is
    # concatenated in front of it, so it reads the capture's own clock: burn the
    # unshifted captions there. The shifted copy is the sidecar for the finished file.
    subtitle_path = str(NARRATION / "captions.en.srt").replace("\\", "/").replace(":", "\\:")
    style = (
        "FontName=Arial,FontSize=11,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
        "BorderStyle=1,Outline=0,Shadow=0,MarginV=6,Alignment=2"
    )
    bg = "0x0E0F11"
    filters.append(
        f"[0:v]trim=start={trim_lead}:end={trim_lead + narration_total},setpts=PTS-STARTPTS,"
        f"fps={FPS},scale={PIC_W}:{PIC_H}:flags=lanczos,"
        f"pad=1920:1080:{PIC_X}:{PIC_Y}:color={bg},"
        f"subtitles='{subtitle_path}':force_style='{style}',format=yuv420p,setsar=1[body]"
    )
    filters.append(f"[1:v]fps={FPS},format=yuv420p,setsar=1[title]")
    filters.append(f"[2:v]fps={FPS},format=yuv420p,setsar=1[outro]")
    filters.append("[title][body][outro]concat=n=3:v=1:a=0[v]")
    filters.append(
        f"{''.join(labels)}amix=inputs={len(labels)}:duration=longest:normalize=0,"
        f"loudnorm=I=-16:LRA=7:TP=-1.5,apad=whole_dur={total},atrim=0:{total}[a]"
    )
    final = OUTPUT / FINAL_NAME
    args.extend([
        "-filter_complex", ";".join(filters),
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-movflags", "+faststart",
        "-t", f"{total:.3f}",
        str(final),
    ])
    run(args)

    media = probe(final)
    duration = float(media["format"]["duration"])
    streams = media["streams"]
    videos = [item for item in streams if item.get("codec_type") == "video"]
    audios = [item for item in streams if item.get("codec_type") == "audio"]
    if not 90 <= duration < 175 or len(videos) != 1 or len(audios) != 1:
        raise SystemExit(f"final media contract failed: {duration:.3f}s, {len(videos)} video, {len(audios)} audio")
    if videos[0].get("width") != 1920 or videos[0].get("height") != 1080:
        raise SystemExit("final video dimensions are not 1920x1080")
    if abs(duration - total) > FRAME_SECONDS:
        raise SystemExit(
            f"composed {duration:.3f}s but the cards plus the narration measure {total:.3f}s. "
            "The capture is probably shorter than the trim lead plus the narration. Record a "
            "longer capture. Do not widen this tolerance."
        )

    # Inputs for the kit's sync gate, derived from the same measured timing.
    last = scenes[-1]
    before_last = scenes[-2]
    screencast = float(last["startSeconds"])
    manifest = {
        "fps": FPS,
        "title_dur": TITLE_SECONDS,
        "screencast_dur": round(screencast, 3),
        "web_dur": round(float(last["holdSeconds"]), 3),
        "outro_dur": OUTRO_SECONDS,
        "segments": ["title", "screencast", "web", "outro"],
        # The end of the last spoken audio inside the screencast window.
        "a_main": round(float(before_last["startSeconds"]) + float(before_last["durationSeconds"]), 3),
        "vo_delay": TITLE_SECONDS,
        "have_vo": True,
        "note": "screencast and web are two windows of one continuous capture; web is the last beat",
    }
    (OUTPUT / "video_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (OUTPUT / "caption_windows.json").write_text(
        json.dumps([[round(s, 3), round(e, 3), t] for s, e, t in shifted], indent=2) + "\n",
        encoding="utf-8",
    )

    digest = hashlib.sha256(final.read_bytes()).hexdigest()
    receipt = {
        "schemaVersion": "mercury.video-receipt/1",
        "file": FINAL_NAME,
        "releaseSha": RELEASE_SHA,
        "recordedFrom": "local server, MERCURY_OFFLINE=1, desktop Chromium at 1920x1080, D-pad bridge",
        "publicDeployment": "live",
        "durationSeconds": round(duration, 3),
        "width": 1920,
        "height": 1080,
        "fps": FPS,
        "sceneCount": len(scenes),
        "titleCardSeconds": TITLE_SECONDS,
        "narrationSeconds": narration_total,
        "closingCardSeconds": OUTRO_SECONDS,
        "voiceId": timing.get("voiceId"),
        "modelId": timing.get("modelId"),
        "charactersInNarration": timing.get("charactersInNarration"),
        "charactersSentAllCalls": timing.get("charactersSentAllCalls"),
        "capture": {
            "sha256": capture_receipt.get("sha256"),
            "trimLeadSeconds": trim_lead,
            "pageErrors": capture_receipt.get("pageErrors"),
        },
        "sha256": digest,
        "bytes": final.stat().st_size,
    }
    (OUTPUT / "video-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, separators=(",", ":")))


if __name__ == "__main__":
    main()
