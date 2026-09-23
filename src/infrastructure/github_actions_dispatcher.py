"""Infrastructure Adapter: dispatch a governed rollback to GitHub Actions.

This is the first :class:`~src.application.governed_rollback_use_case.RollbackDispatcher`
that contacts something outside the process. It asks one GitHub Actions workflow
to run, through the ``workflow_dispatch`` REST endpoint, carrying the rollback's
own fields as workflow inputs.

Three properties matter more than the feature:

Env-gated
    Nothing here is reachable unless ``MERCURY_ROLLBACK_DISPATCH`` names it.
    :meth:`GitHubActionsRollbackDispatcher.from_env` returns ``None`` otherwise,
    and the use case falls back to the record-only dispatcher it has always had.

Dry run by default
    Being configured is not being armed. Without ``MERCURY_ROLLBACK_DISPATCH_ARMED``
    the dispatcher builds the exact request and returns a description of it
    without opening a socket. Arming additionally requires a token and a target,
    and a half-configured deployment stays disarmed and says which piece is
    missing rather than firing something partial.

Fail closed and legible
    A dispatch that is attempted and does not succeed raises
    :class:`RollbackDispatchError`, which the HTTP layer turns into a 502. The
    governance nonce has already been spent by then, so the action cannot be
    confirmed again: the operator stages a new one. That is the same fail-closed
    posture the governance domain takes.

**This dispatcher has never been fired.** Every test drives it through
``httpx.MockTransport`` and asserts the exact request it would send. No request
has been made to github.com from this repository, because doing so needs a token
with ``actions:write`` on a repository that has the workflow, and neither exists
here.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import httpx

from src.domain.governed_rollback import GovernedRollbackAction

GITHUB_API_ROOT = "https://api.github.com"
DISPATCH_MODE_ENV = "MERCURY_ROLLBACK_DISPATCH"
DISPATCH_MODE_GITHUB_ACTIONS = "github_actions"
ARMED_ENV = "MERCURY_ROLLBACK_DISPATCH_ARMED"
REPOSITORY_ENV = "MERCURY_ROLLBACK_REPO"
WORKFLOW_ENV = "MERCURY_ROLLBACK_WORKFLOW"
REF_ENV = "MERCURY_ROLLBACK_REF"
TOKEN_ENV = "GITHUB_TOKEN"
DEFAULT_WORKFLOW = "rollback.yml"
DEFAULT_REF = "main"
_TRUE_VALUES = {"1", "true", "yes", "on"}


class RollbackDispatchError(RuntimeError):
    """Raised when an armed dispatch was attempted and did not succeed."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class DispatchRequest:
    """The exact HTTP request a dispatch would issue.

    Built separately from sending it so the shape can be asserted by a test that
    never opens a socket, and so the dry run can describe a real request rather
    than a summary of one.
    """

    method: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    json_body: dict[str, Any] = field(default_factory=dict)

    def redacted_headers(self) -> dict[str, str]:
        """Headers with the bearer token replaced, safe to print or log."""
        return {
            name: ("Bearer <redacted>" if name.lower() == "authorization" else value)
            for name, value in self.headers.items()
        }

    def describe(self) -> str:
        inputs = ", ".join(f"{k}={v}" for k, v in sorted(self.json_body.get("inputs", {}).items()))
        return f"{self.method} {self.url} ref={self.json_body.get('ref')} inputs({inputs})"


class GitHubActionsRollbackDispatcher:
    """Asks one GitHub Actions workflow to run, carrying the rollback's fields.

    Args:
        repository: ``owner/name`` holding the rollback workflow.
        workflow: workflow file name, for example ``rollback.yml``.
        ref: git ref the workflow runs on.
        token: token with ``actions:write`` on ``repository``.
        armed: send the request. When false, :meth:`dispatch` describes the
            request and sends nothing.
        client: injected ``httpx.Client``. The test suite passes one backed by
            ``httpx.MockTransport`` so the request building executes for real.
        disarm_reason: why arming was refused, carried into the output.
    """

    def __init__(
        self,
        repository: str,
        workflow: str = DEFAULT_WORKFLOW,
        ref: str = DEFAULT_REF,
        token: str = "",
        armed: bool = False,
        client: httpx.Client | None = None,
        timeout: float = 10.0,
        disarm_reason: str = "",
    ) -> None:
        self.repository = repository
        self.workflow = workflow
        self.ref = ref
        self.token = token
        self.armed = armed
        self.disarm_reason = disarm_reason
        self._client = client
        self._timeout = timeout

    # ------------------------------------------------------------ Construction

    @classmethod
    def from_env(cls, client: httpx.Client | None = None) -> "GitHubActionsRollbackDispatcher | None":
        """Build from the environment, or return None when not selected.

        Returning ``None`` rather than a disabled object is deliberate: the use
        case then keeps its record-only default, and nothing about the response
        changes for a deployment that never asked for a dispatcher.
        """
        if os.environ.get(DISPATCH_MODE_ENV, "").strip().lower() != DISPATCH_MODE_GITHUB_ACTIONS:
            return None

        repository = os.environ.get(REPOSITORY_ENV, "").strip()
        workflow = os.environ.get(WORKFLOW_ENV, "").strip() or DEFAULT_WORKFLOW
        ref = os.environ.get(REF_ENV, "").strip() or DEFAULT_REF
        token = os.environ.get(TOKEN_ENV, "").strip()
        wants_arming = os.environ.get(ARMED_ENV, "").strip().lower() in _TRUE_VALUES

        missing = [name for name, value in ((REPOSITORY_ENV, repository), (TOKEN_ENV, token)) if not value]
        if not wants_arming:
            disarm_reason = f"{ARMED_ENV} is not set, so this dispatch is a dry run."
        elif missing:
            disarm_reason = (
                f"{ARMED_ENV} is set but {' and '.join(missing)} is not, so nothing was sent."
            )
        else:
            disarm_reason = ""

        return cls(
            repository=repository,
            workflow=workflow,
            ref=ref,
            token=token,
            armed=wants_arming and not missing,
            client=client,
            disarm_reason=disarm_reason,
        )

    # ------------------------------------------------------------ Request shape

    def build_request(self, action: GovernedRollbackAction) -> DispatchRequest:
        """Build the workflow_dispatch request for this action.

        Pure. Sends nothing, and is what the shape tests assert against.
        """
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "mercury-firetv-cockpit",
            "Content-Type": "application/json",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        return DispatchRequest(
            method="POST",
            url=(
                f"{GITHUB_API_ROOT}/repos/{self.repository}/actions/workflows/"
                f"{self.workflow}/dispatches"
            ),
            headers=headers,
            # Every input is a string: workflow_dispatch inputs are strings on
            # the wire whatever their declared type.
            json_body={
                "ref": self.ref,
                "inputs": {
                    "action_id": action.action_id,
                    "target_service": action.target_service,
                    "target_commit_sha": action.target_commit_sha,
                    "reason": action.reason,
                    "payload_hash": action.payload_hash,
                },
            },
        )

    # ------------------------------------------------------------------ Dispatch

    def dispatch(self, action: GovernedRollbackAction) -> str:
        """Send the workflow_dispatch request, or describe it and send nothing."""
        request = self.build_request(action)

        if not self.armed:
            return (
                f"Governance passed for '{action.target_service}' to commit "
                f"{action.target_commit_sha[:8]}. DRY RUN: no request was sent. The request this "
                f"deployment would have sent is {request.describe()} with headers "
                f"{request.redacted_headers()}. {self.disarm_reason} Set {ARMED_ENV}=1 with "
                f"{REPOSITORY_ENV} and {TOKEN_ENV} to arm it."
            )

        client = self._client or httpx.Client(timeout=self._timeout)
        owns_client = self._client is None
        try:
            response = client.post(request.url, headers=request.headers, json=request.json_body)
        except httpx.HTTPError as exc:
            raise RollbackDispatchError(
                f"The rollback dispatch to {request.url} failed before a response was read "
                f"({type(exc).__name__}: {exc}). Nothing is known to have run."
            ) from exc
        finally:
            if owns_client:
                client.close()

        if response.status_code != 204:
            raise RollbackDispatchError(
                f"GitHub refused the workflow dispatch with HTTP {response.status_code}: "
                f"{response.text[:300]}",
                status_code=response.status_code,
            )

        return (
            f"Governance passed for '{action.target_service}' to commit "
            f"{action.target_commit_sha[:8]}. Dispatched to GitHub Actions: {request.describe()} "
            f"returned HTTP {response.status_code}. GitHub accepted the request; whether the "
            f"workflow itself succeeds is visible in that repository's Actions tab, not here."
        )
