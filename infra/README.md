# Mercury: Infrastructure as Code & Cost Profile

---

## 1. Cloud Architecture

Mercury deploys as a lightweight serverless FastMCP container on AWS Fargate with read-only IAM permissions to AWS Cost Explorer and CloudWatch.

---

## 2. Monthly Idle Cost Profile

| Resource | Service | Monthly Cost Idle | Measured Date |
|---|---|---|---|
| Streamable HTTP MCP Server | AWS Fargate (0 tasks when idle) | **$0.00** | 2026-09-01 |
| Cost Telemetry Queries | AWS Cost Explorer API (Free tier) | **$0.00** | 2026-09-01 |
| Telemetry Logs | Amazon CloudWatch (<5GB free tier) | **$0.00** | 2026-09-01 |
| **TOTAL MONTHLY IDLE COST** | | **$0.00** | **2026-09-01** |
