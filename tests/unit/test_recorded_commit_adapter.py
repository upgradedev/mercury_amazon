import json

from src.infrastructure.recorded_commit_adapter import RecordedCommitProvider


def test_recorded_provider_reads_bounded_real_recording(tmp_path):
    path = tmp_path / "commits.json"
    path.write_text(json.dumps({
        "recorded_at_head": "abc1234", "recorded_at_utc": "2026-09-01T00:00:00Z",
        "commits": [
            {"sha": "a", "message": "one", "author": "A", "committed_at": "2026-09-01T00:00:00Z"},
            {"sha": "b", "message": "two", "author": "B", "committed_at": "2026-08-31T00:00:00Z"},
        ],
    }), encoding="utf-8")
    provider = RecordedCommitProvider(path)
    assert [item["sha"] for item in provider.list_recent_commits(limit=1)] == ["a"]
    assert "abc1234" in provider.detail
    assert "not live commits or deployments" in provider.detail


def test_recorded_provider_refuses_missing_or_malformed_files(tmp_path):
    assert RecordedCommitProvider(tmp_path / "missing.json").list_recent_commits() == []
    broken = tmp_path / "broken.json"
    broken.write_text("[]", encoding="utf-8")
    assert RecordedCommitProvider(broken).list_recent_commits() == []
