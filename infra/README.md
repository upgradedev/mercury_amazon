# Mercury infrastructure and cost profile

## Architecture

`main.tf` declares a serverless public demo on AWS Lambda behind a Function URL.
The role it declares can write only its DynamoDB state and logs, and can invoke
Bedrock models for the agent brief. Terraform forces `MERCURY_OFFLINE=1`, so a stack
built from this file alone serves labelled fixtures to anonymous traffic and cannot
read Cost Explorer or CloudWatch. Nothing runs continuously.

The production function is not that stack alone. Since 2026-10-19 it also reads
CloudWatch for three rows of the board, and the settings that allow it were made by
hand, outside Terraform. See
[What the live function runs that Terraform does not declare](#what-the-live-function-runs-that-terraform-does-not-declare).

## Monthly idle cost

**Every figure in this table is an ESTIMATE.** No AWS bill has been read for a
deployment of this project, and no Cost Explorer report for it has been recorded.
The figures are derived from published AWS free-tier allowances and from the fact
that a Lambda with zero invocations is not billed for compute.

| Resource | Service | Monthly idle cost | Basis |
|---|---|---|---|
| Cockpit compute | AWS Lambda, 0 invocations | **$0.00 (ESTIMATE)** | Lambda bills per request and per GB-second; neither accrues at zero invocations |
| HTTP entry point | Lambda Function URL | **$0.00 (ESTIMATE)** | Function URLs carry no separate charge |
| Telemetry logs | CloudWatch Logs | **$0.00 (ESTIMATE)** | Under the 5 GB ingestion free tier at zero traffic |
| Identity | IAM | **$0.00 (ESTIMATE)** | IAM is not billed |
| **Total idle** | | **$0.00 (ESTIMATE)** | |

The source adapters can make the following calls in a separately secured operator
deployment. The public Terraform stack does not grant these permissions:

* **AWS Cost Explorer** bills roughly one cent per API request. This is why
  `AWSCostAdapter` caches a successful response for 15 minutes; see
  `CACHE_TTL_SECONDS` in `src/infrastructure/aws_cost_adapter.py`.
* **CloudWatch GetMetricStatistics** bills per metric request beyond the free
  tier.

To replace these estimates with measurements, use a separately authenticated
operator deployment, leave it idle for a full billing period, then read its actual
Cost Explorer report. Cost Explorer stays off the anonymous URL, because it reports
the whole AWS account's bill.

The anonymous URL does read one kind of live account telemetry. Since 2026-10-19 the
production function runs with `MERCURY_LIVE_CLOUDWATCH=1`, and the board carries
three LIVE rows read from `AWS/Lambda` `Errors` and `Invocations` for the hackathon's
own functions: `mercury-wallboard-euw1-prod`, `volcan-mcp-euw1-prod` and
`aletheia-provenance-euw1-prod`. A page view can trigger those reads. Each instance
caches a successful read for 60 seconds and an unread one for 30
(`DEFAULT_LIVE_CACHE_SECONDS` in `src/infrastructure/cloudwatch_adapter.py`,
`UNREAD_CACHE_SECONDS` in `src/infrastructure/cloudwatch_read_outcome.py`). With
reserved concurrency at 10, a busy board can make up to ten pairs of successful reads
per function a minute (ESTIMATE, by arithmetic from that cache rule).

The grant is the inline role policy `mercury-read-own-lambda-metrics`. It allows only
`cloudwatch:GetMetricStatistics`, on `Resource: "*"`, because that action takes no
resource-level scoping. IAM therefore lets the role read any CloudWatch metric in the
account. The limit to three functions is enforced in the code
(`LIVE_PRODUCTION_FUNCTIONS` in `src/infrastructure/cloudwatch_adapter.py`), not in
the policy.

## What the live function runs that Terraform does not declare

Read on 2026-10-20 with read-only calls: `aws lambda get-function-configuration`,
`aws lambda get-function-concurrency`, `aws iam list-role-policies`,
`aws iam list-attached-role-policies` and `aws iam get-role-policy`. None of the
settings below is in `main.tf`, so applying this file does not reproduce the
production function. They were set outside Terraform; the 2026-10-19 changes to the
environment, the CloudWatch grant and the concurrency were each approved by the owner.

| Setting on `mercury-wallboard-euw1-prod` | Live value | In `main.tf` |
|---|---|---|
| `MERCURY_LIVE_CLOUDWATCH` | `1`, set on 2026-10-19 at 22:21 UTC | No |
| `MERCURY_AGENT_MODEL` and `MERCURY_AGENT_MODEL_MAX_CALLS` | `on` and `40`, set on 2026-10-19 | No |
| `MERCURY_ROLLBACK_SECRET` | Set; its value is not in the repository | No |
| Inline policy `mercury-read-own-lambda-metrics` | `cloudwatch:GetMetricStatistics` on `*`, attached on 2026-10-19 at 22:21 UTC | No |
| Reserved concurrency | 10, set on 2026-10-19 at 22:48 UTC; it was 2 before | No `reserved_concurrent_executions` |
| The role's other grants | Inline `mercury-state-euw1-prod` (DynamoDB `GetItem`, `PutItem` and `Query` on its table), the AWS-managed `AWSLambdaBasicExecutionRole`, and the customer-managed `volcan-bedrock-mantle-euw1-prod` | `main.tf` declares one customer-managed policy, `mercury-serverless-policy-euw1-prod`, for logs, DynamoDB and Bedrock. It is not attached to the live role |

The live function does carry what `main.tf` declares for its environment:
`ENVIRONMENT`, `MERCURY_BUILD_SHA` (`e6aae2c`), `MERCURY_STATE_TABLE` and
`MERCURY_OFFLINE=1`. Neither `MERCURY_LIVE_GITHUB` nor `GITHUB_TOKEN` is set.

## Deploy and teardown

The **Disposable deploy and teardown proof** Actions workflow is the auditable route.
It refuses any environment name outside `ci-RUN_ID-RUN_ATTEMPT`, builds the Lambda
package from the checked-out revision, applies this Terraform from nothing, probes
the emitted URL and build SHA, destroys the stack, then verifies that its Lambda,
DynamoDB table, IAM role and CloudWatch log group are absent. A passing run uploads
a content-addressed receipt; it never targets or destroys the production URL.

`infra/.terraform.lock.hcl` pins the reviewed AWS provider 6.66.0. That version owns
both public Function URL statements, including the URL-only `lambda:InvokeFunction`
condition. Main CI runs `fmt`, `init` against the lock file and `validate` before tests.

```bash
cd infra
terraform init
terraform validate
terraform plan -var="source_revision=$(git rev-parse HEAD)" -out=tfplan
terraform apply tfplan

terraform destroy -auto-approve
```

The disposable GitHub Actions cycle performs teardown in the runner script and
again in an `always()` fail-safe step with its own time budget. This covers an
ordinary failure, primary-step timeout and standard workflow cancellation. A
force-cancel or lost runner can bypass all runner-side cleanup; every stack uses
the guarded `ci-RUN_ID-RUN_ATTEMPT` namespace so an operator can identify and
remove that interrupted run before accepting a D2 receipt.

The public cockpit is deployed at
`https://leol25sezuvokpankox5cvjopm0gtvfa.lambda-url.eu-west-1.on.aws/`.
`GET /health` publishes the immutable build SHA. Probed on 2026-10-19 at 22:23 UTC
with `python scripts/probe_deployment.py <url>`, it reported `e6aae2c`, which matched
the local HEAD at the time, and listed the three CloudWatch rows under `live_sources`.
`deploy_teardown_receipt.json` records that dated HTTP observation. The deployment
keeps `MERCURY_OFFLINE=1`, so the five demo services, Cost Explorer and GitHub are
labelled fixtures, and rollback dispatch is record-only. Its execution role can read
CloudWatch metrics, as described above. It does not claim a physical Fire TV run.

Set `MERCURY_BUILD_SHA` at deploy time, or deploy from a git checkout, so that
`GET /health` reports the commit it was built from. `scripts/probe_deployment.py`
reads that field to decide whether a deployment matches the submitted commit.
