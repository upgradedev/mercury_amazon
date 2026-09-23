from scripts.build_lambda_package import REPO_ROOT, package_manifest


def test_lambda_package_manifest_includes_golden_path_evidence():
    required = set(package_manifest())
    assert "correlation_trial_summary.json" in required
    assert "src/infrastructure/fixtures/commit_stream_fixture.json" in required
    assert "docs/index.html" in required
    assert all((REPO_ROOT / path).is_file() for path in required)
