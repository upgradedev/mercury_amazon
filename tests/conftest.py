"""Shared test fixtures.

The rollback secret is set here, before any test module imports the server, so
the whole suite authorizes against a known value instead of the ephemeral one
the server generates when the variable is unset.
"""
import os

os.environ.setdefault("MERCURY_ROLLBACK_SECRET", "test-secret-do-not-use-in-production")
# Keep the suite off the network whatever credentials the machine happens to
# have. Without this the cost endpoint makes a real, billable Cost Explorer
# request on any developer machine with an AWS profile configured.
os.environ["MERCURY_OFFLINE"] = "1"
os.environ.pop("GITHUB_TOKEN", None)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

OPERATOR_SECRET = os.environ["MERCURY_ROLLBACK_SECRET"]


@pytest.fixture(scope="session")
def operator_secret() -> str:
    return OPERATOR_SECRET


@pytest.fixture
def client() -> TestClient:
    from src.interfaces.mcp_server import app

    return TestClient(app)


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {OPERATOR_SECRET}"}


@pytest.fixture(autouse=True)
def _reset_shared_evidence_state():
    """Keep deployment and handoff evidence isolated between tests."""
    from src.interfaces.mcp_server import deployment_evidence, incident_handoffs

    deployment_evidence.clear()
    incident_handoffs.clear()
    yield
    deployment_evidence.clear()
    incident_handoffs.clear()
