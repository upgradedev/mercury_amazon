# 🧪 End-to-End User Acceptance Testing (UAT) Testbook
## Project: Mercury — Fire TV Voice CTO Cockpit & 10-Foot War Room

---

## 🎯 Target Persona
* **Persona:** Alex, Lead DevOps Engineer running Black Friday infrastructure monitoring.
* **Hardware Setup:** 65" TV Screen with Amazon Fire TV Stick 4K & Alexa Voice Remote.

---

## 📋 UAT Test Scenario Matrix

| Test ID | Scenario Description | Preconditions | Action Steps | Expected Outcome | Automated Test Mapping |
|:---:|---|---|---|---|---|
| **UAT-MER-01** | **10-Foot Glanceable UI Ingestion** | Fire TV Leanback app running | 1. Open Mercury Cockpit on 65" TV.<br>2. Observe telemetry cards from 3 meters. | • High-contrast 24px-36px fonts.<br>• Sub-second P95 render latency. | `tests/unit/test_html_structure.py` |
| **UAT-MER-02** | **Real-Time CloudWatch Alarm Telemetry Ingestion** | Multi-source CI/CD webhook sent | 1. Ingest incident payload (`500 Internal Server Error`).<br>2. Monitor D-Bus event. | • Dashboard turns Amber/Red immediately.<br>• Triggers alarm sound effect & visual pulse. | `tests/unit/test_devops_ingest.py` |
| **UAT-MER-03** | **Alexa Voice Remote Navigation (D-Pad)** | Alexa Voice Remote paired | 1. Press D-Pad Left/Right.<br>2. Say *"Alexa, filter active P1 incidents"*. | • Focus shifts smoothly with zero cursor requirement.<br>• Filters incident stream hands-free. | `tests/unit/test_devops_ingest.py` |
| **UAT-MER-04** | **Sub-50ms Incident Recovery & Resolution** | Incident resolved in GitHub Actions | 1. Ingest resolution webhook.<br>2. Validate telemetry clear. | • Screen returns to Emerald Green status (`All Systems Normal`). | `tests/performance/test_load_and_latency.py` |

---

## 🛡️ CI/CD Verification
All scenarios above are automated and executed on every push via `.github/workflows/ci.yml`.
