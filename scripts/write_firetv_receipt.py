#!/usr/bin/env python3
"""Write ``firetv_build_receipt.json`` from a real build and a real launch, or refuse.

Readiness gate J4 in ``ci/readiness.py`` decides whether the sponsor product is
load-bearing. It wants a receipt recording three things that cannot be produced by
running code in a checkout: a gradle build that exited 0, the APK it produced, and a
launch watched on a Fire TV device. Until 2026-09-08 that file was to be written by hand.
This script writes it instead, so the receipt's shape cannot drift from the gate's, and
so it cannot be written without the evidence:

* the APK named by ``--apk`` has to exist inside the checkout and has to be an APK,
  which is to say a zip archive whose first bytes are a zip header and which carries
  an ``AndroidManifest.xml``; the sha256 in the receipt is computed from that file
  here and is never accepted as typed input;
* ``--gradle-exit-code`` has to be 0, because a failed build has no APK to record;
* ``--adb-install-exit-code`` has to be 0, and ``--device-model``, ``--os-version`` and
  ``--observed`` have to be non-empty, because a launch nobody watched is not a launch.

Any of those missing makes it exit 2 and write nothing. The receipt it does write is
run through the gate's own predicate before it touches disk, so a receipt this script
writes is one the gate accepts.

The device is a physical one. No Fire TV emulator exists, and Amazon's Vega Virtual
Device runs Vega apps rather than this APK and its SDK lists only macOS and Ubuntu as
supported, so the launch in the receipt has to come from hardware. That is the owner action this script
is the last step of: build in CI or locally, ``adb install`` on a Fire TV, launch,
watch, then run this with what was seen.

Usage::

    python scripts/write_firetv_receipt.py \\
        --gradle-exit-code 0 \\
        --apk app/build/outputs/apk/debug/app-debug.apk \\
        --built-by-command "./gradlew :app:assembleDebug" \\
        --device-model "Fire TV Stick 4K Max (2nd gen)" \\
        --os-version "Fire OS 8.1.0.3" \\
        --adb-install-exit-code 0 \\
        --observed "The wallboard rendered; the D-pad moved the focus ring across the tiles." \\
        [--adb-launch-output launch.log] [--launched-at-utc 2026-09-08T10:00:00Z] [--dry-run]

``--dry-run`` prints the receipt it would write and writes nothing. The APK itself is
gitignored, so a clone receives the receipt and its digest but not the binary; the CI
artifact from ``.github/workflows/android.yml`` is where a reader downloads the file
the digest identifies.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "ci") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "ci"))

import readiness  # noqa: E402

RECEIPT_SCHEMA = "mercury.firetv_build_receipt/1"
ZIP_MAGIC = b"PK\x03\x04"
#: The one entry every Android package carries. A zip archive without it is a zip
#: archive, not an APK, however it is named.
APK_MANIFEST_ENTRY = "AndroidManifest.xml"
REFUSED = 2


class ReceiptRefused(ValueError):
    """Raised when the evidence is not there. The message says which piece."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_apk(apk: Path, repo_root: Path) -> Path:
    """Return the APK's path relative to the checkout, or refuse.

    Five refusals, each of which is a way the old hand-written receipt could have lied:
    the file is not there, it is outside the checkout the gate reads, it is empty, it is
    not a zip archive, or it is a zip archive with no ``AndroidManifest.xml`` inside and
    therefore not an APK.
    """
    resolved = apk.resolve()
    if not resolved.is_file():
        raise ReceiptRefused(f"no APK at {apk}: nothing was built, so there is nothing to record")
    try:
        relative = resolved.relative_to(repo_root.resolve())
    except ValueError as exc:
        raise ReceiptRefused(
            f"{apk} is outside the checkout at {repo_root}; gate J4 opens apk_path relative "
            "to the repository root, so the APK has to live inside it"
        ) from exc
    with resolved.open("rb") as handle:
        head = handle.read(len(ZIP_MAGIC))
    if len(head) < len(ZIP_MAGIC):
        raise ReceiptRefused(f"{apk} is empty; an empty file is not an APK")
    if head != ZIP_MAGIC:
        raise ReceiptRefused(
            f"{apk} does not start with a zip header; an APK is a zip archive and this file is not one"
        )
    try:
        with zipfile.ZipFile(resolved) as archive:
            entries = set(archive.namelist())
    except zipfile.BadZipFile as exc:
        raise ReceiptRefused(f"{apk} starts like a zip archive but cannot be read as one: {exc}") from exc
    if APK_MANIFEST_ENTRY not in entries:
        raise ReceiptRefused(
            f"{apk} is a zip archive with no {APK_MANIFEST_ENTRY} inside; every APK carries one, "
            "so this file is not an APK"
        )
    return relative


def build_receipt(
    *,
    gradle_exit_code: int,
    apk: Path,
    built_by_command: str,
    device_model: str,
    os_version: str,
    adb_install_exit_code: int,
    observed: str,
    launched_at_utc: str | None = None,
    adb_launch_output: str | None = None,
    repo_root: Path = REPO_ROOT,
) -> dict[str, object]:
    """Assemble the receipt, refusing on any missing piece of evidence."""
    if gradle_exit_code != 0:
        raise ReceiptRefused(
            f"gradle exited {gradle_exit_code}; a failed build produced no APK to record"
        )
    relative_apk = check_apk(apk, repo_root)
    if adb_install_exit_code != 0:
        raise ReceiptRefused(
            f"adb install exited {adb_install_exit_code}; the APK never installed, so nothing ran"
        )
    for name, value in (
        ("--device-model", device_model),
        ("--os-version", os_version),
        ("--observed", observed),
        ("--built-by-command", built_by_command),
    ):
        if not value or not value.strip():
            raise ReceiptRefused(f"{name} is empty; a launch nobody can describe is not a launch")
    if launched_at_utc:
        try:
            datetime.fromisoformat(launched_at_utc.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ReceiptRefused(
                f"--launched-at-utc {launched_at_utc!r} is not an ISO-8601 timestamp"
            ) from exc
    else:
        launched_at_utc = _utc_now()

    device_run: dict[str, object] = {
        "device_model": device_model.strip(),
        "fire_os_or_android_version": os_version.strip(),
        "adb_install_exit_code": adb_install_exit_code,
        "launched_at_utc": launched_at_utc,
        "observed": observed.strip(),
    }
    if adb_launch_output:
        device_run["adb_launch_output"] = adb_launch_output

    receipt: dict[str, object] = {
        "schema": RECEIPT_SCHEMA,
        "note": (
            "Written by python scripts/write_firetv_receipt.py from a gradle build that exited 0, "
            "an APK the script opened and hashed, and a launch on a Fire TV device that a person "
            "watched. The APK is not committed (it is gitignored); apk_sha256 identifies the CI "
            "artifact. Gate J4 in ci/readiness.py reads this file and opens apk_path."
        ),
        "recorded_by_command": "python scripts/write_firetv_receipt.py",
        "recorded_at_utc": _utc_now(),
        "built_by_command": built_by_command.strip(),
        "gradle_exit_code": gradle_exit_code,
        "apk_path": relative_apk.as_posix(),
        "apk_sha256": _sha256(repo_root / relative_apk),
        "device_run": device_run,
    }

    # The gate's own predicate, before anything touches disk. If this refuses, the
    # receipt would have failed J4 anyway, and writing it would only look like evidence.
    passed, message = readiness.evaluate_firetv_gate(
        ["fire tv"], "LEANBACK_LAUNCHER", receipt,
        lambda path: (repo_root / path).is_file(),
    )
    if not passed:
        raise ReceiptRefused(f"the receipt would not pass gate J4: {message}")
    return receipt


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--gradle-exit-code", type=int, required=True)
    parser.add_argument("--apk", type=Path, required=True, help="path to the built APK")
    parser.add_argument("--built-by-command", default="./gradlew :app:assembleDebug")
    parser.add_argument("--device-model", required=True)
    parser.add_argument("--os-version", required=True, help="the Fire OS version the device reported")
    parser.add_argument("--adb-install-exit-code", type=int, required=True)
    parser.add_argument("--observed", required=True, help="what was on the screen, in words")
    parser.add_argument("--adb-launch-output", type=Path, default=None,
                        help="a file holding the verbatim output of adb shell am start")
    parser.add_argument("--launched-at-utc", default=None)
    parser.add_argument("--out", type=Path, default=None,
                        help=f"where to write; default <repo-root>/{readiness.FIRETV_BUILD_RECEIPT}")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT,
                        help="the checkout the APK path is resolved against")
    parser.add_argument("--dry-run", action="store_true", help="print the receipt, write nothing")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    launch_output = None
    if args.adb_launch_output is not None:
        try:
            launch_output = args.adb_launch_output.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            sys.stderr.write(f"refused: cannot read --adb-launch-output: {exc}\n")
            return REFUSED
    try:
        receipt = build_receipt(
            gradle_exit_code=args.gradle_exit_code,
            apk=args.apk if args.apk.is_absolute() else args.repo_root / args.apk,
            built_by_command=args.built_by_command,
            device_model=args.device_model,
            os_version=args.os_version,
            adb_install_exit_code=args.adb_install_exit_code,
            observed=args.observed,
            launched_at_utc=args.launched_at_utc,
            adb_launch_output=launch_output,
            repo_root=args.repo_root,
        )
    except ReceiptRefused as exc:
        sys.stderr.write(f"refused: {exc}\nNothing was written.\n")
        return REFUSED

    rendered = json.dumps(receipt, indent=2) + "\n"
    out = args.out or (args.repo_root / readiness.FIRETV_BUILD_RECEIPT)
    if args.dry_run:
        print(rendered, end="")
        print(f"dry run: would write {out}; nothing written", file=sys.stderr)
        return 0

    out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    print(
        f"wrote {out}. Next: commit it, then change "
        "tests/unit/test_readiness_gates.py::test_the_gate_fails_in_this_repository_because_no_apk_exists "
        "to assert this receipt's contents, and run python ci/readiness.py to watch J4 pass.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    raise SystemExit(main())
