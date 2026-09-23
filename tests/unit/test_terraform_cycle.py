from __future__ import annotations

import argparse

import pytest

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
