"""Which files a service is built from, so a change can be read against it.

A regression in a running service's error rate has to come from something the service
runs: its code, the files it serves, or the definition of how it is built and deployed.
A commit that changed only tests, prose or the video plan did not change any of those.
This module answers one narrow question about a commit, from its file list alone: did it
touch a file this service is built from?

Three answers, and the third matters:

* ``True``: at least one changed file is one the service is built from.
* ``False``: every changed file is outside that set. The correlator the server wires
  (``src/interfaces/mcp_server.py``) does not count such a commit as a candidate: a
  change that touches no runtime file deployed no code. That is a reading of its file list, not a finding that the
  change is harmless, and every surface that mentions it says so.
* ``None``: the file list is unknown (the GitHub commits API does not return one, and a
  recording may lack it). An unknown commit stays a candidate, exactly as before this
  module existed, so missing data can never make Mercury more willing to name a change.

The set below is Mercury's own, derived from what ships, not tuned: the files the
``Dockerfile`` copies into the image and ``scripts/build_lambda_package.py`` packs into the
Lambda zip, plus the files that define how that artefact is built and deployed.
``tests/unit/test_change_scope.py`` parses both and fails if either ships a path this set
does not cover. A different service would declare its own set.
"""
from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase

#: What Mercury's server artefact is built from. Patterns are ``fnmatch`` style over
#: repository-relative POSIX paths; ``*`` also crosses ``/``.
MERCURY_SERVICE_PATTERNS: tuple[str, ...] = (
    # What the image and the zip contain.
    "src/*",
    "docs/index.html",
    "docs/firetv_nav.js",
    "docs/webmcp_bridge.js",
    "docs/manifest.json",
    "docs/*.woff2",
    "docs/OFL-*.txt",
    "correlation_trial_summary.json",
    "attribution_holdout_summary.json",
    # How the artefact is built and deployed. A change here can change what runs.
    "pyproject.toml",
    "Dockerfile",
    "docker-compose.yml",
    "scripts/build_lambda_package.py",
    "scripts/terraform_cycle.py",
    "infra/*",
    ".github/workflows/terraform-cycle.yml",
)


@dataclass(frozen=True)
class ServiceScope:
    """A named set of path patterns a service is built from."""

    name: str
    patterns: tuple[str, ...]

    def covers(self, path: str) -> bool:
        normalised = path.replace("\\", "/")
        if normalised.startswith("./"):
            normalised = normalised[2:]
        return any(fnmatchcase(normalised, pattern) for pattern in self.patterns)

    def touches(self, paths: tuple[str, ...] | None) -> bool | None:
        """True, False, or None when the file list is unknown or empty."""
        if not paths:
            return None
        return any(self.covers(path) for path in paths)

    def runtime_files(self, paths: tuple[str, ...] | None) -> list[str] | None:
        """The listed files this scope covers, or None when the file list is unknown."""
        if not paths:
            return None
        return [path for path in paths if self.covers(path)]

    def describe(self) -> dict[str, object]:
        """What counts as a deploy candidate, as the server states it beside an answer."""
        return {
            "name": self.name,
            "runtime_paths": list(self.patterns),
            "rule": (
                "A commit counts as a deploy candidate only when it changed at least one of "
                "these paths, the files the server is built from. A commit that changed none of "
                "them deploys no code and is set aside; that is a reading of its file list, not "
                "a finding that it is harmless. A commit whose file list is unknown (its per-commit "
                "read failed or hit the endpoint's cap) stays a candidate."
            ),
            "defined_in": "src/domain/change_scope.py",
        }


MERCURY_SERVICE_SCOPE = ServiceScope(name="mercury-server", patterns=MERCURY_SERVICE_PATTERNS)
