#!/usr/bin/env bash
# Records the Android TV D-pad journey as footage for the demo video.
#
# This is footage, not runtime proof. It never writes android_tv_runtime_receipt.json;
# gate J4 rests on scripts/android_tv_smoke.sh. The journey is the same one, driven at
# a pace a viewer can follow: the Leanback home screen, the launch, the opening answer,
# then Stage, Confirm (record-only) and Publish with the key codes a TV remote emits.
# screenrecord is the primary capture; a 1 fps screencap sequence is the fallback,
# because the emulator's software GPU can break screenrecord.
set -euo pipefail

endpoint="https://leol25sezuvokpankox5cvjopm0gtvfa.lambda-url.eu-west-1.on.aws/"
apk="app/build/outputs/apk/debug/app-debug.apk"
out="build/android-tv-footage"
pace="${FOOTAGE_PACE_SECONDS:-3}"
mkdir -p "$out/frames"

if [[ ! -s "$out/endpoint-health.json" ]]; then
  echo "The public demo's /health record is missing" >&2
  exit 1
fi

keys="$out/timeline.tsv"
printf 'seconds\tstep\n' > "$keys"
t0="$(date +%s.%N)"
mark() {
  printf '%s\t%s\n' "$(awk -v a="$(date +%s.%N)" -v b="$t0" 'BEGIN { printf "%.2f", a - b }')" "$1" >> "$keys"
}

wait_for_event() {
  local event="$1"
  local deadline=$((SECONDS + 120))
  while (( SECONDS < deadline )); do
    if adb logcat -d -s MercuryCockpit:I '*:S' 2>/dev/null | grep -Fq "$event"; then
      return 0
    fi
    if ! adb shell pidof io.github.upgradedev.mercury.wallboard >/dev/null 2>&1; then
      echo "Mercury process exited before event: $event" >&2
      return 1
    fi
    sleep 1
  done
  echo "Timed out waiting for event: $event" >&2
  return 1
}

press() {
  mark "$1"
  adb shell input keyevent "$1"
}

frames_loop() {
  local i=0
  while [[ -e "$out/.recording" ]]; do
    adb exec-out screencap -p > "$out/frames/$(printf '%04d' "$i").png" 2>/dev/null || true
    i=$((i + 1))
    sleep 1
  done
}

rec_pid=""
frames_pid=""
stop_recording() {
  rm -f "$out/.recording"
  adb shell 'kill -2 $(pidof screenrecord)' >/dev/null 2>&1 || true
  sleep 3
  if [[ -n "$rec_pid" ]]; then wait "$rec_pid" 2>/dev/null || true; fi
  if [[ -n "$frames_pid" ]]; then wait "$frames_pid" 2>/dev/null || true; fi
  adb pull /sdcard/journey.mp4 "$out/journey.mp4" > "$out/pull.log" 2>&1 || true
  adb exec-out screencap -p > "$out/final.png" 2>/dev/null || true
  adb logcat -d > "$out/logcat.txt" 2>&1 || true
}
trap stop_recording EXIT

adb logcat -c
adb install -r "$apk" | tee "$out/adb-install.txt"
adb shell am force-stop io.github.upgradedev.mercury.wallboard
adb shell input keyevent KEYCODE_HOME
sleep 3

adb shell rm -f /sdcard/journey.mp4
adb shell screenrecord --time-limit 175 --bit-rate 8000000 /sdcard/journey.mp4 > "$out/screenrecord.log" 2>&1 &
rec_pid=$!
touch "$out/.recording"
frames_loop &
frames_pid=$!
mark "Leanback home screen"
sleep "$pace"

mark "launch Mercury from the Leanback launcher"
adb shell am start -W \
  -a android.intent.action.MAIN \
  -c android.intent.category.LEANBACK_LAUNCHER \
  -n io.github.upgradedev.mercury.wallboard/.MainActivity \
  | tee "$out/launcher.txt"
wait_for_event "journey:page_loaded:$endpoint"
mark "board loaded from the public demo"
# Stage stays disabled until the opening correlation renders (run 36915746324).
wait_for_event "journey:what_changed:"
mark "opening answer: what changed"
sleep "$pace"

press KEYCODE_DPAD_RIGHT
sleep 1
press KEYCODE_DPAD_CENTER
wait_for_event "journey:rollback_staged:"
mark "rollback staged"
sleep "$pace"

press KEYCODE_DPAD_RIGHT
sleep 1
press KEYCODE_DPAD_CENTER
wait_for_event "journey:rollback_confirmed:RECORDED_ONLY:DPAD_RECORD_ONLY_DEMO"
mark "rollback confirmed, record-only"
sleep "$pace"

press KEYCODE_DPAD_CENTER
wait_for_event "journey:handoff_published:checkout-api-active:"
mark "responder handoff published"
sleep "$pace"
sleep "$pace"

stop_recording
trap - EXIT

device_model="$(adb shell getprop ro.product.model | tr -d '\r')"
os_version="Android $(adb shell getprop ro.build.version.release | tr -d '\r') / API $(adb shell getprop ro.build.version.sdk | tr -d '\r')"
python3 - "$out" "$device_model" "$os_version" <<'PY'
import json
import os
import sys
from pathlib import Path

out, device_model, os_version = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
health = json.loads((out / "endpoint-health.json").read_text(encoding="utf-8"))
video = out / "journey.mp4"
provenance = {
    "kind": "footage, not a runtime receipt",
    "workflow_sha": os.environ.get("GITHUB_SHA", "local"),
    "workflow_run_url": "{}/{}/actions/runs/{}".format(
        os.environ.get("GITHUB_SERVER_URL", "https://github.com"),
        os.environ.get("GITHUB_REPOSITORY", "local"),
        os.environ.get("GITHUB_RUN_ID", "local"),
    ),
    "public_demo_build_sha": health.get("build_sha"),
    "rollback_dispatch": health.get("rollback_dispatch"),
    "device_model": device_model,
    "os_version": os_version,
    "screenrecord_bytes": video.stat().st_size if video.exists() else 0,
    "fallback_frames": len(list((out / "frames").glob("*.png"))),
    "timeline": [line.split("\t") for line in (out / "timeline.tsv").read_text(encoding="utf-8").splitlines()[1:]],
}
(out / "footage-provenance.json").write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
print(json.dumps(provenance, indent=2))
PY
