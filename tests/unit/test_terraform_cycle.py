from __future__ import annotations

import argparse
import subprocess

import pytest

from scripts import terraform_cycle
from scripts.terraform_cycle import run_cycle


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
