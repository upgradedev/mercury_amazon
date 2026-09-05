"""Shared test fixtures.

The rollback secret is set here, before any test module imports the server, so
the whole suite authorizes against a known value instead of the ephemeral one
the server generates when the variable is unset.
"""
import os

os.environ.setdefault("MERCURY_ROLLBACK_SECRET", "test-secret-do-not-use-in-production")
# Keep the suite off the network: without a token the GitHub adapter serves its
# recorded fixture, which is what these tests assert against.
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
