#!/usr/bin/env bash
# Mercury on the VVD: install the x86_64 vpkg, launch it, wait for the board,
# then drive the same remote journey as scripts/android_tv_footage.sh on Fire
# OS: Right and Center (Stage), Right and Center (Confirm, record-only on the
# public demo), Center (Publish). Center is KEY_ENTER: the WebView delivers it as
# Enter, keyCode 13 (develop-your-app-with-webview.html, remote key events).
#
# Amazon documents that the VVD has no WebView module on Ubuntu or Intel Macs
# (kvd-issues.html, "Webview-based Vega app fails on Ubuntu"). This script
# records that outcome as blocked_webview_module_missing when the install
# reports a missing module, and exits 0 only for that documented outcome or a
# completed journey.
set -uo pipefail
source "$(dirname "$0")/lib.sh"

status mercury_result not_run
vpkg_name="$(status_of mercury_vpkg_x86_64)"
vpkg="$OUT/vpkg/$vpkg_name"
if [ -z "$vpkg_name" ] || [ ! -f "$vpkg" ]; then
  status mercury_result no_x86_64_vpkg
  echo "::error::no Mercury x86_64 vpkg to install"
  exit 1
fi
device="$(device_name)"

# The device log carries the app's console lines, journey events included.
vda shell loggingctl log -o short-precise -f > "$OUT/logs/device.log" 2>&1 &
log_pid=$!
recording=""
if python3 "$CI_DIR/vvd_console.py" record-start "$OUT/journey.webm" 180 > "$OUT/logs/screenrecord.log" 2>&1; then
  recording=1
fi

finish() {
  if [ -n "$recording" ]; then
    python3 "$CI_DIR/vvd_console.py" record-stop >> "$OUT/logs/screenrecord.log" 2>&1 || true
    sleep 3
  fi
  kill "$log_pid" 2>/dev/null || true
  grep -F 'journey:' "$OUT/logs/device.log" > "$OUT/journey-events.txt" 2>/dev/null || true
  grep -iE 'MercuryCockpit|webview|module dependency' "$OUT/logs/device.log" | head -400 \
    > "$OUT/logs/device-mercury.log" 2>/dev/null || true
  echo "Mercury on the VVD: $(status_of mercury_result)"
}
trap finish EXIT

mark "Mercury: VVD home screen"
shot 20-mercury-before-install

mark "Mercury: install the x86_64 vpkg"
timeout 300 vega device install-app -p "$vpkg" --device "$device" < /dev/null > "$OUT/logs/mercury-install.log" 2>&1
install_rc=$?
cat "$OUT/logs/mercury-install.log"
needs_modules() {  # needs_modules <manifest.toml>: the [[needs.module]] ids, sorted
  awk '/^\[/{inside = ($0 ~ /^\[\[needs\.module\]\]/)} inside && /^id *=/{gsub(/^id *= *"|" *$/, ""); print}' "$1" | sort
}
if [ $install_rc != 0 ]; then
  sleep 3
  missing="$(grep -hiE 'module dependency not found|IWebview|webview_[0-9]' \
    "$OUT/logs/mercury-install.log" "$OUT/logs/device.log" 2>/dev/null | head -8)"
  printf '%s\n' "$missing" > "$OUT/status/mercury_missing_module"
  # What Mercury needs that the control app (installed fine) does not.
  comm -23 <(needs_modules "$(status_of mercury_app_dir)/manifest.toml") \
    <(needs_modules "$(status_of template_root_helloWorld)/manifest.toml") > "$OUT/status/mercury_extra_needs"
  if grep -qi 'module dependency not found' <<< "$missing"; then
    if grep -qiE 'IWebview|webview_[0-9]' <<< "$missing"; then
      status mercury_result blocked_webview_module_missing
    elif [ "$(cat "$OUT/status/mercury_extra_needs")" = "/com.amazon.kepler.webview_4@IWebview_4" ] \
      && [ "$(status_of control_result)" = rendered ]; then
      # The error does not name the module, but the only module Mercury needs
      # beyond the control app (which installed and rendered) is the WebView.
      status mercury_result blocked_webview_module_missing
      echo "unnamed in the error; the only extra need over the control is webview_4" >> "$OUT/status/mercury_missing_module"
    else
      status mercury_result blocked_other_module_missing
      shot 21-mercury-install-refused
      exit 1
    fi
    echo "::warning::Amazon's documented VVD limit reproduced: $missing"
    shot 21-mercury-install-refused
    exit 0
  fi
  status mercury_result install_failed
  shot 21-mercury-install-failed
  exit 1
fi

mark "Mercury: launch"
if ! timeout 120 vega device launch-app --device "$device" --appName "$APP_ID" < /dev/null > "$OUT/logs/mercury-launch.log" 2>&1; then
  cat "$OUT/logs/mercury-launch.log"
  status mercury_result launch_failed
  shot 21-mercury-launch-failed
  exit 1
fi
vega device running-apps --device "$device" > "$OUT/logs/mercury-running-apps.txt" 2>&1 || true

if ! wait_log "journey:page_loaded:" 240 21-mercury-loading; then
  status mercury_result page_not_loaded
  shot 22-mercury-page-not-loaded
  grep -iE 'module dependency|IWebview' "$OUT/logs/device.log" | head -5 > "$OUT/status/mercury_missing_module" || true
  if [ -s "$OUT/status/mercury_missing_module" ]; then
    status mercury_result blocked_webview_module_missing
    exit 0
  fi
  exit 1
fi
mark "board loaded from the public demo"
shot 22-board-loaded

# Stage stays disabled until the opening correlation renders (run 36915746324).
wait_log "journey:what_changed:" 120 23-what-changed || { status mercury_result no_opening_answer; exit 1; }
mark "opening answer: what changed"
sleep 3
shot 23-opening-answer

key KEY_RIGHT
sleep 1
key KEY_ENTER
wait_log "journey:rollback_staged:" 90 || { status mercury_result stage_not_seen; shot 24-stage-missing; exit 1; }
mark "rollback staged"
sleep 3
shot 24-rollback-staged

key KEY_RIGHT
sleep 1
key KEY_ENTER
wait_log "journey:rollback_confirmed:RECORDED_ONLY:DPAD_RECORD_ONLY_DEMO" 90 \
  || { status mercury_result confirm_not_seen; shot 25-confirm-missing; exit 1; }
mark "rollback confirmed, record-only"
sleep 3
shot 25-rollback-confirmed

key KEY_ENTER
wait_log "journey:handoff_published:checkout-api-active:" 90 \
  || { status mercury_result publish_not_seen; shot 26-publish-missing; exit 1; }
mark "responder handoff published"
sleep 3
shot 26-handoff-published
status mercury_result journey_complete

# BACK: the page has nothing open, so the app should leave (MainActivity parity).
key KEY_BACK
sleep 6
vega device running-apps --device "$device" > "$OUT/logs/mercury-running-after-back.txt" 2>&1 || true
if grep -q 'com.upgradedev.mercury' "$OUT/logs/mercury-running-after-back.txt"; then
  status mercury_back still_running
else
  status mercury_back exited
fi
shot 27-after-back
exit 0
