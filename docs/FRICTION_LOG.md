# Mercury: Amazon Alexa+ & AWS Telemetry Friction Log

> **Contest Submission Bonus Requirement:** Developer feedback on Alexa+ MCP integration and AWS Cost Explorer APIs. (Up to +10% Stage 2 bonus).

---

## 1. AWS Cost Explorer & Anomaly Detection APIs

### Task Attempted
Query real-time daily cost trends and anomaly detection feeds from AWS Cost Explorer to announce spend surges via Alexa+ voice turns.

### Steps Taken
1. Configured least-privilege IAM policy with `ce:GetCostAndUsage` and `ce:GetAnomalies`.
2. Implemented mock telemetry adapter for zero-cost offline development.

### Expected vs. Actual Result
* **Expected:** Instant sub-second response times from Cost Explorer APIs for recent 24-hour windows.
* **Actual:** Cost Explorer API queries occasionally incur 1.5s to 3.0s latency due to historical aggregation overhead.

### Workaround Used
Implemented a lightweight caching and projection layer in the application use case to maintain sub-100ms voice query responses on Alexa+.

### Actionable Suggestion for AWS Team
Provide lightweight real-time telemetry streaming hooks for AWS Cost Explorer anomalies directly into Amazon EventBridge.
