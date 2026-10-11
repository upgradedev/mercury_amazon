#!/usr/bin/env python3
"""Talk to the Vega Virtual Device's emulator console, and measure PNG frames.

The VVD is a QEMU emulator with the same console as the Android emulator
(127.0.0.1:5554, auth token in ~/.emulator_console_auth_token). Its
``screenrecord screenshot`` reads the colour buffer that ``-gpu host`` posts,
which is the capture path github.com/finloop/vega-virtual-device-action
(MIT, docs/vvd-docker-screenshot-fix.md @a0f17767) found to be non-black on a
GPU-less host. Standard library only, so it runs on a bare runner.

    vvd_console.py screenshot <out.png>
    vvd_console.py record-start <out.webm> [seconds]
    vvd_console.py record-stop
    vvd_console.py send <console command>
    vvd_console.py nonblack <file.png>      prints WxH and the non-black fraction
"""
from __future__ import annotations

import glob
import os
import shutil
import socket
import struct
import sys
import tempfile
import time
import zlib

PORT = int(os.environ.get("VVD_CONSOLE_PORT", "5554"))
TOKEN_FILE = os.path.expanduser("~/.emulator_console_auth_token")


def _read_reply(sock: socket.socket, timeout: float) -> str:
    """Read until the console ends a reply with an OK or KO line."""
    sock.settimeout(timeout)
    data = b""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            chunk = sock.recv(65536)
        except socket.timeout:
            break
        if not chunk:
            break
        data += chunk
        lines = data.decode(errors="replace").replace("\r", "").split("\n")
        if any(line == "OK" or line.startswith("KO") for line in lines):
            break
    return data.decode(errors="replace").replace("\r", "")


def console(commands: list[str], timeout: float = 30.0) -> list[str]:
    with socket.create_connection(("127.0.0.1", PORT), timeout=10) as sock:
        _read_reply(sock, 5)  # banner
        replies = []
        if os.path.exists(TOKEN_FILE):
            token = open(TOKEN_FILE, encoding="utf-8").read().strip()
            sock.sendall(f"auth {token}\n".encode())
            replies.append(_read_reply(sock, 5))
        for command in commands:
            sock.sendall((command + "\n").encode())
            replies.append(_read_reply(sock, timeout))
        sock.sendall(b"quit\n")
        return replies


def nonblack(path: str) -> tuple[int, int, float]:
    """Width, height and the fraction of non-zero bytes in the decoded image data.

    Decodes the PNG's IDAT stream with zlib; no imaging library needed. A black
    frame scores about 0.000, a rendered UI about 0.01 or more.
    """
    data = open(path, "rb").read()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path} is not a PNG")
    offset, idat, width, height = 8, bytearray(), 0, 0
    while offset + 8 <= len(data):
        length = struct.unpack(">I", data[offset:offset + 4])[0]
        kind = data[offset + 4:offset + 8]
        if kind == b"IHDR":
            width, height = struct.unpack(">II", data[offset + 8:offset + 16])
        elif kind == b"IDAT":
            idat += data[offset + 8:offset + 8 + length]
        offset += 12 + length
        if kind == b"IEND":
            break
    raw = zlib.decompress(bytes(idat))
    fraction = (len(raw) - raw.count(0)) / len(raw) if raw else 0.0
    return width, height, fraction


def screenshot(out: str) -> int:
    workdir = tempfile.mkdtemp(prefix="vvdshot-")
    try:
        replies = console([f"screenrecord screenshot {workdir}"], timeout=30)
        shots: list[str] = []
        for _ in range(20):  # the file can land just after the console replies
            shots = sorted(glob.glob(os.path.join(workdir, "*.png")), key=os.path.getmtime)
            if shots and os.path.getsize(shots[-1]) > 0:
                break
            time.sleep(0.25)
        if not shots:
            print("no screenshot produced: " + " | ".join(r.strip()[-200:] for r in replies), file=sys.stderr)
            return 1
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        shutil.move(shots[-1], out)
        return 0
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    action = argv[1]
    if action == "screenshot" and len(argv) == 3:
        return screenshot(argv[2])
    if action == "record-start" and len(argv) in (3, 4):
        seconds = argv[3] if len(argv) == 4 else "180"
        reply = console([f"screenrecord start --time-limit {seconds} {os.path.abspath(argv[2])}"])[-1]
        print(reply.strip())
        return 0 if "KO" not in reply else 1
    if action == "record-stop" and len(argv) == 2:
        reply = console(["screenrecord stop"])[-1]
        print(reply.strip())
        return 0 if "KO" not in reply else 1
    if action == "send" and len(argv) >= 3:
        for reply in console([" ".join(argv[2:])]):
            print(reply.strip())
        return 0
    if action == "nonblack" and len(argv) == 3:
        try:
            width, height, fraction = nonblack(argv[2])
        except (OSError, ValueError, zlib.error) as error:
            print(f"unreadable: {error}")
            return 2
        print(f"{width}x{height} {fraction:.4f}")
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
