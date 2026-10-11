#!/usr/bin/env bash
# The control: Amazon's helloWorld template, which has no WebView, installed,
# launched and given one D-pad press on the VVD. If this renders and moves
# focus while Mercury's WebView app does not install, the difference is the
# WebView module, not the pipeline.
#
# helloWorld opens with focus on its first tile (Home) in a row of four, so
# KEY_RIGHT must change the frame. That frame change is the only proof this
# run has that key injection moves focus on the VVD.
set -uo pipefail
source "$(dirname "$0")/lib.sh"

status control_result not_run
vpkg="$(status_of control_vpkg)"
if [ -z "$vpkg" ] || [ ! -f "$vpkg" ]; then
  status control_result no_vpkg
  echo "::error::no helloWorld x86_64 vpkg to install"
  exit 1
fi
device="$(device_name)"

recording=""
if python3 "$CI_DIR/vvd_console.py" record-start "$OUT/vvd-control.webm" 120 > "$OUT/logs/control-screenrecord.log" 2>&1; then
  recording=1
fi
stop_recording() {
  if [ -n "$recording" ]; then
    python3 "$CI_DIR/vvd_console.py" record-stop >> "$OUT/logs/control-screenrecord.log" 2>&1 || true
    recording=""
    sleep 3
  fi
}
trap stop_recording EXIT

mark "control: install helloWorld"
if ! timeout 300 vega device install-app -p "$vpkg" --device "$device" < /dev/null > "$OUT/logs/control-install.log" 2>&1; then
  cat "$OUT/logs/control-install.log"
  status control_result install_failed
  exit 1
fi
mark "control: launch helloWorld"
if ! timeout 120 vega device launch-app --device "$device" --appName "$CONTROL_APP_ID" < /dev/null > "$OUT/logs/control-launch.log" 2>&1; then
  cat "$OUT/logs/control-launch.log"
  status control_result launch_failed
  exit 1
fi
sleep 20
vega device running-apps --device "$device" > "$OUT/logs/control-running-apps.txt" 2>&1 || true
shot 10-control-launched
key KEY_RIGHT
sleep 4
shot 11-control-after-right
stop_recording

home="$OUT/frames/00-vvd-ready.png"
before="$OUT/frames/10-control-launched.png"
after="$OUT/frames/11-control-after-right.png"
if nonblack_ok "$before" 0.004 && ! cmp -s "$home" "$before"; then
  status control_rendered yes
else
  status control_rendered no
fi
if [ -s "$after" ] && ! cmp -s "$before" "$after"; then
  status control_focus_moved yes
else
  status control_focus_moved no
fi
grep -q hellovega "$OUT/logs/control-running-apps.txt" && status control_running yes || status control_running no
if [ "$(status_of control_rendered)" = yes ] && [ "$(status_of control_focus_moved)" = yes ]; then
  status control_result rendered_and_focus_moved
elif [ "$(status_of control_rendered)" = yes ]; then
  status control_result rendered_focus_not_moved
else
  status control_result not_rendered
fi
timeout 60 vega device terminate-app --device "$device" --appName "$CONTROL_APP_ID" < /dev/null > /dev/null 2>&1 || true
echo "control: $(status_of control_result), running-apps lists it: $(status_of control_running)"
[ "$(status_of control_result)" = rendered_and_focus_moved ]
