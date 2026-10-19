"""The switches that decide which adapters may make a live call.

``MERCURY_OFFLINE=1`` still means what it always meant: no adapter makes an
outbound call, whatever credentials happen to be lying around on the machine. The
test suite sets it so runs are deterministic and never spend money on a Cost
Explorer request, and it gives a judge a way to see the whole cockpit behave
identically on any laptop.

Two narrower opt-ins make one source live **even when** ``MERCURY_OFFLINE=1`` is
set, so a deployment can run as a hybrid: real data where it is safe to publish,
labelled fixtures everywhere else.

``MERCURY_LIVE_CLOUDWATCH=1``
    Reads the hackathon's own production Lambda functions
    (:data:`src.infrastructure.cloudwatch_adapter.LIVE_PRODUCTION_FUNCTIONS`) from
    CloudWatch, ``AWS/Lambda`` ``Errors`` with ``Invocations`` beside it. Only those
    names. The four simulated incident services and any other name keep their
    offline behaviour, so the rollback demo is unchanged.
``MERCURY_LIVE_GITHUB=1``
    Reads the DORA report and the pull request radar from the GitHub REST API,
    unauthenticated when no ``GITHUB_TOKEN`` is set, behind an in-process cache.
    It does not open the incident correlator's commit feed, which stays on its
    recorded path, so the rollback demo is unchanged.

There is deliberately no switch for Cost Explorer. It reports the whole AWS
account's bill, so under ``MERCURY_OFFLINE=1`` it is always the labelled fixture.

None of these can make a fixture look live: a switch only allows a live call, and
what that call returns is labelled by its own provenance.
"""
import os

ENV_VAR = "MERCURY_OFFLINE"
LIVE_CLOUDWATCH_ENV = "MERCURY_LIVE_CLOUDWATCH"
LIVE_GITHUB_ENV = "MERCURY_LIVE_GITHUB"
_TRUE_VALUES = {"1", "true", "yes", "on"}


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in _TRUE_VALUES


def offline_mode_enabled() -> bool:
    """True when MERCURY_OFFLINE asks every adapter to skip its live call."""
    return _flag(ENV_VAR)


def live_cloudwatch_enabled() -> bool:
    """True when MERCURY_LIVE_CLOUDWATCH opts the production Lambda rows into live reads."""
    return _flag(LIVE_CLOUDWATCH_ENV)


def live_github_enabled() -> bool:
    """True when MERCURY_LIVE_GITHUB opts the DORA and PR radar reads into live calls."""
    return _flag(LIVE_GITHUB_ENV)


OFFLINE_REASON = (
    f"{ENV_VAR} is set, so no live call was attempted."
)
