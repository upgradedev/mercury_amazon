# Mercury — Full End-to-End User Acceptance Testing (UAT) Testbook

**Product:** Mercury (Multi-modal Engineering Cockpit on Fire TV & Alexa Voice Control)  
**Version:** 0.1.0  
**Target Persona:** Engineering Directors, CTOs, and Platform leads running team war-rooms on large TV screens  
**Standard:** ISO/IEC 25010 & IEEE 829 Test Documentation

---

## 1. Test Strategy & Acceptance Criteria

| ID | Test Category | Objective | Tool / Automation | Acceptance Criteria |
|---|---|---|---|---|
| **UAT-01** | **10-Foot Spatial Focus Nav** | Verify D-Pad directional navigation (`Arrow` keys + `Enter`) across TV UI tiles | Playwright / DOM Nav | Visual neon focus ring moves seamlessly without focus traps |
| **UAT-02** | **DORA Velocity Assessment** | Calculate deploy frequency, lead time, CFR, and MTTR from Git/CI events | DORA Domain Model | Correctly evaluates Elite / High performer tier in < 1.0 ms |
| **UAT-03** | **AWS Cloud Cost Radar** | Detect Bedrock and ECS staging spend spikes (>200% burn rate) | Cost Radar Model | Anomaly flag triggered and spoken voice alert synthesized |
| **UAT-04** | **Governed Production Rollback** | Verify production rollback staging under SHA-256 lock & 300s lease | Rollback Engine | Rollback quarantined; unconfirmed leases expire automatically |
| **UAT-05** | **TV Multi-Modal Voice Sync** | Synchronize spoken metrics with visual on-screen tile highlights | Web Speech + DOM | Voice narration matches displayed numbers with zero discrepancy |

---

## 2. Step-by-Step Scenario Test Cases

### Test Case UAT-MERCURY-001: 10-Foot D-Pad Navigation & DORA Inspection
- **Pre-Conditions:** Fire TV Webview running Mercury Cockpit (`localhost:8000`).
- **Action Steps:**
  1. User presses `ArrowRight` on remote to focus Deploy Frequency tile.
  2. User presses `Enter` or utters: *"Alexa, show engineering velocity"*.
  3. Mercury computes 4 DORA metrics.
- **Expected Outcome:**
  - Tile displays `2.4 / day`, `14.5 h` lead time, `3.2%` CFR, and `0.8 h` MTTR.
  - Tag illuminates in green: `ELITE PERFORMER`.
  - Voice summary spoken: *"Team velocity is rated Elite Performer with 2.4 daily deploys and 0.8 hour recovery time."*

### Test Case UAT-MERCURY-002: AWS Cost Explorer Anomaly Detection
- **Pre-Conditions:** Staging cluster burn rate increases from $45/day to $185/day.
- **Action Steps:**
  1. User clicks "Scan AWS Cost Explorer" or utters: *"Alexa, scan cloud costs"*.
  2. Mercury analyzes CloudWatch / Cost Explorer baseline.
- **Expected Outcome:**
  - Anomaly tag flashes red: `COST SPIKE +311%`.
  - Spoken digest: *"Warning: Staging Bedrock tasks increased daily burn by 311 percent to 185 dollars per day."*

### Test Case UAT-MERCURY-003: Governed Production Rollback Staging
- **Pre-Conditions:** Anomaly detected in `payments-api` service.
- **Action Steps:**
  1. Lead engineer triggers "Execute Governed Rollback".
  2. Mercury stages `GovernedRollbackAction` with 300s TTL.
- **Expected Outcome:**
  - Status transitions to `ROLLBACK LEASE INITIATED`.
  - Target commit hash displayed (`HEAD~1` SHA `12443b59`).
  - Voice prompt announced: *"Production rollback lease staged for payments API. 300 second lease active. Say: Alexa, approve rollback."*
