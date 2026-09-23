"""Unit tests for the GitHub Actions rollback dispatcher.

The dispatcher has never been fired at github.com, so what these tests can prove
is the shape of the request it would send, and that it sends nothing at all until
it is explicitly armed. Every case drives the real ``httpx`` request building
through ``httpx.MockTransport``; only the socket is replaced.

The negative cases carry the weight: a dispatcher that is configured but not
armed, and one that is armed but missing a token, must both leave the transport
untouched. A recorder list that is still empty at the end of the test is the
assertion.
"""
import httpx
import pytest

from src.domain.governed_rollback import GovernedRollbackAction
from src.infrastructure.github_actions_dispatcher import (
    ARMED_ENV,
    DISPATCH_MODE_ENV,
    REF_ENV,
    REPOSITORY_ENV,
    TOKEN_ENV,
    WORKFLOW_ENV,
    GitHubActionsRollbackDispatcher,
    RollbackDispatchError,
)

REPO = "acme/payments"
WORKFLOW = "rollback.yml"
EXPECTED_URL = f"https://api.github.com/repos/{REPO}/actions/workflows/{WORKFLOW}/dispatches"


def make_action() -> GovernedRollbackAction:
    return GovernedRollbackAction.create(
        action_id="tv-1730",
        target_service="checkout-api",
        target_commit_sha="3e9d10c4b2",
        reason="Staged from the Fire TV cockpit after a what-changed correlation.",
    )


def make_client(status: int = 204, body: str = "", recorder: list | None = None) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if recorder is not None:
            recorder.append(request)
        return httpx.Response(status, text=body)

    return httpx.Client(transport=httpx.MockTransport(handler))


def clear_dispatch_env(monkeypatch) -> None:
    for name in (DISPATCH_MODE_ENV, ARMED_ENV, REPOSITORY_ENV, WORKFLOW_ENV, REF_ENV, TOKEN_ENV):
        monkeypatch.delenv(name, raising=False)


# ------------------------------------------------------------- The request shape

def test_the_request_is_a_workflow_dispatch_carrying_every_rollback_field():
    dispatcher = GitHubActionsRollbackDispatcher(REPO, WORKFLOW, ref="main", token="ghp_test")
    action = make_action()
    request = dispatcher.build_request(action)

    assert request.method == "POST"
    assert request.url == EXPECTED_URL
    assert request.json_body["ref"] == "main"
    assert request.json_body["inputs"] == {
        "action_id": "tv-1730",
        "target_service": "checkout-api",
        "target_commit_sha": "3e9d10c4b2",
        "environment": "",
        "target_artifact_sha256": "",
        "target_deployment_marker_id": "",
        "offending_deployment_marker_id": "",
        "reason": "Staged from the Fire TV cockpit after a what-changed correlation.",
        "payload_hash": action.payload_hash,
    }


def test_the_request_carries_the_github_api_version_and_a_bearer_token():
    request = GitHubActionsRollbackDispatcher(REPO, token="ghp_test").build_request(make_action())
    assert request.headers["Authorization"] == "Bearer ghp_test"
    assert request.headers["Accept"] == "application/vnd.github+json"
    assert request.headers["X-GitHub-Api-Version"] == "2022-11-28"


def test_no_authorization_header_is_invented_when_there_is_no_token():
    request = GitHubActionsRollbackDispatcher(REPO, token="").build_request(make_action())
    assert "Authorization" not in request.headers


def test_a_described_request_never_prints_the_token():
    request = GitHubActionsRollbackDispatcher(REPO, token="ghp_supersecret").build_request(make_action())
    assert request.redacted_headers()["Authorization"] == "Bearer <redacted>"
    assert "ghp_supersecret" not in str(request.redacted_headers())


def test_the_payload_hash_travels_with_the_dispatch():
    """The workflow can re-derive what it was asked to do, and check it."""
    action = make_action()
    request = GitHubActionsRollbackDispatcher(REPO).build_request(action)
    assert request.json_body["inputs"]["payload_hash"] == action.current_payload_hash()


# ---------------------------------------------------- Disarmed means nothing sent

def test_an_unarmed_dispatch_sends_nothing_and_says_what_it_would_have_sent():
    sent: list[httpx.Request] = []
    dispatcher = GitHubActionsRollbackDispatcher(
        REPO, token="ghp_test", armed=False, client=make_client(recorder=sent),
        disarm_reason=f"{ARMED_ENV} is not set, so this dispatch is a dry run.",
    )
    result = dispatcher.dispatch(make_action())

    assert sent == [], "an unarmed dispatcher must not open a socket"
    assert result.state.value == "RECORDED_ONLY"
    assert "DRY RUN: no request was sent" in result.output
    assert EXPECTED_URL in result.output
    assert "ghp_test" not in result.output, "the dry run must not print the token"


def test_an_armed_but_tokenless_configuration_refuses_to_arm(monkeypatch):
    clear_dispatch_env(monkeypatch)
    monkeypatch.setenv(DISPATCH_MODE_ENV, "github_actions")
    monkeypatch.setenv(ARMED_ENV, "1")
    monkeypatch.setenv(REPOSITORY_ENV, REPO)

    sent: list[httpx.Request] = []
    dispatcher = GitHubActionsRollbackDispatcher.from_env(client=make_client(recorder=sent))

    assert dispatcher is not None
    assert dispatcher.armed is False
    assert TOKEN_ENV in dispatcher.disarm_reason
    dispatcher.dispatch(make_action())
    assert sent == [], "a half-configured dispatcher must not fire"


# ------------------------------------------------------------ Armed, with a mock

def test_an_armed_dispatch_sends_exactly_the_request_that_was_built():
    sent: list[httpx.Request] = []
    dispatcher = GitHubActionsRollbackDispatcher(
        REPO, WORKFLOW, ref="release", token="ghp_test", armed=True,
        client=make_client(204, recorder=sent),
    )
    result = dispatcher.dispatch(make_action())

    assert len(sent) == 1
    request = sent[0]
    assert request.method == "POST"
    assert str(request.url) == EXPECTED_URL
    assert request.headers["Authorization"] == "Bearer ghp_test"
    assert request.headers["X-GitHub-Api-Version"] == "2022-11-28"

    import json

    body = json.loads(request.content)
    assert body["ref"] == "release"
    assert body["inputs"]["target_commit_sha"] == "3e9d10c4b2"
    assert result.state.value == "DISPATCH_ACCEPTED"
    assert "returned HTTP 204" in result.output
    assert "this is not completion" in result.output


def test_a_refused_dispatch_raises_with_the_status_and_the_body():
    dispatcher = GitHubActionsRollbackDispatcher(
        REPO, token="ghp_test", armed=True,
        client=make_client(404, body='{"message":"Not Found"}'),
    )
    with pytest.raises(RollbackDispatchError) as raised:
        dispatcher.dispatch(make_action())
    assert raised.value.status_code == 404
    assert "Not Found" in str(raised.value)


def test_a_transport_failure_is_reported_as_nothing_known_to_have_run():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("name resolution failed")

    dispatcher = GitHubActionsRollbackDispatcher(
        REPO, token="ghp_test", armed=True,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(RollbackDispatchError) as raised:
        dispatcher.dispatch(make_action())
    assert "Nothing is known to have run" in str(raised.value)


def test_a_202_is_not_treated_as_success():
    """GitHub answers workflow_dispatch with 204. Anything else is not acceptance."""
    dispatcher = GitHubActionsRollbackDispatcher(
        REPO, token="ghp_test", armed=True, client=make_client(202),
    )
    with pytest.raises(RollbackDispatchError):
        dispatcher.dispatch(make_action())


# ------------------------------------------------------------- Environment gate

def test_no_dispatcher_is_built_unless_the_environment_names_one(monkeypatch):
    clear_dispatch_env(monkeypatch)
    assert GitHubActionsRollbackDispatcher.from_env() is None


def test_an_unrecognised_dispatch_mode_builds_nothing(monkeypatch):
    clear_dispatch_env(monkeypatch)
    monkeypatch.setenv(DISPATCH_MODE_ENV, "argocd")
    assert GitHubActionsRollbackDispatcher.from_env() is None


def test_configuration_is_read_from_the_environment(monkeypatch):
    clear_dispatch_env(monkeypatch)
    monkeypatch.setenv(DISPATCH_MODE_ENV, "GitHub_Actions")  # case is not significant
    monkeypatch.setenv(REPOSITORY_ENV, REPO)
    monkeypatch.setenv(WORKFLOW_ENV, "revert.yml")
    monkeypatch.setenv(REF_ENV, "production")
    monkeypatch.setenv(TOKEN_ENV, "ghp_env")

    dispatcher = GitHubActionsRollbackDispatcher.from_env()
    assert dispatcher is not None
    assert (dispatcher.repository, dispatcher.workflow, dispatcher.ref) == (REPO, "revert.yml", "production")
    assert dispatcher.armed is False, "configured is not armed"
    assert ARMED_ENV in dispatcher.disarm_reason


def test_a_fully_configured_and_armed_environment_arms(monkeypatch):
    clear_dispatch_env(monkeypatch)
    monkeypatch.setenv(DISPATCH_MODE_ENV, "github_actions")
    monkeypatch.setenv(REPOSITORY_ENV, REPO)
    monkeypatch.setenv(TOKEN_ENV, "ghp_env")
    monkeypatch.setenv(ARMED_ENV, "yes")

    dispatcher = GitHubActionsRollbackDispatcher.from_env()
    assert dispatcher is not None and dispatcher.armed is True
    assert dispatcher.disarm_reason == ""
