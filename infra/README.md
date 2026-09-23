# Mercury infrastructure and cost profile

## Architecture

`main.tf` declares a serverless deployment on AWS Lambda behind a Function URL,
reading AWS Cost Explorer and CloudWatch. Nothing runs continuously.

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

Idle is not the same as in use. Two costs accrue the moment the cockpit is used,
and neither is estimated here because it depends entirely on refresh rate:

* **AWS Cost Explorer** bills roughly one cent per API request. This is why
  `AWSCostAdapter` caches a successful response for 15 minutes; see
  `CACHE_TTL_SECONDS` in `src/infrastructure/aws_cost_adapter.py`.
* **CloudWatch GetMetricStatistics** bills per metric request beyond the free
  tier.

To replace these estimates with measurements, deploy, leave it idle for a full
billing period, then run `python scripts/probe_deployment.py` and read the actual
Cost Explorer report for the account.

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

The public cockpit is deployed at
`https://leol25sezuvokpankox5cvjopm0gtvfa.lambda-url.eu-west-1.on.aws/`.
`GET /health` publishes the immutable build SHA. The deployment currently uses labelled
offline fixtures and record-only rollback dispatch; it does not claim live incident telemetry
or a physical Fire TV run. `deploy_teardown_receipt.json` records a dated HTTP observation.

Set `MERCURY_BUILD_SHA` at deploy time, or deploy from a git checkout, so that
`GET /health` reports the commit it was built from. `scripts/probe_deployment.py`
reads that field to decide whether a deployment matches the submitted commit.
