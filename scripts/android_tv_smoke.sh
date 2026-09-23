#!/usr/bin/env bash
set -euo pipefail

endpoint="https://leol25sezuvokpankox5cvjopm0gtvfa.lambda-url.eu-west-1.on.aws/"
apk="app/build/outputs/apk/debug/app-debug.apk"
evidence="build/android-tv-evidence"
mkdir -p "$evidence"

adb logcat -c
adb install -r "$apk" | tee "$evidence/adb-install.txt"
adb shell am force-stop com.amazon.mercury.wallboard
adb shell monkey -p com.amazon.mercury.wallboard -c android.intent.category.LEANBACK_LAUNCHER 1 \
  | tee "$evidence/launcher.txt"
sleep 18

# The page starts focused on Ask what changed. Move right to Stage, select, then
# move right to Confirm and select. These are the same key codes a TV remote emits.
adb shell input keyevent KEYCODE_DPAD_RIGHT
adb shell input keyevent KEYCODE_DPAD_CENTER
sleep 5
adb shell input keyevent KEYCODE_DPAD_RIGHT
adb shell input keyevent KEYCODE_DPAD_CENTER
sleep 5
# Publish the fixed, labelled responder handoff with the same D-pad path.
adb shell input keyevent KEYCODE_DPAD_CENTER
sleep 5

adb logcat -d > "$evidence/logcat.txt"
adb exec-out screencap -p > "$evidence/final.png"
device_model="$(adb shell getprop ro.product.model | tr -d '\r')"
os_version="Android $(adb shell getprop ro.build.version.release | tr -d '\r') / API $(adb shell getprop ro.build.version.sdk | tr -d '\r')"

python scripts/write_android_tv_runtime_receipt.py \
  --apk "$apk" \
  --logcat "$evidence/logcat.txt" \
  --screenshot "$evidence/final.png" \
  --endpoint "$endpoint" \
  --build-sha "${GITHUB_SHA:-local}" \
  --device-model "$device_model" \
  --os-version "$os_version" \
  --install-log "$evidence/adb-install.txt" \
  --launch-log "$evidence/launcher.txt" \
  --workflow-run-url "${GITHUB_SERVER_URL:-https://github.com}/${GITHUB_REPOSITORY:-local}/actions/runs/${GITHUB_RUN_ID:-local}" \
  --artifact-name "mercury-android-tv-runtime-${GITHUB_SHA:-local}" \
  --output "$evidence/receipt.json"

cp "$apk" "$evidence/app-debug.apk"
