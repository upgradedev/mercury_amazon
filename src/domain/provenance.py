"""Domain model for telemetry provenance.

Every report Mercury renders on the Fire TV wallboard carries the provenance of
the data behind it. The cockpit shows this verbatim so a viewer can always tell
a live reading from a recorded fixture without reading the code.
"""
from dataclasses import dataclass
from enum import Enum


class DataSource(str, Enum):
    """Where a telemetry report actually came from."""

    GITHUB_API = "github-api"
    AWS_COST_EXPLORER = "aws-cost-explorer"
    AWS_CLOUDWATCH = "aws-cloudwatch"
    OFFLINE_FIXTURE = "offline-fixture"

    @property
    def is_live(self) -> bool:
        return self is not DataSource.OFFLINE_FIXTURE


@dataclass(frozen=True)
class Provenance:
    """Provenance stamp attached to every telemetry report.

    Attributes:
        source: which backing system produced the numbers.
        detail: human readable explanation, including the reason a live call
            was not attempted or why it fell back to a fixture.
        observed_at_utc: ISO-8601 timestamp of when the data was read.
    """

    source: DataSource
    detail: str
    observed_at_utc: str

    @property
    def is_live(self) -> bool:
        return self.source.is_live

    @property
    def display_label(self) -> str:
        """Short label rendered on the 10-foot wallboard."""
        return "LIVE" if self.is_live else "OFFLINE FIXTURE"

    def to_dict(self) -> dict[str, str | bool]:
        return {
            "data_source": self.source.value,
            "detail": self.detail,
            "observed_at_utc": self.observed_at_utc,
            "is_live": self.is_live,
            "display_label": self.display_label,
        }


UNKNOWN_PROVENANCE = Provenance(
    source=DataSource.OFFLINE_FIXTURE,
    detail="Constructed in-process without a backing system.",
    observed_at_utc="",
)
