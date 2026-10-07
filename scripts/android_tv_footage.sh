#!/usr/bin/env bash
# Records the Android TV D-pad journey as footage for the demo video.
#
# This is footage, not runtime proof. It never writes android_tv_runtime_receipt.json;
# gate J4 rests on scripts/android_tv_smoke.sh. The journey is the same one, driven at
# a pace a viewer can follow: the Leanback home screen, the launch, the opening answer,
# then Stage, Confirm (record-only) and Publish with the key codes a TV remote emits.
# The launch is the one a viewer makes: D-pad presses from the home screen to the
# Mercury tile, each one chosen from a uiautomator dump (scripts/android_tv_tile_focus.py),
# then Center once the dump shows that the focused node names Mercury. If the tile is not
# focused within FOOTAGE_MAX_DPAD_PRESSES presses, or Center does not start Mercury, the
# script falls back to 'am start' and says so in timeline.tsv and footage-provenance.json.
# screenrecord is the primary capture; a 1 fps screencap sequence is the fallback,
# because the emulator's software GPU can break screenrecord.
set -euo pipefail

endpoint="https://leol25sezuvokpankox5cvjopm0gtvfa.lambda-url.eu-west-1.on.aws/"
apk="app/build/outputs/apk/debug/app-debug.apk"
out="build/android-tv-footage"
pace="${FOOTAGE_PACE_SECONDS:-3}"
# Each move waits half the pace on top of the dump that follows it; the focused tile
# is held for the full pace before Center.
nav_pace="$(awk -v p="$pace" 'BEGIN { printf "%.2f", p / 2 }')"
max_presses="${FOOTAGE_MAX_DPAD_PRESSES:-20}"
package="io.github.upgradedev.mercury.wallboard"
mkdir -p "$out/frames" "$out/ui"

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

mercury_pid=""
current_pid() {
  adb shell pidof "$package" 2>/dev/null | tr -d '\r' || true
}

wait_for_event() {
  local event="$1"
  local deadline=$((SECONDS + 120))
  local now
  while (( SECONDS < deadline )); do
    if adb logcat -d -s MercuryCockpit:I '*:S' 2>/dev/null | grep -Fq "$event"; then
      return 0
    fi
    now="$(current_pid)"
    if [[ -z "$now" ]]; then
      echo "Mercury process exited before event: $event" >&2
      return 1
    fi
    # A new process means the system killed Mercury and something started it again
    # (run 37573814194: Play services restarted itself and took Mercury with it, then
    # the journey's own Right and Center relaunched it from the launcher).
    if [[ -n "$mercury_pid" && "$now" != "$mercury_pid" ]]; then
      echo "Mercury was restarted (pid $mercury_pid, now $now) before event: $event" >&2
      adb logcat -d 2>/dev/null | grep -E "Killing [0-9]+:$package|has died" > "$out/mercury-killed.txt" || true
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

dump_ui() {
  local file
  file="$out/ui/$(printf '%02d' "$1").xml"
  local try
  for try in 1 2 3; do
    if adb shell uiautomator dump /sdcard/ui.xml >/dev/null 2>&1 \
      && adb exec-out cat /sdcard/ui.xml > "$file" 2>/dev/null \
      && [[ -s "$file" ]]; then
      echo "$file"
      return 0
    fi
    sleep 1
  done
  return 1
}

# Captured first, then matched: with pipefail, grep -q closing a pipe early can fail it.
resumed_line() {
  local activities
  activities="$(adb shell dumpsys activity activities 2>/dev/null || true)"
  grep -E 'ResumedActivity' <<< "$activities" || true
}

mercury_resumed() {
  adb shell pidof "$package" >/dev/null 2>&1 || return 1
  [[ "$(resumed_line)" == *"$package/"* ]]
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
adb shell am force-stop "$package"
# After a cold boot Play services can restart itself once, and the system then kills
# every app using its font provider, Mercury's WebView included (run 37573814194).
# Wait until com.google.android.gms.persistent has kept one pid for 90 s, at most 300 s,
# before recording; the outcome goes to play-services-settle.txt.
settle_deadline=$((SECONDS + 300))
settle_pid=""
settle_since=$SECONDS
settle_note="did not settle within 300 s"
while (( SECONDS < settle_deadline )); do
  gms_pid="$(adb shell pidof com.google.android.gms.persistent 2>/dev/null | tr -d '\r' || true)"
  if [[ "$gms_pid" != "$settle_pid" ]]; then
    settle_pid="$gms_pid"
    settle_since=$SECONDS
  fi
  if [[ -z "$gms_pid" ]] && ! adb shell pm path com.google.android.gms >/dev/null 2>&1; then
    settle_note="no Play services on this image"
    break
  fi
  if [[ -n "$gms_pid" ]] && (( SECONDS - settle_since >= 90 )); then
    settle_note="pid $gms_pid unchanged for 90 s"
    break
  fi
  sleep 5
done
echo "Play services: $settle_note" | tee "$out/play-services-settle.txt"
# Give the launcher time to add the new tile before going home.
sleep 5
adb shell input keyevent KEYCODE_HOME
sleep 3
adb shell cmd package resolve-activity --brief -a android.intent.action.MAIN \
  -c android.intent.category.HOME > "$out/home-activity.txt" 2>&1 || true

adb shell rm -f /sdcard/journey.mp4
adb shell screenrecord --time-limit 175 --bit-rate 8000000 /sdcard/journey.mp4 > "$out/screenrecord.log" 2>&1 &
rec_pid=$!
touch "$out/.recording"
frames_loop &
frames_pid=$!
mark "Leanback home screen"
sleep "$pace"

# Walk the home screen to the Mercury tile. Every decision is kept in ui/decisions.tsv
# and every dump in ui/NN.xml.
printf 'dump\taction\tdetail\n' > "$out/ui/decisions.tsv"
presses=0
step=0
focused_label=""
fallback_reason="Mercury tile not focused after $max_presses presses"
sweep="KEYCODE_DPAD_RIGHT"
last_signature=""
last_key=""
# The walk must leave the journey room inside screenrecord's 175 s.
nav_deadline=$((SECONDS + 75))
while :; do
  file="$(dump_ui "$step")" || file=""
  decision="NOFOCUS"$'\t'"uiautomator dump failed"
  if [[ -n "$file" ]]; then
    decision="$(python3 scripts/android_tv_tile_focus.py "$file" --target Mercury 2>>"$out/ui/focus.log")" \
      || decision="NOFOCUS"$'\t'"focus helper failed"
  fi
  action="${decision%%$'\t'*}"
  detail="${decision#*$'\t'}"
  printf '%02d\t%s\t%s\n' "$step" "$action" "$detail" >> "$out/ui/decisions.tsv"
  step=$((step + 1))
  if [[ "$action" == "FOCUSED" ]]; then
    focused_label="$detail"
    break
  fi
  if (( presses >= max_presses )); then
    break
  fi
  if (( SECONDS >= nav_deadline )); then
    fallback_reason="Mercury tile not focused within 75 s ($presses presses)"
    break
  fi
  case "$action" in
    KEYCODE_DPAD_UP|KEYCODE_DPAD_DOWN|KEYCODE_DPAD_LEFT|KEYCODE_DPAD_RIGHT)
      key="$action"
      ;;
    OPEN)
      mark "focus on the launcher's $detail entry"
      sleep "$nav_pace"
      key="KEYCODE_DPAD_CENTER"
      ;;
    SEARCH)
      # Neither the tile nor an Apps entry is on screen: sweep along the row, and
      # drop a row and turn round when focus stops moving.
      if [[ "$detail" == "$last_signature" && "$last_key" == "$sweep" ]]; then
        key="KEYCODE_DPAD_DOWN"
        if [[ "$sweep" == "KEYCODE_DPAD_RIGHT" ]]; then sweep="KEYCODE_DPAD_LEFT"; else sweep="KEYCODE_DPAD_RIGHT"; fi
      elif [[ "$detail" == "$last_signature" && "$last_key" == "KEYCODE_DPAD_DOWN" ]]; then
        fallback_reason="focus stopped moving before the Mercury tile appeared"
        break
      else
        key="$sweep"
      fi
      last_signature="$detail"
      ;;
    *)
      # No focused node yet: any D-pad key gives the launcher focus.
      key="KEYCODE_DPAD_DOWN"
      ;;
  esac
  press "$key"
  last_key="$key"
  presses=$((presses + 1))
  if [[ "$key" == "KEYCODE_DPAD_CENTER" ]]; then sleep 3; else sleep "$nav_pace"; fi
done

launch_path="am_start_fallback"
if [[ -n "$focused_label" ]]; then
  mark "focus on the Mercury tile: $focused_label"
  sleep "$pace"
  mark "launch Mercury from the Leanback launcher"
  press KEYCODE_DPAD_CENTER
  presses=$((presses + 1))
  # wait_for_event gives up as soon as Mercury has no process, so wait for the
  # activity before waiting for the page.
  deadline=$((SECONDS + 30))
  while (( SECONDS < deadline )); do
    if mercury_resumed; then
      launch_path="dpad"
      break
    fi
    sleep 1
  done
  if [[ "$launch_path" == "dpad" ]]; then
    mercury_pid="$(current_pid)"
    {
      echo "Launched by KEYCODE_DPAD_CENTER on the focused tile: $focused_label"
      resumed_line
    } | tee "$out/launcher.txt"
  else
    fallback_reason="Center on the focused tile did not start Mercury within 30 s"
  fi
fi
if [[ "$launch_path" == "dpad" ]]; then
  launch_detail="$presses presses, focus on \"$focused_label\", then KEYCODE_DPAD_CENTER"
  mark "launch path: dpad ($launch_detail)"
else
  launch_detail="$fallback_reason"
  mark "launch path: am start fallback ($launch_detail)"
  mark "launch Mercury from the Leanback launcher"
  adb shell am start -W \
    -a android.intent.action.MAIN \
    -c android.intent.category.LEANBACK_LAUNCHER \
    -n "$package/.MainActivity" \
    | tee "$out/launcher.txt"
  mercury_pid="$(current_pid)"
fi
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
python3 - "$out" "$device_model" "$os_version" "$launch_path" "$presses" "$launch_detail" <<'PY'
import json
import os
import sys
from pathlib import Path

out, device_model, os_version = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
launch_path, launch_presses, launch_detail = sys.argv[4], int(sys.argv[5]), sys.argv[6]
home_activity = out / "home-activity.txt"
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
    # "dpad": Center on the tile the dump showed focused; "am_start_fallback": it did not.
    "launch_path": launch_path,
    "launch_presses": launch_presses,
    "launch_detail": launch_detail,
    "home_activity": home_activity.read_text(encoding="utf-8", errors="replace").strip()
    if home_activity.exists() else "",
    "play_services_settle": (out / "play-services-settle.txt").read_text(encoding="utf-8").strip()
    if (out / "play-services-settle.txt").exists() else "",
    "timeline": [line.split("\t") for line in (out / "timeline.tsv").read_text(encoding="utf-8").splitlines()[1:]],
}
(out / "footage-provenance.json").write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
print(json.dumps(provenance, indent=2))
PY
