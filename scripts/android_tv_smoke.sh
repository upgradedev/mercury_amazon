#!/usr/bin/env bash
set -euo pipefail

endpoint="https://leol25sezuvokpankox5cvjopm0gtvfa.lambda-url.eu-west-1.on.aws/"
apk="app/build/outputs/apk/debug/app-debug.apk"
evidence="build/android-tv-evidence"
endpoint_health="$evidence/endpoint-health.json"
mkdir -p "$evidence"
cp "$apk" "$evidence/app-debug.apk"

if [[ ! -s "$endpoint_health" ]]; then
  echo "Exact deployed /health evidence is missing" >&2
  exit 1
fi

capture_runtime() {
  adb logcat -d > "$evidence/logcat.txt" 2>&1 || true
  adb exec-out screencap -p > "$evidence/final.png" 2>/dev/null || true
  adb shell dumpsys activity activities > "$evidence/activities.txt" 2>&1 || true
}
trap capture_runtime EXIT

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
    sleep 2
  done
  echo "Timed out waiting for event: $event" >&2
  return 1
}

adb logcat -c
adb install -r "$apk" | tee "$evidence/adb-install.txt"
adb shell am force-stop io.github.upgradedev.mercury.wallboard
adb shell am start -W \
  -a android.intent.action.MAIN \
  -c android.intent.category.LEANBACK_LAUNCHER \
  -n io.github.upgradedev.mercury.wallboard/.MainActivity \
  | tee "$evidence/launcher.txt"
wait_for_event "journey:page_loaded:$endpoint"

# The page starts focused on Ask what changed. Move right to Stage, select, then
# move right to Confirm and select. These are the same key codes a TV remote emits.
adb shell input keyevent KEYCODE_DPAD_RIGHT
adb shell input keyevent KEYCODE_DPAD_CENTER
wait_for_event "journey:rollback_staged:"
adb shell input keyevent KEYCODE_DPAD_RIGHT
adb shell input keyevent KEYCODE_DPAD_CENTER
wait_for_event "journey:rollback_confirmed:RECORDED_ONLY:DPAD_RECORD_ONLY_DEMO"
# Publish the fixed, labelled responder handoff with the same D-pad path.
adb shell input keyevent KEYCODE_DPAD_CENTER
wait_for_event "journey:handoff_published:checkout-api-active:"

capture_runtime
trap - EXIT
device_model="$(adb shell getprop ro.product.model | tr -d '\r')"
os_version="Android $(adb shell getprop ro.build.version.release | tr -d '\r') / API $(adb shell getprop ro.build.version.sdk | tr -d '\r')"

python3 scripts/write_android_tv_runtime_receipt.py \
  --apk "$apk" \
  --logcat "$evidence/logcat.txt" \
  --screenshot "$evidence/final.png" \
  --endpoint "$endpoint" \
  --build-sha "${GITHUB_SHA:-local}" \
  --device-model "$device_model" \
  --os-version "$os_version" \
  --install-log "$evidence/adb-install.txt" \
  --launch-log "$evidence/launcher.txt" \
  --endpoint-health "$endpoint_health" \
  --workflow-run-url "${GITHUB_SERVER_URL:-https://github.com}/${GITHUB_REPOSITORY:-local}/actions/runs/${GITHUB_RUN_ID:-local}" \
  --artifact-name "mercury-android-tv-runtime-${GITHUB_SHA:-local}" \
  --built-by-command "./gradlew :app:assembleDebug -PmercuryCockpitUrl=$endpoint" \
  --output "$evidence/receipt.json"
