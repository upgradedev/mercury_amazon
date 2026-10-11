#!/usr/bin/env python3
"""Write vega-provenance.json and the job summary, or give the run's verdict.

    provenance.py <OUT>            writes <OUT>/vega-provenance.json and the summary
    provenance.py <OUT> --stitch   writes <OUT>/frames-1fps.mp4 from the frames
    provenance.py <OUT> --verdict  exits non-zero unless the run met its bar

Footage, not a runtime receipt: nothing here is read by ci/readiness.py, and
gate J4 still rests on .github/workflows/android-tv-emulator.yml.

The bar: an armv7 vpkg was built, the helloWorld control rendered on the VVD
and a D-pad press changed its frame, and Mercury either completed the remote
journey or hit the one documented limit, the VVD's missing WebView module
(kvd-issues.html).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ACCEPTED_MERCURY = {"journey_complete", "blocked_webview_module_missing"}


def read_status(out: Path) -> dict[str, str]:
    folder = out / "status"
    if not folder.is_dir():
        return {}
    return {p.name: p.read_text(encoding="utf-8", errors="replace").strip() for p in sorted(folder.iterdir()) if p.is_file()}


def read_tsv(path: Path) -> list[list[str]]:
    if not path.exists():
        return []
    return [line.split("\t") for line in path.read_text(encoding="utf-8").splitlines()[1:] if line.strip()]


def vvd_status(status: dict[str, str]) -> str:
    """The same four outcomes the task reports."""
    if status.get("sdk_install") != "ok":
        return "install_blocked"
    if not status.get("mercury_vpkg_armv7"):
        return "build_blocked"
    if status.get("mercury_result") == "journey_complete":
        return "app_running_on_vvd_with_footage"
    return "builds_but_vvd_blocked"


def build(out: Path) -> dict:
    status = read_status(out)
    health_path = out / "endpoint-health.json"
    health = json.loads(health_path.read_text(encoding="utf-8")) if health_path.exists() else {}
    sums = {}
    sums_path = out / "vpkg" / "SHA256SUMS"
    if sums_path.exists():
        for line in sums_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                digest, name = line.split(maxsplit=1)
                sums[name.strip().lstrip("*")] = {
                    "sha256": digest,
                    "bytes": (out / "vpkg" / name.strip().lstrip("*")).stat().st_size,
                }
    frames = [
        {"frame": row[0], "method": row[1], "bytes": int(row[2]), "size_and_nonblack": row[3]}
        for row in read_tsv(out / "frames" / "index.tsv") if len(row) >= 4
    ]
    videos = {path.name: path.stat().st_size for path in sorted(out.glob("*.webm"))}
    stitched = out / "frames-1fps.mp4"
    events = (out / "journey-events.txt")
    return {
        "kind": "footage and build evidence, not a runtime receipt",
        "workflow_sha": os.environ.get("GITHUB_SHA", "local"),
        "workflow_run_url": "{}/{}/actions/runs/{}".format(
            os.environ.get("GITHUB_SERVER_URL", "https://github.com"),
            os.environ.get("GITHUB_REPOSITORY", "local"),
            os.environ.get("GITHUB_RUN_ID", "local"),
        ),
        "public_demo_build_sha": health.get("build_sha"),
        "rollback_dispatch": health.get("rollback_dispatch"),
        "vvd_status": vvd_status(status),
        "sdk_version": status.get("sdk_version"),
        "mercury_build_mode": status.get("mercury_build_mode"),
        "mercury_jest": status.get("mercury_jest"),
        "mercury_tsc": status.get("mercury_tsc"),
        "vpkgs": sums,
        "vvd": {
            "boot": status.get("vvd_boot"),
            "gpu_mode": status.get("vvd_gpu_mode"),
            "capture": status.get("vvd_capture"),
            "developer_mode": status.get("vvd_developer_mode"),
            "device_name": status.get("device_name"),
        },
        "control_result": status.get("control_result"),
        "control_rendered": status.get("control_rendered"),
        "control_focus_moved": status.get("control_focus_moved"),
        "control_running": status.get("control_running"),
        "mercury_result": status.get("mercury_result"),
        "mercury_missing_module": status.get("mercury_missing_module"),
        "mercury_back": status.get("mercury_back"),
        "journey_events": events.read_text(encoding="utf-8").splitlines() if events.exists() else [],
        "screenrecord_bytes": videos,
        "stitched_video_bytes": stitched.stat().st_size if stitched.exists() else 0,
        "frames": frames,
        "timeline": read_tsv(out / "timeline.tsv"),
        "status": status,
    }


def summary(record: dict) -> str:
    rows = [
        ("VVD status", record["vvd_status"]),
        ("Vega SDK", record["sdk_version"]),
        ("Public demo build", f"{record['public_demo_build_sha']} ({record['rollback_dispatch']})"),
        ("Build mode", record["mercury_build_mode"]),
        ("Jest / tsc", f"{record['mercury_jest']} / {record['mercury_tsc']}"),
        ("vpkgs", ", ".join(f"{name} {meta['bytes']} B sha256 {meta['sha256'][:12]}" for name, meta in record["vpkgs"].items()) or "none"),
        ("VVD boot", f"{record['vvd']['boot']} ({record['vvd']['gpu_mode']}, capture {record['vvd']['capture']}, developer mode {record['vvd']['developer_mode']})"),
        ("Control (helloWorld)", f"{record['control_result']} (running-apps: {record['control_running']})"),
        ("Screen recordings", ", ".join(f"{name} {size} B" for name, size in record["screenrecord_bytes"].items()) or "none"),
        ("Mercury on the VVD", record["mercury_result"]),
        ("Missing module", (record["mercury_missing_module"] or "").replace("\n", " / ")),
        ("Journey events", str(len(record["journey_events"]))),
        ("Frames", str(len(record["frames"]))),
    ]
    lines = ["### Mercury on Vega OS", "", "| | |", "|---|---|"]
    lines += [f"| {key} | {str(value).replace('|', '/')} |" for key, value in rows]
    return "\n".join(lines) + "\n"


def verdict(record: dict) -> list[str]:
    problems = []
    if record["rollback_dispatch"] != "record-only":
        problems.append(f"public demo is not record-only: {record['rollback_dispatch']!r}")
    if not any(name.endswith("_armv7.vpkg") for name in record["vpkgs"]):
        problems.append("no armv7 vpkg was built")
    if record["vvd"]["boot"] != "ready":
        problems.append(f"the VVD did not boot to a visible screen: {record['vvd']['boot']}")
    if record["control_result"] != "rendered_and_focus_moved":
        problems.append(f"the helloWorld control did not render and move focus: {record['control_result']}")
    if record["mercury_result"] not in ACCEPTED_MERCURY:
        problems.append(f"Mercury on the VVD: {record['mercury_result']}")
    return problems


def stitch(out: Path) -> int:
    """Join the step frames into a video, two seconds each, in name order.

    For each step the console capture is used when it rendered, else the
    in-guest one. The console's screenrecord webm files are the primary video;
    this is the step-by-step version a reader can scrub.
    """
    import subprocess

    scores: dict[tuple[str, str], float] = {}
    for row in read_tsv(out / "frames" / "index.tsv"):
        if len(row) >= 4:
            try:
                scores[(row[0], row[1])] = float(row[3].split()[-1])
            except ValueError:
                continue
    names = sorted({name for name, _method in scores if "-wait" not in name})
    chosen = []
    for name in names:
        for method, suffix in (("console", ".png"), ("guest", ".guest.png")):
            if scores.get((name, method), 0.0) > 0.004:
                chosen.append(out / "frames" / f"{name}{suffix}")
                break
    if not chosen:
        print("no rendered frames to stitch")
        return 0
    concat = out / "frames" / "concat.txt"
    lines = []
    for path in chosen:
        lines += [f"file '{path.as_posix()}'", "duration 2"]
    lines.append(f"file '{chosen[-1].as_posix()}'")
    concat.write_text("\n".join(lines) + "\n", encoding="utf-8")
    result = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(concat),
         "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,format=yuv420p",
         "-c:v", "libx264", "-r", "25", str(out / "frames-1fps.mp4")],
        check=False,
    )
    print(f"stitched {len(chosen)} frames, ffmpeg exit {result.returncode}")
    return 0


def main(argv: list[str]) -> int:
    out = Path(argv[1])
    if "--stitch" in argv:
        return stitch(out)
    record = build(out)
    if "--verdict" in argv:
        problems = verdict(record)
        for problem in problems:
            print(f"::error::{problem}")
        if record["mercury_result"] == "blocked_webview_module_missing":
            print("::warning::Mercury's WebView app does not install on the Ubuntu VVD: the documented missing WebView module")
        print(f"vvd_status={record['vvd_status']}")
        return 1 if problems else 0
    (out / "vega-provenance.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as handle:
            handle.write(summary(record))
    print(summary(record))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
