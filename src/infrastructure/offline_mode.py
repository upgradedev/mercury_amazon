"""The single switch that forces every adapter into fixture mode.

Set ``MERCURY_OFFLINE=1`` to stop Mercury making any outbound call, whatever
credentials happen to be lying around on the machine. The test suite sets it so
runs are deterministic and never spend money on a Cost Explorer request, and it
gives a judge a way to see the whole cockpit behave identically on any laptop.

It only ever suppresses a live call. It can never make a fixture look live.
"""
import os

ENV_VAR = "MERCURY_OFFLINE"
_TRUE_VALUES = {"1", "true", "yes", "on"}


def offline_mode_enabled() -> bool:
    """True when MERCURY_OFFLINE asks every adapter to skip its live call."""
    return os.environ.get(ENV_VAR, "").strip().lower() in _TRUE_VALUES


OFFLINE_REASON = (
    f"{ENV_VAR} is set, so no live call was attempted."
)
