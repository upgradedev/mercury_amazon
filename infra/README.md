# Mercury: Infrastructure as Code & Cost Profile

---

## 1. Cloud Architecture: 100% Pure Serverless

Mercury deploys as a **Pure Serverless Architecture** on AWS Lambda, serving telemetry and DORA metrics to Amazon Fire TV devices and web warrooms via HTTPS Lambda Function URLs with zero always-on container costs.

---

## 2. Monthly Idle Cost Profile

| Resource | AWS Service | Monthly Idle Cost | Measured Date |
|---|---|---|---|
| Wallboard Serverless Compute | AWS Lambda (0 invocations = $0.00) | **$0.00** | 2026-09-02 |
| Wallboard Function URL | AWS Lambda Function URL (Included Free) | **$0.00** | 2026-09-02 |
| Cost Telemetry Queries | AWS Cost Explorer API (Free tier) | **$0.00** | 2026-09-02 |
| Telemetry Logs | Amazon CloudWatch (<5GB free tier) | **$0.00** | 2026-09-02 |
| Identity & Access | AWS IAM | **$0.00** | 2026-09-02 |
| **TOTAL MONTHLY IDLE COST** | | **$0.00** | **2026-09-02** |

---

## 3. Deploy & Teardown Instructions

```bash
# Initialize Terraform
cd infra
terraform init

# Validate configuration
terraform validate

# Plan and Apply
terraform plan -out=tfplan
terraform apply tfplan

# Teardown / Destroy all resources
terraform destroy -auto-approve
```
