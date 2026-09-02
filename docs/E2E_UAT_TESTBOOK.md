# E2E UAT Testbook — Mercury (Fire TV Multi-Modal Engineering Cockpit)

## Test Persona: Dev Team Lead viewing war room telemetry on 65-inch Fire TV

### 📋 Scenario 1: 10-Foot Glanceable Wallboard Ingress
* **Precondition:** Fire TV cockpit active.
* **Step 1 (Input):** Webhook pushes deployment failure event.
* **Step 2 (Execution):** Mercury updates high-contrast red widget banner.
* **Expected Result:** High-contrast glanceable layout visible from 3 meters away.
* **Verification Command:** `pytest tests/integration/test_wallboard_telemetry.py -v`
