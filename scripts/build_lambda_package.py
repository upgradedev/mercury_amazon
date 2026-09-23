"""Build the reproducible Linux Lambda zip for Mercury.

The source tree alone is insufficient: the public offline journey also needs the
recorded commit stream and the published trial summary.  This builder makes those
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
    Path("src/infrastructure/fixtures/commit_stream_fixture.json"),
    Path("docs/index.html"),
    Path("docs/firetv_nav.js"),
    Path("docs/webmcp_bridge.js"),
    Path("docs/manifest.json"),
)


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


def build(output: Path) -> Path:
    staging = output.parent / "mercury_lambda_staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    subprocess.run([
        sys.executable, "-m", "pip", "install",
        "fastapi>=0.111.0", "pydantic>=2.7.0", "httpx>=0.27.0",
        "--target", str(staging), "--platform", "manylinux2014_x86_64",
        "--implementation", "cp", "--python-version", "3.11",
        "--only-binary=:all:", "--upgrade",
    ], check=True)
    _copy_runtime(staging)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(staging.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                archive.write(path, path.relative_to(staging).as_posix())
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
