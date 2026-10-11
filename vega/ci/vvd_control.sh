#!/usr/bin/env bash
# The control: Amazon's helloWorld template, which has no WebView, installed,
# launched and given one D-pad press on the VVD. If this renders and Mercury's
# WebView app does not, the difference is the WebView module, not the pipeline.
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
key KEY_DOWN
sleep 4
shot 11-control-after-down

home="$OUT/frames/00-vvd-ready.png"
launched="$OUT/frames/10-control-launched.png"
if [ ! -s "$launched" ]; then launched="$OUT/frames/10-control-launched.guest.png"; home="$OUT/frames/00-vvd-ready.guest.png"; fi
if nonblack_ok "$launched" 0.004 && ! cmp -s "$home" "$launched"; then
  status control_result rendered
else
  status control_result not_rendered
fi
grep -q hellovega "$OUT/logs/control-running-apps.txt" && status control_running yes || status control_running no
timeout 60 vega device terminate-app --device "$device" --appName "$CONTROL_APP_ID" > /dev/null 2>&1 || true
echo "control: $(status_of control_result), running-apps lists it: $(status_of control_running)"
[ "$(status_of control_result)" = rendered ]
