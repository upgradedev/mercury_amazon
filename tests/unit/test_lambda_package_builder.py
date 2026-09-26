import hashlib
import os
import zipfile

from scripts.build_lambda_package import (
    REPO_ROOT,
    RUNTIME_REQUIREMENTS,
    _write_deterministic_zip,
    package_manifest,
)


def test_lambda_package_manifest_includes_golden_path_evidence(tmp_path):
    required = set(package_manifest())
    assert "correlation_trial_summary.json" in required
    assert "src/infrastructure/fixtures/commit_stream_fixture.json" in required
    assert "docs/index.html" in required
    # The page's self-hosted fonts and their licences ship with it: the Fire TV app
    # loads the page from this Lambda and may never reach a font CDN.
    for font in sorted((REPO_ROOT / "docs").glob("*.woff2")):
        assert f"docs/{font.name}" in required, f"{font.name} would not ship in the Lambda zip"
    assert {"docs/OFL-Barlow.txt", "docs/OFL-BarlowCondensed.txt", "docs/OFL-JetBrainsMono.txt"} <= required
    assert all((REPO_ROOT / path).is_file() for path in required)
    assert all("==" in requirement for requirement in RUNTIME_REQUIREMENTS)

    staging = tmp_path / "staging"
    staging.mkdir()
    member = staging / "handler.py"
    member.write_text("answer = 42\n", encoding="utf-8")
    (staging / "bin").mkdir()
    (staging / "bin" / "launcher.exe").write_bytes(b"temporary path")
    dist_info = staging / "demo-1.0.dist-info"
    dist_info.mkdir()
    (dist_info / "RECORD").write_text("bin/launcher.exe,changes-per-build\n", encoding="utf-8")
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"
    _write_deterministic_zip(staging, first)
    os.utime(member, (2_000_000_000, 2_000_000_000))
    _write_deterministic_zip(staging, second)
    assert hashlib.sha256(first.read_bytes()).digest() == hashlib.sha256(second.read_bytes()).digest()
    with zipfile.ZipFile(first) as archive:
        assert archive.namelist() == ["handler.py"]
