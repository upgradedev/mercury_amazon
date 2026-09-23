"""Run one guarded disposable Terraform deploy, probe, destroy and absence check."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _run(command: list[str], cwd: Path, log_path: Path) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=900)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        "$ " + " ".join(command) + "\n\n" + result.stdout + "\n" + result.stderr,
        encoding="utf-8",
    )
    return result


def _require(result: subprocess.CompletedProcess[str], step: str) -> str:
    if result.returncode != 0:
        raise RuntimeError(f"{step} failed with exit code {result.returncode}")
    return result.stdout


def _probe(url: str, path: str, attempts: int = 8) -> dict[str, Any]:
    target = url.rstrip("/") + path
    last: dict[str, Any] = {"url": target, "http_status": None, "body": "", "error": "not run"}
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(target, timeout=20) as response:
                body = response.read().decode("utf-8", errors="replace")
                return {
                    "url": target,
                    "http_status": response.status,
                    "body": body[:1000],
                    "error": None,
                }
        except urllib.error.HTTPError as exc:
            last = {"url": target, "http_status": exc.code, "body": "", "error": str(exc)}
        except (OSError, urllib.error.URLError) as exc:
            last = {"url": target, "http_status": None, "body": "", "error": str(exc)}
        if attempt + 1 < attempts:
            time.sleep(5)
    return last


def _absent(command: list[str], expected: str, cwd: Path, log_path: Path) -> bool:
    result = _run(command, cwd, log_path)
    return result.returncode != 0 and expected in (result.stdout + result.stderr)


def _log_group_absent(name: str, region: str, cwd: Path, log_path: Path) -> bool:
    result = _run(
        [
            "aws", "logs", "describe-log-groups", "--log-group-name-prefix", name,
            "--region", region, "--query", "logGroups[].logGroupName", "--output", "text",
        ],
        cwd,
        log_path,
    )
    names = {line.strip() for line in result.stdout.splitlines() if line.strip()}
    return result.returncode == 0 and name not in names


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_cycle(args: argparse.Namespace) -> tuple[dict[str, Any], bool]:
    if not re.fullmatch(r"ci-[0-9]+-[0-9]+", args.environment):
        raise ValueError("environment must be the guarded ci-RUN_ID-RUN_ATTEMPT form")
    if not re.fullmatch(r"[0-9a-f]{40}", args.source_revision):
        raise ValueError("source revision must be a full Git SHA")
    if not args.workflow_run_url.startswith("https://github.com/upgradedev/mercury_amazon/actions/runs/"):
        raise ValueError("workflow URL must identify a mercury_amazon Actions run")

    terraform_dir = args.terraform_dir.resolve()
    package = args.package.resolve()
    output = args.output.resolve()
    evidence_dir = output.parent
    evidence_dir.mkdir(parents=True, exist_ok=True)
    variables = [
        f"-var=environment={args.environment}",
        f"-var=source_revision={args.source_revision}",
        f"-var=lambda_package_path={package}",
    ]
    function_name = f"mercury-wallboard-euw1-{args.environment}"
    table_name = f"mercury-state-euw1-{args.environment}"
    role_name = f"mercury-lambda-role-euw1-{args.environment}"
    log_group_name = f"/aws/lambda/{function_name}"
    receipt: dict[str, Any] = {
        "schema": "mercury.terraform_cycle_receipt/2",
        "note": (
            "A GitHub Actions pipeline created a uniquely named disposable stack, probed it, "
            "destroyed it, then verified that its Lambda, DynamoDB table and IAM role were absent. "
            "The production URL was not destroyed."
        ),
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_revision": args.source_revision,
        "workflow_run_url": args.workflow_run_url,
        "execution_mode": "github_actions_pipeline",
        "environment": args.environment,
        "region": args.region,
        "production_url_destroyed": False,
        "lambda_package": {"sha256": _sha256(package), "bytes": package.stat().st_size},
        "infra": {
            "main_tf_sha256": _sha256(terraform_dir / "main.tf"),
            "git_blob": subprocess.run(
                ["git", "hash-object", "infra/main.tf"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip(),
        },
        "steps": {},
    }
    initialized = False
    endpoint = ""
    cycle_error = ""
    pre_destroy: dict[str, Any] = {}
    destroy: dict[str, Any] = {"teardown_verified": False}
    try:
        init = _run(
            ["terraform", "init", "-input=false", "-no-color"],
            terraform_dir,
            evidence_dir / "terraform-init.log",
        )
        receipt["steps"]["init_exit_code"] = init.returncode
        _require(init, "terraform init")
        initialized = True

        plan_path = terraform_dir / "cycle.tfplan"
        plan = _run(
            ["terraform", "plan", "-input=false", "-no-color", f"-out={plan_path}", *variables],
            terraform_dir,
            evidence_dir / "terraform-plan.log",
        )
        receipt["steps"]["plan_exit_code"] = plan.returncode
        _require(plan, "terraform plan")
        apply = _run(
            ["terraform", "apply", "-input=false", "-no-color", str(plan_path)],
            terraform_dir,
            evidence_dir / "terraform-apply.log",
        )
        receipt["steps"]["apply_exit_code"] = apply.returncode
        _require(apply, "terraform apply")

        endpoint_result = _run(
            ["terraform", "output", "-json", "wallboard_endpoint_url"],
            terraform_dir,
            evidence_dir / "terraform-output.log",
        )
        endpoint = json.loads(_require(endpoint_result, "terraform output"))
        root_probe = _probe(endpoint, "/")
        health_probe = _probe(endpoint, "/health")
        health = json.loads(health_probe["body"]) if health_probe["http_status"] == 200 else {}
        policy = _run(
            ["aws", "lambda", "get-policy", "--function-name", function_name, "--region", args.region],
            terraform_dir,
            evidence_dir / "lambda-policy.log",
        )
        policy_document = json.loads(json.loads(policy.stdout)["Policy"]) if policy.returncode == 0 else {}
        policy_sids = sorted(statement.get("Sid", "") for statement in policy_document.get("Statement", []))
        pre_destroy = {
            "url": endpoint,
            "root_http_status": root_probe["http_status"],
            "health_http_status": health_probe["http_status"],
            "health_build_sha": health.get("build_sha"),
            "health_durable_state": health.get("durable_state"),
            "function_policy_statements": policy_sids,
        }
    except Exception as exc:  # recorded, followed by a mandatory destroy attempt
        cycle_error = f"{type(exc).__name__}: {exc}"
    finally:
        if initialized:
            destroyed = _run(
                [
                    "terraform", "destroy", "-auto-approve", "-input=false", "-no-color",
                    *variables,
                ],
                terraform_dir,
                evidence_dir / "terraform-destroy.log",
            )
            receipt["steps"]["destroy_exit_code"] = destroyed.returncode
            time.sleep(5)
            url_probe = _probe(endpoint, "/", attempts=2) if endpoint else {
                "http_status": None,
                "error": "apply produced no endpoint",
            }
            lambda_absent = _absent(
                ["aws", "lambda", "get-function", "--function-name", function_name, "--region", args.region],
                "ResourceNotFoundException",
                terraform_dir,
                evidence_dir / "post-destroy-lambda.log",
            )
            table_absent = _absent(
                ["aws", "dynamodb", "describe-table", "--table-name", table_name, "--region", args.region],
                "ResourceNotFoundException",
                terraform_dir,
                evidence_dir / "post-destroy-dynamodb.log",
            )
            role_absent = _absent(
                ["aws", "iam", "get-role", "--role-name", role_name],
                "NoSuchEntity",
                terraform_dir,
                evidence_dir / "post-destroy-iam.log",
            )
            log_group_absent = _log_group_absent(
                log_group_name,
                args.region,
                terraform_dir,
                evidence_dir / "post-destroy-cloudwatch.log",
            )
            destroy = {
                "terraform_exit_code": destroyed.returncode,
                "post_destroy_url_http_status": url_probe.get("http_status"),
                "post_destroy_url_error": url_probe.get("error"),
                "lambda_absent": lambda_absent,
                "dynamodb_absent": table_absent,
                "iam_role_absent": role_absent,
                "cloudwatch_log_group_absent": log_group_absent,
                "teardown_verified": (
                    destroyed.returncode == 0
                    and url_probe.get("http_status") != 200
                    and lambda_absent
                    and table_absent
                    and role_absent
                    and log_group_absent
                ),
            }

    receipt["pre_destroy"] = pre_destroy
    receipt["destroy"] = destroy
    receipt["error"] = cycle_error or None
    required_sids = {"FunctionURLAllowPublicAccess", "FunctionURLAllowInvokeAction"}
    passed = (
        not cycle_error
        and pre_destroy.get("root_http_status") == 200
        and pre_destroy.get("health_http_status") == 200
        and pre_destroy.get("health_build_sha") == args.source_revision
        and pre_destroy.get("health_durable_state") is True
        and required_sids <= set(pre_destroy.get("function_policy_statements", []))
        and destroy.get("teardown_verified") is True
    )
    receipt["passed"] = passed
    output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt, passed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--terraform-dir", type=Path, required=True)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--workflow-run-url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--region", default="eu-west-1")
    receipt, passed = run_cycle(parser.parse_args())
    print(json.dumps(receipt, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
