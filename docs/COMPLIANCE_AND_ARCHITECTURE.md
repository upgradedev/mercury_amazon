# Mercury: Architecture & Compliance Review

---

## 1. AWS Well-Architected Framework (with 2026 Agentic AI Lens)

| Pillar | Architectural Implementation | Verification Control |
|---|---|---|
| **Operational Excellence** | Automated GitHub Actions CI, structured healthchecks (`/health`), deterministic DORA calculations. | `OPS-01`: Healthcheck returns HTTP 200 with runtime status. |
| **Security** | Least privilege read-only IAM access for AWS Cost Explorer; voice token required for production rollbacks. | `SEC-01`: `test_governed_rollback_flow` verifies token enforcement. |
| **Reliability** | Decoupled hexagonal architecture with robust mock fallbacks for offline testing. | `REL-01`: Zero crashes during telemetry API latency. |
| **Performance Efficiency** | Pure Python DORA calculation executes in <1ms without disk I/O. | `PERF-01`: DORA calculation benchmarked <1ms. |
| **Cost Optimization** | Serverless FastMCP deployment scales to zero with $0.00 idle cost. | `COST-01`: $0.00 idle cost verified in `infra/README.md`. |
| **Sustainability** | Lightweight event-driven processing with minimal CPU overhead. | `SUST-01`: CPU utilization <1% at idle. |

---

## 2. EU AI Act (Regulation EU 2024/1689) Alignment

| Article | Requirement | Mercury Implementation | Residual Gap |
|---|---|---|---|
| **Article 10** | Data Governance | All engineering metrics processed in-memory. Zero source code or confidential credentials persisted. | GitHub token storage managed by customer IAM. |
| **Article 13** | Transparency | Metric formulas follow standard Google DORA definitions with clear spoken explanations. | Custom organization DORA variations must be configured in schedules. |
| **Article 14** | Human Oversight | Rollback actions require explicit voice token confirmation from authorized engineering leader. | Voice token authentication depends on host device security. |
| **Article 15** | Accuracy & Robustness | Deterministic metric aggregation prevents hallucination in quantitative statistics. | None. Pure deterministic mathematics. |
| **Article 50** | Model Transparency | Spoken digests explicitly declare calculated metrics versus heuristic anomaly projections. | None. Clearly articulated in voice digests. |

---

## 3. GDPR & Privacy Map

* **Personal Data Processed:** Anonymized pull request IDs and author usernames. Zero PII or customer database records accessed.
* **Storage Duration:** In-memory volatile processing; zero permanent storage.
