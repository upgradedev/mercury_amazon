"""Build the reproducible Linux Lambda zip for Mercury.

The source tree alone is insufficient: the public offline journey also needs the
display-only deploy feed and the published trial summaries; the recorded commit stream
ships beside them as the input those summaries were scored on.  This builder makes those
files explicit and installs Linux wheels even when it is invoked from Windows.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNTIME_FILES = (
    Path("correlation_trial_summary.json"),
    # The held-out figure the answer carries beside a named commit (trial_summary.py).
    Path("attribution_holdout_summary.json"),
    Path("src/infrastructure/fixtures/commit_stream_fixture.json"),
    Path("src/infrastructure/fixtures/deploy_feed_fixture.json"),
    Path("docs/index.html"),
    Path("docs/firetv_nav.js"),
    Path("docs/webmcp_bridge.js"),
    Path("docs/manifest.json"),
    # The board's self-hosted typefaces and their SIL OFL licences. The Fire TV app
    # loads the page from this Lambda, and a television may never reach a font CDN.
    Path("docs/barlow-latin-400.woff2"),
    Path("docs/barlow-latin-600.woff2"),
    Path("docs/barlow-condensed-latin-500.woff2"),
    Path("docs/barlow-condensed-latin-600.woff2"),
    Path("docs/barlow-condensed-latin-700.woff2"),
    Path("docs/jetbrains-mono-latin.woff2"),
    Path("docs/OFL-Barlow.txt"),
    Path("docs/OFL-BarlowCondensed.txt"),
    Path("docs/OFL-JetBrainsMono.txt"),
)
RUNTIME_REQUIREMENTS = (
    "fastapi==0.141.1",
    "starlette==1.7.0",
    "pydantic==2.13.5",
    "pydantic-core==2.46.5",
    "annotated-types==0.8.0",
    "annotated-doc==0.0.5",
    "typing-extensions==4.16.0",
    "typing-inspection==0.4.4",
    "httpx==0.28.1",
    "httpcore==1.0.9",
    "h11==0.16.0",
    "anyio==4.15.1",
    "idna==3.20",
    "certifi==2026.7.22",
)
ZIP_DATE_TIME = (1980, 1, 1, 0, 0, 0)


def package_manifest() -> tuple[str, ...]:
    """Files whose absence would break or mislabel the public golden path."""
    return tuple(path.as_posix() for path in RUNTIME_FILES)


def _copy_runtime(staging: Path) -> None:
    shutil.copytree(REPO_ROOT / "src", staging / "src", dirs_exist_ok=True)
    (staging / "docs").mkdir(parents=True, exist_ok=True)
    for relative in RUNTIME_FILES:
        source = REPO_ROOT / relative
        if not source.is_file():
            raise FileNotFoundError(f"required Lambda runtime file is absent: {relative}")
        target = staging / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def _write_deterministic_zip(staging: Path, output: Path) -> None:
    """Write stable member order, timestamps and permissions into the archive."""
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(staging.rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            relative = path.relative_to(staging)
            # pip's Windows console launchers embed the temporary --target path,
            # and their RECORD hashes therefore change on every build. Lambda
            # imports the libraries directly, so neither artifact is runtime data.
            if relative.parts[0] == "bin" or (
                relative.name == "RECORD" and relative.parent.name.endswith(".dist-info")
            ):
                continue
            info = zipfile.ZipInfo(relative.as_posix(), ZIP_DATE_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(
                info,
                path.read_bytes(),
                compress_type=zipfile.ZIP_DEFLATED,
                compresslevel=9,
            )


def build(output: Path) -> Path:
    staging = output.parent / "mercury_lambda_staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    subprocess.run([
        sys.executable, "-m", "pip", "install",
        *RUNTIME_REQUIREMENTS,
        "--target", str(staging), "--platform", "manylinux2014_x86_64",
        "--implementation", "cp", "--python-version", "3.11",
        "--only-binary=:all:", "--upgrade",
    ], check=True)
    _copy_runtime(staging)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()
    _write_deterministic_zip(staging, output)
    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
        missing = sorted(set(package_manifest()) - names)
        if missing:
            raise RuntimeError(f"Lambda package omitted required files: {missing}")
        if any(name.endswith(".pyd") for name in names):
            raise RuntimeError("Lambda package contains a Windows extension module")
        if not any(name.startswith("pydantic_core/") and name.endswith("linux-gnu.so") for name in names):
            raise RuntimeError("Lambda package lacks the Linux pydantic_core extension")
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "dist" / "mercury_lambda.zip")
    parser.add_argument("--print-manifest", action="store_true")
    args = parser.parse_args()
    if args.print_manifest:
        print("\n".join(package_manifest()))
        return 0
    result = build(args.output.resolve())
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
