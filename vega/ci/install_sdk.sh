#!/usr/bin/env bash
# Installs the Vega SDK, CLI and Vega Virtual Device without prompts.
#
# get_vvm.sh is Amazon's installer (install-vega-sdk.html). NONINTERACTIVE=true
# makes it take its defaults instead of prompting, and VEGA_SDK_VERSION pins the
# SDK when set (continuous-integration.html). stdin is /dev/null because the
# installer's `vega sdk config setup` call has no non-interactive flag.
set -uo pipefail
source "$(dirname "$0")/lib.sh"

# The SDK and its tools collect telemetry unless ${HOME}/vega/telemetry/config.json
# sets optIn to false (https://developer.amazon.com/docs/vega/0.24/telemetry.html).
# CI opts out before the first tool runs, and again after the install.
opt_out() {
  local config="$HOME/vega/telemetry/config.json"
  mkdir -p "$(dirname "$config")"
  if [ -s "$config" ] && jq -e . "$config" > /dev/null 2>&1; then
    jq '.optIn = false' "$config" > "$config.tmp" && mv "$config.tmp" "$config"
  else
    printf '{\n  "optIn": false\n}\n' > "$config"
  fi
  cp "$config" "$OUT/logs/telemetry-config.json"
}
opt_out

installer="${RUNNER_TEMP:-/tmp}/get_vvm.sh"
ok=""
for attempt in 1 2 3; do
  log="$OUT/logs/sdk-install-$attempt.log"
  if curl -fsSL --retry 3 --retry-delay 5 https://sdk-installer.vega.labcollab.net/get_vvm.sh -o "$installer"; then
    sha256sum "$installer" | tee "$OUT/logs/get_vvm.sha256"
    if [ -n "${GET_VVM_SHA256:-}" ] && [ "$(sha256sum "$installer" | cut -d' ' -f1)" != "$GET_VVM_SHA256" ]; then
      status sdk_install installer_changed
      echo "::error::get_vvm.sh differs from the reviewed installer (GET_VVM_SHA256); review it, then update the pin"
      exit 1
    fi
    started=$SECONDS
    if NONINTERACTIVE=true timeout 1200 bash "$installer" < /dev/null > "$log" 2>&1; then
      echo "installer finished in $((SECONDS - started)) s" | tee -a "$log"
      ok=1
      break
    fi
  fi
  echo "::warning::Vega SDK install attempt $attempt failed"
  tail -40 "$log" 2>/dev/null || true
  sleep $((attempt * 15))
done
if [ -z "$ok" ]; then
  status sdk_install failed
  echo "::error::Vega SDK install failed after 3 attempts"
  exit 1
fi

# shellcheck disable=SC1091
source "$HOME/vega/env" || true
export PATH="$HOME/vega/bin:$PATH"
echo "$HOME/vega/bin" >> "${GITHUB_PATH:-/dev/null}"
opt_out

vega -v 2>&1 | tee "$OUT/logs/vega-version.txt"
vega sdk list-installed > "$OUT/logs/sdk-list-installed.txt" 2>&1 || true
vega sdk list-remote --json > "$OUT/logs/sdk-list-remote.json" 2>&1 || true
node -v > "$OUT/logs/node-version.txt" 2>&1 || true
du -sh "$HOME/vega" 2>&1 | tee "$OUT/logs/sdk-size.txt"
df -h / | tail -1 | tee -a "$OUT/logs/sdk-size.txt"
status sdk_install ok
status sdk_version "$(sed -n 's/^Active SDK Version: *//p' "$OUT/logs/vega-version.txt" | head -1)"
