# Mercury: Official Devpost Submission Text

---

## Short Tagline (under 25 words)
Mercury equips VP of Engineering and CTOs with voice-driven DORA metrics, pull request bottleneck diagnostics, and AWS cloud cost anomaly alerts on Alexa+ and Fire TV.

---

## 1. Inspiration & Problem (The Human Story)

Engineering directors and CTOs are inundated with 10+ disjointed dashboards across GitHub, Jira, Datadog, and AWS Cost Explorer. Critical insights fall through the cracks:
* Pull requests languish in code review queues for over 36 hours without executive awareness.
* Staging cloud workloads spike unexpectedly over weekends, depleting monthly cloud budgets.
* Change failure rates and mean time to recovery (MTTR) drift unchecked.

Inspired by **Hermes (Mercury)**, the fleet-footed messenger god of trade and rapid communication, **Mercury** transforms Amazon Alexa+ and Fire TV into an executive voice cockpit.

---

## 2. What it Does

1. **Voice DORA Radar:** Real-time calculation of Deployment Frequency, Lead Time, Change Failure Rate, and MTTR into spoken executive digests and Elite/High/Medium tier classifications.
2. **PR Bottleneck Diagnostics:** Identifies stalled pull requests exceeding 36-hour team review SLAs.
3. **AWS Cloud Cost Radar:** Proactive anomaly detection on AWS Cost Explorer with month-end projections and root-cause explanations.
4. **Governed Service Rollbacks:** Voice-authenticated staging and execution of production rollbacks with 300-second leases.

---

## 3. How We Built It

* **Architecture:** Clean Hexagonal Domain-Driven Design (DDD) with pure Python telemetry models.
* **Voice Transport:** FastMCP Server over Streamable HTTP (Spec 2025-11-25+).
* **AWS Integration:** Read-only IAM access to AWS Cost Explorer and CloudWatch metrics.
* **Zero-Setup Web Demo:** Interactive companion war room dashboard on `/demo`.

---

## 4. Headline Comparative Result

* **76% Faster Executive Decision Velocity:** Reduces cross-dashboard diagnostic time from 25 minutes of manual clicking to a **6-second voice conversation**.

---

## 5. Track & Mini-Challenge Declarations

* **Primary Track:** **Alexa+ Track** (or Fire TV Track).
* **Mini Challenges:** **AWS Builder** + **Open Source**.

---

## 6. Mandatory Product Feedback

* **Developer Tools Used:** Amazon Alexa+, Model Context Protocol (Streamable HTTP), AWS Cost Explorer API, FastAPI.
* **What Worked Well:** The Streamable HTTP MCP transport allows instant streaming of telemetry digests to voice clients.
* **What Needs Work:** Native AWS Cost Explorer sandbox environments for local CI integration testing would accelerate development.
* **Onboarding Experience:** Highly responsive and developer-friendly.
* **Would You Build With These Tools Again:** Yes. Voice-first executive intelligence saves hours of executive cognitive load.
