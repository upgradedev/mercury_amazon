#!/usr/bin/env python3
"""Compose the emulator footage, the capture, the measured narration and the captions
into the demo mp4.

Adapted from the submission kit's video/build-video.py. Kept from the kit: the
picture trimmed to exactly the measured narration, each beat's audio delayed to its
measured start, burned captions derived from that same timing, loudnorm at -16 LUFS,
1920x1080 at 25 fps, and a hard failure when the composed length differs from the
planned length by more than one frame.

What changed for this repository, so the kit's pixel-reading sync gate
(``scripts/verify_video_sync.py``) runs on the result unchanged:

  1. A silent title card opens the video and a silent closing card ends it, both
     rendered here with Pillow. The title card says what Mercury does first, then in
     smaller lines the two sources of the picture: the Android TV emulator footage
     from CI, and the local desktop run of the recorded commit.
  2. The content opens on the Android TV emulator footage: ``journey.mp4`` from the
     ``android-tv-footage.yml`` artifact, the debug APK on an AOSP Android TV
     emulator loading the public demo. The screenrecord is variable frame rate (it
     writes a frame only when the screen changes), so it is converted to 25 fps by
     holding each frame until the next one, at 1x: nothing is sped up, slowed or
     frozen past its own recorded length. The beats marked ``android_tv_emulator`` in
     ``timing.json`` say which window of it plays. A small label under it names the
     emulator, the APK, the public demo build and the CI run for as long as it plays.
  3. The desktop capture follows, scaled to 87.5% and placed at the top of the frame.
     The emulator picture is scaled a little smaller (1600x900) to leave room for its
     label. The captions sit in the band underneath both, so no caption ever covers
     what the board shows. Both pictures were captured at 1920x1080.
  4. The captions are burned once, on the joined content (footage then capture), so
     they run on the narration's own clock. The shifted copy is the upload sidecar.
  5. It writes ``video_manifest.json`` and ``caption_windows.json`` for the gate.
     The gate's four segments stay the title card, ``screencast`` (the content up to
     the last beat: the emulator footage, then the desktop capture), ``web`` (the last
     beat) and the closing card.
  6. The receipt records the voice, the characters synthesized, the card lengths,
     the capture's own receipt and the footage's provenance and digest.

Environment: ``MERCURY_VIDEO_ROOT`` (media folder outside the repository),
``MERCURY_RELEASE_SHA`` (the 40 character commit the local server reported while
it was recorded), ``MERCURY_EMULATOR_FOOTAGE`` (the unpacked footage artifact
folder, holding ``journey.mp4`` and ``footage-provenance.json``), ``FFMPEG`` and
``FFPROBE``.
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import subprocess

from PIL import Image, ImageDraw, ImageFont

REPO = pathlib.Path(__file__).resolve().parent.parent
PLAN = REPO / "video" / "narration.json"
FPS = 25
FRAME_SECONDS = 1 / FPS
TITLE_SECONDS = 4.0
OUTRO_SECONDS = 3.0
# The capture is shown at 1680x945, top-centred; captions live in the band below.
PIC_W, PIC_H, PIC_X, PIC_Y = 1680, 945, 120, 8
# The emulator footage is shown at 1600x900, top-centred, with its label under it and
# the captions in the band below that.
EMU_W, EMU_H, EMU_X, EMU_Y = 1600, 900, 160, 8
EMU_LABEL_Y = EMU_Y + EMU_H + 6
EMULATOR_SOURCE = "android_tv_emulator"
FOOTAGE_KIND = "footage, not a runtime receipt"
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


def footage_facts(provenance: dict[str, object]) -> dict[str, str]:
    """The short facts the label and the cards print, read from the provenance file."""
    run_url = str(provenance.get("workflow_run_url", ""))
    run_id = re.search(r"/actions/runs/(\d+)$", run_url)
    api = re.search(r"\bAPI (\d+)\b", str(provenance.get("os_version", "")))
    demo = str(provenance.get("public_demo_build_sha", ""))
    if not run_id or not api or not re.fullmatch(r"[0-9a-f]{40}", demo):
        raise SystemExit("footage-provenance.json does not name a CI run, an API level and a demo build")
    return {"run_id": run_id.group(1), "api": api.group(1), "demo_short": demo[:7]}


def emulator_label(facts: dict[str, str]) -> str:
    return (
        f"Android TV emulator (API {facts['api']}), debug APK, "
        f"public demo build {facts['demo_short']}, CI run {facts['run_id']}"
    )


def title_lines(short: str, facts: dict[str, str]) -> list[tuple[str, str, int, tuple[int, int, int]]]:
    # The product first: a judge reads what Mercury does before where the take came
    # from. The two sources of the picture follow in smaller lines, in the order they
    # play, and again on the closing card.
    return [
        ("Mercury", "bahnschrift.ttf", 120, AMBER),
        ("An incident board for the team's Fire TV.", "segoeui.ttf", 58, INK),
        ("It names the deploy behind a spike only when it can.", "segoeui.ttf", 58, INK),
        ("", "segoeui.ttf", 30, INK_2),
        (f"Android TV emulator, API {facts['api']}, CI run {facts['run_id']}; "
         f"local desktop run of {short}.", "segoeui.ttf", 34, INK_2),
        ("Offline fixtures, record-only rollback.", "segoeui.ttf", 34, INK_2),
    ]


def outro_lines(short: str, facts: dict[str, str]) -> list[tuple[str, str, int, tuple[int, int, int]]]:
    return [
        ("Mercury", "bahnschrift.ttf", 110, AMBER),
        ("One deploy, or why not.", "segoeui.ttf", 54, INK),
        (f"Emulator footage: CI run {facts['run_id']}, public demo build {facts['demo_short']}.",
         "segoeui.ttf", 40, INK_2),
        (f"Desktop: local run of commit {short}, offline fixtures.", "segoeui.ttf", 40, INK_2),
        ("The emulator runtime receipt is a separate record.", "segoeui.ttf", 40, INK_2),
    ]


def label_plate(path: pathlib.Path, text: str) -> None:
    """A transparent 1920x1080 plate with the footage label centred under the picture."""
    image = Image.new("RGBA", (1920, 1080), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    face = font("segoeui.ttf", 26)
    width = draw.textlength(text, font=face)
    draw.text(((1920 - width) / 2, EMU_LABEL_Y), text, font=face, fill=INK_2 + (255,))
    image.save(path)


def emulator_plan(scenes: list[dict[str, object]]) -> dict[str, object]:
    """Which frames of the footage play, from the emulator scenes in ``timing.json``.

    The emulator scenes must open the narration, cover one unbroken window of the
    footage, and each be held for exactly its window, so the footage plays once, in
    order, at 1x.
    """
    emulator = [scene for scene in scenes if scene.get("source") == EMULATOR_SOURCE]
    if not emulator:
        raise SystemExit("timing.json has no emulator beats; this take opens on the emulator footage")
    if scenes[: len(emulator)] != emulator:
        raise SystemExit("the emulator beats must open the narration, before any desktop beat")
    windows = [scene.get("footageWindowSeconds") for scene in emulator]
    if any(not isinstance(window, list) or len(window) != 2 for window in windows):
        raise SystemExit("every emulator beat needs its footage window in timing.json")
    for scene, window in zip(emulator, windows):
        if abs(float(scene["holdSeconds"]) - (window[1] - window[0])) > 0.0015:
            raise SystemExit(f"{scene['id']} is not held for exactly its footage window")
    for before, after in zip(windows, windows[1:]):
        if abs(before[1] - after[0]) > 1e-9:
            raise SystemExit("the emulator beats do not cover one unbroken window of the footage")
    start_frame = round(windows[0][0] * FPS)
    end_frame = round(windows[-1][1] * FPS)
    if abs(start_frame / FPS - windows[0][0]) > 1e-6 or abs(end_frame / FPS - windows[-1][1]) > 1e-6:
        raise SystemExit("the footage cuts must sit on 25 fps frames")
    return {
        "scenes": [scene["id"] for scene in emulator],
        "start_frame": start_frame,
        "end_frame": end_frame,
        "frames": end_frame - start_frame,
        "seconds": round((end_frame - start_frame) / FPS, 3),
    }


def content_filters(
    *,
    trim_lead: float,
    narration_total: float,
    emulator: dict[str, object],
    subtitle_path: str,
    capture_input: int = 0,
    footage_input: int = 3,
    label_input: int = 4,
) -> list[str]:
    """The video graph for the content: the footage, then the capture, then captions.

    The footage is converted to 25 fps first (``fps`` holds each frame until the next
    one) and then cut by frame number, so the clip is exactly ``emulator['frames']``
    frames at 1x. The capture fills the rest of the narration to the frame. The
    captions are burned on the joined content, so they run on the narration's clock.
    """
    total_frames = round(narration_total * FPS)
    desktop_frames = total_frames - int(emulator["frames"])
    if desktop_frames <= 0:
        raise SystemExit("the emulator footage is longer than the narration")
    desktop_seconds = desktop_frames / FPS
    bg = "0x0E0F11"
    style = (
        "FontName=Arial,FontSize=11,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
        "BorderStyle=1,Outline=0,Shadow=0,MarginV=6,Alignment=2"
    )
    return [
        f"[{footage_input}:v]fps={FPS},trim=start_frame={emulator['start_frame']}:"
        f"end_frame={emulator['end_frame']},setpts=PTS-STARTPTS,"
        f"scale={EMU_W}:{EMU_H}:flags=lanczos,pad=1920:1080:{EMU_X}:{EMU_Y}:color={bg},"
        f"format=yuv420p,setsar=1[emubase]",
        f"[{label_input}:v]format=rgba[emulabel]",
        "[emubase][emulabel]overlay=0:0:shortest=1:format=auto,format=yuv420p,setsar=1[emu]",
        f"[{capture_input}:v]trim=start={trim_lead}:end={trim_lead + desktop_seconds + 1},"
        f"setpts=PTS-STARTPTS,fps={FPS},trim=end_frame={desktop_frames},setpts=PTS-STARTPTS,"
        f"scale={PIC_W}:{PIC_H}:flags=lanczos,pad=1920:1080:{PIC_X}:{PIC_Y}:color={bg},"
        f"format=yuv420p,setsar=1[desk]",
        f"[emu][desk]concat=n=2:v=1:a=0,"
        f"subtitles='{subtitle_path}':force_style='{style}',format=yuv420p,setsar=1[body]",
    ]


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


def load_footage(folder: pathlib.Path, plan: dict[str, object]) -> tuple[pathlib.Path, dict[str, object]]:
    """The footage clip and its provenance, checked against the plan it was cut for."""
    clip = folder / "journey.mp4"
    provenance = json.loads((folder / "footage-provenance.json").read_text(encoding="utf-8"))
    expected = plan.get("emulator_footage") or {}
    if provenance.get("kind") != FOOTAGE_KIND:
        raise SystemExit("the footage provenance does not describe footage")
    if provenance.get("rollback_dispatch") != "record-only":
        raise SystemExit("the footage was not filmed against a record-only demo")
    for key in ("workflow_run_url", "workflow_sha", "public_demo_build_sha", "os_version", "device_model"):
        if provenance.get(key) != expected.get(key):
            raise SystemExit(f"the footage's {key} is not the one video/narration.json was cut for")
    if clip.stat().st_size != provenance.get("screenrecord_bytes"):
        raise SystemExit("journey.mp4 is not the screenrecord the provenance file describes")
    return clip, provenance


def main() -> None:
    root = pathlib.Path(os.environ["MERCURY_VIDEO_ROOT"])
    release_sha = os.environ["MERCURY_RELEASE_SHA"]
    narration_dir = root / "narration"
    capture = root / "capture" / "production.webm"
    output = root / "output"
    cards = root / "cards"
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    footage, provenance = load_footage(pathlib.Path(os.environ["MERCURY_EMULATOR_FOOTAGE"]), plan)
    facts = footage_facts(provenance)

    timing = json.loads((narration_dir / "timing.json").read_text(encoding="utf-8"))
    capture_receipt = json.loads((root / "capture" / "capture-receipt.json").read_text(encoding="utf-8"))
    if capture_receipt.get("releaseSha") != release_sha:
        raise SystemExit("the capture was recorded at a different commit than MERCURY_RELEASE_SHA")
    scenes = timing["scenes"]
    emulator = emulator_plan(scenes)
    if abs(float(capture_receipt.get("narrationStartSeconds", -1)) - emulator["seconds"]) > 0.002:
        raise SystemExit("the capture's timeline does not start where the emulator footage ends")
    footage_seconds = float(probe(footage)["format"]["duration"])
    if emulator["end_frame"] / FPS > footage_seconds + FRAME_SECONDS:
        raise SystemExit("the planned footage window runs past the end of journey.mp4")
    narration_total = float(timing["totalSeconds"])
    total = TITLE_SECONDS + narration_total + OUTRO_SECONDS
    trim_lead = float(capture_receipt["trimLeadSeconds"])
    if not 0 <= trim_lead <= 30:
        raise SystemExit("capture trim lead is outside the bounded contract")
    output.mkdir(parents=True, exist_ok=True)
    cards.mkdir(parents=True, exist_ok=True)

    short = release_sha[:7]
    title_png = cards / "title.png"
    outro_png = cards / "outro.png"
    label_png = cards / "emulator-label.png"
    card(title_png, title_lines(short, facts))
    card(outro_png, outro_lines(short, facts))
    label = emulator_label(facts)
    label_plate(label_png, label)

    # In the finished file every caption starts after the title card: shift each window.
    source = srt_windows((narration_dir / "captions.en.srt").read_text(encoding="utf-8"))
    shifted = [(start + TITLE_SECONDS, end + TITLE_SECONDS, text) for start, end, text in source]
    captions_out = output / "captions.en.srt"
    blocks = []
    for number, (start, end, text) in enumerate(shifted, start=1):
        blocks.extend([str(number), f"{stamp(start)} --> {stamp(end)}", text, ""])
    captions_out.write_text("\n".join(blocks), encoding="utf-8")

    emulator_seconds = emulator["seconds"]
    args = [
        os.environ["FFMPEG"], "-y",
        "-i", str(capture),
        "-loop", "1", "-framerate", str(FPS), "-t", str(TITLE_SECONDS), "-i", str(title_png),
        "-loop", "1", "-framerate", str(FPS), "-t", str(OUTRO_SECONDS), "-i", str(outro_png),
        "-i", str(footage),
        "-loop", "1", "-framerate", str(FPS), "-t", str(emulator_seconds), "-i", str(label_png),
    ]
    filters: list[str] = []
    labels: list[str] = []
    first_audio_input = 5
    for index, scene in enumerate(scenes):
        args.extend(["-i", str(narration_dir / str(scene["audio"]))])
        delay = round((TITLE_SECONDS + float(scene["startSeconds"])) * 1000)
        hold = float(scene["holdSeconds"])
        name = f"a{index}"
        filters.append(
            f"[{first_audio_input + index}:a]aresample=48000,apad=pad_dur={hold},atrim=0:{hold},"
            f"adelay={delay}:all=1[{name}]"
        )
        labels.append(f"[{name}]")
    # The subtitles filter runs on the content before the title card is concatenated
    # in front of it, so it reads the content's own clock, which is the narration's:
    # burn the unshifted captions there. The shifted copy is the sidecar for the file.
    subtitle_path = str(narration_dir / "captions.en.srt").replace("\\", "/").replace(":", "\\:")
    filters.extend(content_filters(
        trim_lead=trim_lead, narration_total=narration_total, emulator=emulator,
        subtitle_path=subtitle_path,
    ))
    filters.append(f"[1:v]fps={FPS},format=yuv420p,setsar=1[title]")
    filters.append(f"[2:v]fps={FPS},format=yuv420p,setsar=1[outro]")
    filters.append("[title][body][outro]concat=n=3:v=1:a=0[v]")
    filters.append(
        f"{''.join(labels)}amix=inputs={len(labels)}:duration=longest:normalize=0,"
        f"loudnorm=I=-16:LRA=7:TP=-1.5,apad=whole_dur={total},atrim=0:{total}[a]"
    )
    final = output / FINAL_NAME
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
    picture = float(videos[0].get("duration") or 0.0)
    if abs(duration - total) > FRAME_SECONDS or abs(picture - total) > FRAME_SECONDS:
        raise SystemExit(
            f"composed {duration:.3f}s (picture {picture:.3f}s) but the cards plus the narration measure {total:.3f}s. "
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
        "emulator_footage_dur": emulator_seconds,
        "note": (
            f"screencast opens with {emulator_seconds:.2f} s of Android TV emulator footage "
            f"from CI run {facts['run_id']} (beats {', '.join(emulator['scenes'])}), then the "
            "desktop capture; web is the last desktop beat, a window of the same continuous "
            "capture"
        ),
    }
    (output / "video_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (output / "caption_windows.json").write_text(
        json.dumps([[round(s, 3), round(e, 3), t] for s, e, t in shifted], indent=2) + "\n",
        encoding="utf-8",
    )

    digest = hashlib.sha256(final.read_bytes()).hexdigest()
    receipt = {
        "schemaVersion": "mercury.video-receipt/1",
        "file": FINAL_NAME,
        "releaseSha": release_sha,
        "recordedFrom": (
            "Android TV emulator footage from CI, then a local server with MERCURY_OFFLINE=1 "
            "in desktop Chromium at 1920x1080 through the D-pad bridge"
        ),
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
        "emulatorFootage": {
            "kind": provenance.get("kind"),
            "workflowRunUrl": provenance.get("workflow_run_url"),
            "workflowSha": provenance.get("workflow_sha"),
            "publicDemoBuildSha": provenance.get("public_demo_build_sha"),
            "deviceModel": provenance.get("device_model"),
            "osVersion": provenance.get("os_version"),
            "sha256": hashlib.sha256(footage.read_bytes()).hexdigest(),
            "bytes": footage.stat().st_size,
            "sourceSeconds": footage_seconds,
            "windowSeconds": [emulator["start_frame"] / FPS, emulator["end_frame"] / FPS],
            "seconds": emulator_seconds,
            "conversion": "variable to 25 fps by holding each frame until the next; 1x",
            "label": label,
        },
        "capture": {
            "sha256": capture_receipt.get("sha256"),
            "trimLeadSeconds": trim_lead,
            "pageErrors": capture_receipt.get("pageErrors"),
        },
        "sha256": digest,
        "bytes": final.stat().st_size,
    }
    (output / "video-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, separators=(",", ":")))


if __name__ == "__main__":
    main()
