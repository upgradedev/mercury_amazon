#!/usr/bin/env bash
# Boots the Vega Virtual Device (VVD) headless on a GPU-less GitHub runner so
# that screenshots show the screen instead of black.
#
# Technique from github.com/finloop/vega-virtual-device-action (MIT), files
# scripts/start-vvd.sh and docs/vvd-docker-screenshot-fix.md @a0f17767: the CLI
# starts the emulator in a software ANGLE mode that never posts a colour buffer,
# so every capture is black. So the CLI is used once, to create the instance and
# download the emulator binary, and the same emulator is then started again
# with -gpu host on Mesa llvmpipe and an Xvfb display. If that relaunch does not
# come up, the CLI boot is used as it is and the in-guest screenshot tool
# (vda-tools.html, gwsi-tool-screenshooter) is the capture path.
set -uo pipefail
source "$(dirname "$0")/lib.sh"

boot_timeout="${VVD_BOOT_TIMEOUT:-720}"
status vvd_boot not_ready

# QEMU binds a GNSS chardev on ::1; it aborts if IPv6 is off on loopback.
sudo sysctl -w net.ipv6.conf.all.disable_ipv6=0 net.ipv6.conf.default.disable_ipv6=0 \
  net.ipv6.conf.lo.disable_ipv6=0 > /dev/null 2>&1 || true

if ! xdpyinfo -display "$DISPLAY" > /dev/null 2>&1; then
  Xvfb "$DISPLAY" -screen 0 1920x1080x24 -nolisten tcp > "$OUT/logs/xvfb.log" 2>&1 &
  for _ in $(seq 1 40); do xdpyinfo -display "$DISPLAY" > /dev/null 2>&1 && break; sleep 0.5; done
fi
glxinfo -B > "$OUT/logs/glxinfo.txt" 2>&1 || true
grep -E 'OpenGL renderer|OpenGL version' "$OUT/logs/glxinfo.txt" || true
{ free -h; nproc; ls -la /dev/kvm; } > "$OUT/logs/host-before-boot.txt" 2>&1

# The emulator binary is vega-virtual-device (finloop's start-vvd.sh); the kernel
# truncates process names to 15 characters.
emulator_pid() { { pgrep -x vega-virtual-de || pgrep -x qemu-system-x86; } 2>/dev/null | head -1 || true; }
console_up() { ss -ltn 2>/dev/null | grep -q ':5554 '; }

wait_ready() {  # wait_ready <seconds>: until a capture is not black
  local deadline=$((SECONDS + $1)) probe="$OUT/frames/boot-probe.png"
  timeout 180 vda wait-for-device >> "$OUT/logs/vvd-boot.log" 2>&1 || true
  while (( SECONDS < deadline )); do
    if python3 "$CI_DIR/vvd_console.py" screenshot "$probe" >> "$OUT/logs/vvd-boot.log" 2>&1 \
      && nonblack_ok "$probe" 0.004; then
      status vvd_capture console
      return 0
    fi
    if timeout 30 vda shell gwsi-tool-screenshooter /tmp/boot-probe.png >> "$OUT/logs/vvd-boot.log" 2>&1 \
      && timeout 30 vda pull /tmp/boot-probe.png "$probe.guest.png" >> "$OUT/logs/vvd-boot.log" 2>&1 \
      && nonblack_ok "$probe.guest.png" 0.004; then
      status vvd_capture guest
      return 0
    fi
    if [ -z "$(emulator_pid)" ]; then
      echo "emulator process is gone" >> "$OUT/logs/vvd-boot.log"
      return 1
    fi
    sleep 10
  done
  return 1
}

mark "VVD phase 1: the CLI creates the instance"
started=$SECONDS
vega virtual-device start --gui=false --gl-accel=true > "$OUT/logs/vvd-cli-phase1.log" 2>&1 &
cli_pid=$!
pid=""
for i in $(seq 1 900); do
  pid="$(emulator_pid)"
  [ -n "$pid" ] && break
  if ! kill -0 "$cli_pid" 2>/dev/null; then
    sleep 5
    pid="$(emulator_pid)"
    [ -n "$pid" ] && break
    echo "the CLI exited before an emulator process appeared" >> "$OUT/logs/vvd-boot.log"
    break
  fi
  if (( i % 60 == 0 )); then
    ps -eo pid,comm,args | grep -iE 'vega|qemu|emulat' | grep -v grep | cut -c1-200 >> "$OUT/logs/vvd-boot.log" || true
  fi
  sleep 1
done
if [ -z "$pid" ]; then
  echo "::error::the VVD emulator never started"
  tail -60 "$OUT/logs/vvd-cli-phase1.log"
  ps -eo pid,comm,args | grep -iE 'vega|qemu|emulat' | grep -v grep | cut -c1-200 || true
  status vvd_boot phase1_failed
  exit 1
fi
echo "emulator up after $((SECONDS - started)) s (pid $pid)"
mapfile -d '' -t argv < "/proc/$pid/cmdline"
printf '%s\n' "${argv[@]}" > "$OUT/logs/vvd-emulator-argv.txt"
emulator_bin="${argv[0]}"
agent_dir="$(cd "$(dirname "$emulator_bin")/../.." && pwd)"
ls -la "$agent_dir" "$agent_dir/lib64" > "$OUT/logs/vvd-agent-dir.txt" 2>&1 || true

mark "VVD phase 2: relaunch with -gpu host on llvmpipe"
pkill -9 virtualdevice 2>/dev/null || true
pkill -9 -x node 2>/dev/null || true
pkill -9 vega-virtual-de 2>/dev/null || true
pkill -9 -x qemu-system-x86 2>/dev/null || true
sleep 3
rm -f /tmp/qmp-socket-*.sock
(
  export LD_LIBRARY_PATH="$agent_dir/lib64/libstdc++:$agent_dir/lib64/gles_swiftshader:$agent_dir/lib64"
  setsid "$emulator_bin" -gpu host "${argv[@]:1}" > "$OUT/logs/vvd-emulator.log" 2>&1 < /dev/null &
)
mode=gpu_host
deadline=$((SECONDS + 180))
until console_up; do
  if [ -z "$(emulator_pid)" ] || (( SECONDS >= deadline )); then
    echo "::warning::the -gpu host relaunch did not open the console; falling back to the CLI boot"
    grep -iE '::1|abnormal|error while load|gpu mode|fatal' "$OUT/logs/vvd-emulator.log" | head -20 || true
    pkill -9 vega-virtual-de 2>/dev/null || true
    pkill -9 -x qemu-system-x86 2>/dev/null || true
    sleep 3
    vega virtual-device start --no-gui --timeout "$boot_timeout" > "$OUT/logs/vvd-cli-fallback.log" 2>&1 &
    mode=cli_default
    break
  fi
  sleep 3
done
status vvd_gpu_mode "$mode"
grep -iE 'gpu mode|renderer|library_mode' "$OUT/logs/vvd-emulator.log" | head -10 || true

mark "wait for the VVD home screen"
if wait_ready "$boot_timeout"; then
  status vvd_boot ready
  echo "VVD ready after $((SECONDS - started)) s ($mode, capture $(status_of vvd_capture))"
else
  status vvd_boot not_ready
  echo "::error::the VVD did not show a non-black screen within ${boot_timeout}s"
  tail -40 "$OUT/logs/vvd-emulator.log" 2>/dev/null || true
  exit 1
fi
shot 00-vvd-ready

vega device list > "$OUT/logs/device-list.txt" 2>&1 || true
vega virtual-device status > "$OUT/logs/vvd-status.txt" 2>&1 || true
vda devices -l > "$OUT/logs/vda-devices.txt" 2>&1 || true
cat "$OUT/logs/device-list.txt"
status device_name "$(device_name)"

# inputd-cli needs developer mode for button_press (inputdcli.html); without it
# the help lists only get_camera_cover_open_close, get_mic_state and
# get_screen_size. Enabling it reboots the device.
timeout 30 vda shell inputd-cli --help > "$OUT/logs/inputd-help.txt" 2>&1 || true
if grep -q button_press "$OUT/logs/inputd-help.txt"; then
  status vvd_developer_mode already_on
else
  mark "enable developer mode (the VVD reboots)"
  timeout 60 vda shell vsm developer-mode enable > "$OUT/logs/developer-mode.log" 2>&1 || true
  sleep 45
  status vvd_developer_mode still_limited
  deadline=$((SECONDS + 420))
  while (( SECONDS < deadline )); do
    timeout 60 vda wait-for-device >> "$OUT/logs/developer-mode.log" 2>&1 || true
    if timeout 30 vda shell inputd-cli --help > "$OUT/logs/inputd-help-after.txt" 2>&1 \
      && grep -q button_press "$OUT/logs/inputd-help-after.txt"; then
      status vvd_developer_mode enabled
      break
    fi
    sleep 10
  done
  wait_ready 300 || echo "::warning::no non-black screen after the developer mode reboot"
  shot 00-vvd-developer-mode
fi
timeout 30 vda shell inputd-cli get_screen_size > "$OUT/logs/inputd-screen-size.txt" 2>&1 || true
{ free -h; df -h /; } > "$OUT/logs/host-after-boot.txt" 2>&1
echo "developer mode: $(status_of vvd_developer_mode)"
