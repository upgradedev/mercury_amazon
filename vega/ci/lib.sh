# Shared helpers for the Vega CI scripts. Source this file; do not run it.
#
# Every script writes into $OUT: logs/, frames/ (PNG screenshots), vpkg/,
# status/ (one small file per fact, read by provenance.py) and timeline.tsv.

: "${OUT:?OUT must name the evidence directory}"
mkdir -p "$OUT/logs" "$OUT/frames" "$OUT/vpkg" "$OUT/status"

# The SDK installer writes ~/vega/env, which puts the CLI on PATH and exports
# KEPLER_SDK_PATH. Later steps start new shells, so each script sources it.
if [ -f "$HOME/vega/env" ]; then
  # shellcheck disable=SC1091
  source "$HOME/vega/env" || true
fi
export PATH="$HOME/vega/bin:$PATH"

# Software GL for the emulator's -gpu host path (see vvd_boot.sh).
export DISPLAY="${DISPLAY:-:99}"
export LIBGL_ALWAYS_SOFTWARE=1 GALLIUM_DRIVER=llvmpipe __GLX_VENDOR_LIBRARY_NAME=mesa MESA_LOADER_DRIVER_OVERRIDE=llvmpipe

CI_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_ID="${APP_ID:-com.upgradedev.mercury.main}"
CONTROL_APP_ID="${CONTROL_APP_ID:-com.upgradedev.hellovega.main}"

status() {  # status <name> <value>
  printf '%s\n' "$2" > "$OUT/status/$1"
}

status_of() {  # status_of <name>: the recorded value, or empty
  cat "$OUT/status/$1" 2>/dev/null || true
}

# vda is the Vega device bridge. Calling the binary directly avoids starting
# the Node-based CLI for every key press; `vega exec vda` is the fallback.
VDA_BIN="$(find "$HOME/vega" -type f -name vda -perm -u+x 2>/dev/null | head -1 || true)"
vda() {
  if [ -n "$VDA_BIN" ]; then "$VDA_BIN" "$@"; else vega exec vda "$@"; fi
}

device_name() {  # the CLI's name for the booted VVD; VirtualDevice per run-apps.html
  local name
  name="$(vega device list 2>/dev/null | awk -F' *: *' '/ : / {print $1; exit}')"
  printf '%s' "${name:-VirtualDevice}"
}

T0_FILE="$OUT/status/t0"
[ -f "$T0_FILE" ] || date +%s.%N > "$T0_FILE"
mark() {  # mark <step>: seconds since the first script started, then the step
  local now t0
  now="$(date +%s.%N)"
  t0="$(cat "$T0_FILE")"
  [ -f "$OUT/timeline.tsv" ] || printf 'seconds\tstep\n' > "$OUT/timeline.tsv"
  printf '%s\t%s\n' "$(awk -v a="$now" -v b="$t0" 'BEGIN { printf "%.2f", a - b }')" "$1" >> "$OUT/timeline.tsv"
  echo "[$(date -u +%H:%M:%S)] $1"
}

# shot <name>: one frame through the emulator console (the -gpu host readback),
# and one through the in-guest screenshot tool, each scored for how much of it
# is not black. frames/index.tsv keeps every score so a reader can tell a
# rendered screen from a black capture without opening the image.
shot() {
  local name="$1" png guest score
  png="$OUT/frames/${name}.png"
  guest="$OUT/frames/${name}.guest.png"
  [ -f "$OUT/frames/index.tsv" ] || printf 'frame\tmethod\tbytes\tsize_and_nonblack\n' > "$OUT/frames/index.tsv"
  if python3 "$CI_DIR/vvd_console.py" screenshot "$png" >> "$OUT/logs/screenshots.log" 2>&1; then
    score="$(python3 "$CI_DIR/vvd_console.py" nonblack "$png")"
    printf '%s\tconsole\t%s\t%s\n' "$name" "$(stat -c%s "$png")" "$score" >> "$OUT/frames/index.tsv"
  fi
  if [ "${GUEST_SHOTS:-1}" = 1 ]; then
    if timeout 30 vda shell gwsi-tool-screenshooter /tmp/mercury-shot.png >> "$OUT/logs/screenshots.log" 2>&1 \
      && timeout 30 vda pull /tmp/mercury-shot.png "$guest" >> "$OUT/logs/screenshots.log" 2>&1 \
      && [ -s "$guest" ]; then
      score="$(python3 "$CI_DIR/vvd_console.py" nonblack "$guest")"
      printf '%s\tguest\t%s\t%s\n' "$name" "$(stat -c%s "$guest")" "$score" >> "$OUT/frames/index.tsv"
    else
      rm -f "$guest"
    fi
  fi
}

nonblack_ok() {  # nonblack_ok <png> [min]: true when the frame rendered something
  local min="${2:-0.004}" fraction
  [ -s "$1" ] || return 1
  fraction="$(python3 "$CI_DIR/vvd_console.py" nonblack "$1" | awk '{print $2}')"
  awk -v f="${fraction:-0}" -v m="$min" 'BEGIN { exit !(f > m) }'
}

key() {  # key <KEY_*>: one short press through the input daemon
  mark "key $1"
  timeout 30 vda shell inputd-cli button_press "$1" short >> "$OUT/logs/inputd.log" 2>&1 \
    || echo "inputd-cli $1 failed" >> "$OUT/logs/inputd.log"
}

wait_log() {  # wait_log <fixed string> <seconds> [shot prefix]: poll the device log
  local needle="$1" seconds="$2" prefix="${3:-}" deadline i=0
  deadline=$((SECONDS + seconds))
  while (( SECONDS < deadline )); do
    if grep -Fq "$needle" "$OUT/logs/device.log" 2>/dev/null; then
      return 0
    fi
    if [ -n "$prefix" ] && (( i % 3 == 0 )); then
      shot "$(printf '%s-wait%02d' "$prefix" "$i")"
    fi
    i=$((i + 1))
    sleep 2
  done
  return 1
}
