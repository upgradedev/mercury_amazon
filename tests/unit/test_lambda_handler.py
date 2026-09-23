"""The committed Lambda bridge and exact-revision health response."""
import importlib
import json
import re
from pathlib import Path

from src.interfaces import mcp_server
from src.interfaces.lambda_handler import handler

ROOT = Path(__file__).resolve().parents[2]


def event(method: str, path: str) -> dict:
    return {
        "version": "2.0",
        "rawPath": path,
        "rawQueryString": "",
        "headers": {},
        "requestContext": {
            "domainName": "example.lambda-url.eu-west-1.on.aws",
            "http": {"method": method, "path": path, "sourceIp": "203.0.113.10"},
        },
        "body": None,
        "isBase64Encoded": False,
    }


def test_terraform_handler_resolves_to_the_committed_callable():
    text = (ROOT / "infra" / "main.tf").read_text(encoding="utf-8")
    match = re.search(r'handler\s*=\s*"([^"]+)"', text)
    assert match
    module_name, _, function_name = match.group(1).rpartition(".")
    assert callable(getattr(importlib.import_module(module_name), function_name))
    assert module_name == "src.interfaces.lambda_handler"
    assert "filename         = var.lambda_package_path" in text
    assert "source_code_hash = filebase64sha256(var.lambda_package_path)" in text


def test_health_runs_through_lambda_bridge_and_exposes_revision(monkeypatch):
    monkeypatch.setattr(mcp_server, "BUILD_SHA", "abc123def456")
    response = handler(event("GET", "/health"))
    body = json.loads(response["body"])
    assert response["statusCode"] == 200
    assert body["service"] == "mercury-firetv-cockpit"
    assert body["build_sha"] == "abc123def456"


def test_unknown_path_is_a_404_response():
    assert handler(event("GET", "/not-a-route"))["statusCode"] == 404

