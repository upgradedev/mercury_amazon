from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

import pytest
import yaml

from scripts import terraform_cycle
from scripts.terraform_cycle import run_cycle

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def test_public_function_url_cannot_read_live_account_telemetry():
    """Anonymous demo traffic must stay fixture-only even with Lambda credentials."""
    terraform = (REPO_ROOT / "infra" / "main.tf").read_text(encoding="utf-8")
    assert 'authorization_type = "NONE"' in terraform
    assert 'MERCURY_OFFLINE = "1"' in terraform
    assert '"ce:' not in terraform
    assert '"cloudwatch:' not in terraform
    assert 'var.environment == "prod" || can(regex("^ci-[0-9]+-[0-9]+$"' in terraform
    assert 'can(regex("^[0-9a-f]{40}$", var.source_revision))' in terraform


def test_external_workflow_actions_are_pinned_to_commits():
    """Floating action tags can change code without changing this repository."""
    uses_pattern = re.compile(r"^\s*uses:\s*([^\s#]+)", re.MULTILINE)
    for workflow_path in (REPO_ROOT / ".github" / "workflows").glob("*.yml"):
        workflow = workflow_path.read_text(encoding="utf-8")
        for action in uses_pattern.findall(workflow):
            if action.startswith("./"):
                continue
            _repository, separator, revision = action.rpartition("@")
            assert separator and re.fullmatch(r"[0-9a-f]{40}", revision), (
                f"{workflow_path.name} has an unpinned external action: {action}"
            )


def test_cycle_workflow_reserves_time_for_fail_safe_teardown():
    """A timed-out primary cycle must leave the runner time to destroy its stack."""
    workflow = yaml.safe_load(
        (REPO_ROOT / ".github" / "workflows" / "terraform-cycle.yml").read_text(encoding="utf-8")
    )
    job = workflow["jobs"]["deploy-probe-destroy"]
    assert job["if"] == "${{ always() }}"
    steps = {step.get("name"): step for step in job["steps"] if "name" in step}
    primary = steps["Deploy, probe, destroy and verify absence"]
    cleanup = steps["Fail-safe teardown after an interrupted cycle"]
    assert job["timeout-minutes"] >= primary["timeout-minutes"] + cleanup["timeout-minutes"] + 10
    assert cleanup["if"] == "${{ always() }}"
    assert "-lock-timeout=60s" in cleanup["run"]
    assert "ci-${{ github.run_id }}-${{ github.run_attempt }}" in cleanup["run"]


def test_source_provenance_rejects_a_mismatched_checkout(monkeypatch, tmp_path):
    terraform_dir = tmp_path / "infra"
    terraform_dir.mkdir()
    (terraform_dir / "main.tf").write_text("terraform {}\n", encoding="utf-8")
    answers = iter([str(tmp_path), "b" * 40])
    monkeypatch.setattr(terraform_cycle, "_git", lambda *_args: next(answers))
    with pytest.raises(ValueError, match="does not match checkout HEAD"):
        terraform_cycle._verify_source_provenance(terraform_dir, "a" * 40)


def test_source_provenance_binds_the_committed_main_tf_blob(monkeypatch, tmp_path):
    terraform_dir = tmp_path / "infra"
    terraform_dir.mkdir()
    (terraform_dir / "main.tf").write_text("terraform {}\n", encoding="utf-8")
    answers = iter([str(tmp_path), "a" * 40, "", "1" * 40, "2" * 40])
    monkeypatch.setattr(terraform_cycle, "_git", lambda *_args: next(answers))
    with pytest.raises(ValueError, match="does not match the committed"):
        terraform_cycle._verify_source_provenance(terraform_dir, "a" * 40)


def test_cycle_refuses_any_environment_that_could_name_production(tmp_path):
    args = argparse.Namespace(
        terraform_dir=tmp_path,
        package=tmp_path / "package.zip",
        environment="prod",
        source_revision="a" * 40,
        workflow_run_url="https://github.com/upgradedev/mercury_amazon/actions/runs/1",
        output=tmp_path / "receipt.json",
        region="eu-west-1",
    )
    with pytest.raises(ValueError, match="guarded"):
        run_cycle(args)


def test_cycle_refuses_a_workflow_url_from_another_repository(tmp_path):
    args = argparse.Namespace(
        terraform_dir=tmp_path,
        package=tmp_path / "package.zip",
        environment="ci-1-1",
        source_revision="a" * 40,
        workflow_run_url="https://github.com/example/other/actions/runs/1",
        output=tmp_path / "receipt.json",
        region="eu-west-1",
    )
    with pytest.raises(ValueError, match="mercury_amazon"):
        run_cycle(args)


def test_absence_check_retries_through_control_plane_propagation(monkeypatch, tmp_path):
    results = iter([
        subprocess.CompletedProcess(["aws"], 0, "still here", ""),
        subprocess.CompletedProcess(["aws"], 255, "", "ResourceNotFoundException"),
    ])
    monkeypatch.setattr(terraform_cycle.subprocess, "run", lambda *args, **kwargs: next(results))
    monkeypatch.setattr(terraform_cycle.time, "sleep", lambda _seconds: None)
    log = tmp_path / "absence.log"
    assert terraform_cycle._absent(
        ["aws", "lambda", "get-function"], "ResourceNotFoundException", tmp_path, log,
        attempts=3,
    )
    assert "attempt 2/3" in log.read_text(encoding="utf-8")


def test_log_group_absence_retries_until_the_exact_name_is_gone(monkeypatch, tmp_path):
    results = iter([
        subprocess.CompletedProcess(["aws"], 0, "/aws/lambda/mercury-test\n", ""),
        subprocess.CompletedProcess(["aws"], 0, "", ""),
    ])
    monkeypatch.setattr(terraform_cycle.subprocess, "run", lambda *args, **kwargs: next(results))
    monkeypatch.setattr(terraform_cycle.time, "sleep", lambda _seconds: None)
    log = tmp_path / "cloudwatch.log"
    assert terraform_cycle._log_group_absent(
        "/aws/lambda/mercury-test", "eu-west-1", tmp_path, log, attempts=3,
    )
    assert "attempt 2/3" in log.read_text(encoding="utf-8")


def test_iam_policy_absence_retries_until_the_exact_name_is_gone(monkeypatch, tmp_path):
    results = iter([
        subprocess.CompletedProcess(["aws"], 0, "other-policy\tmercury-policy\n", ""),
        subprocess.CompletedProcess(["aws"], 0, "other-policy\n", ""),
    ])
    monkeypatch.setattr(terraform_cycle.subprocess, "run", lambda *args, **kwargs: next(results))
    monkeypatch.setattr(terraform_cycle.time, "sleep", lambda _seconds: None)
    log = tmp_path / "iam-policy.log"
    assert terraform_cycle._iam_policy_absent(
        "mercury-policy", tmp_path, log, attempts=3,
    )
    assert "attempt 2/3" in log.read_text(encoding="utf-8")
