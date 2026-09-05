# Contributing to Mercury

Thanks for looking. This file is short on purpose: it covers how to run the thing,
what a pull request is checked against, and the one house rule that is not
negotiable.

## The house rule

**Never write a number, a status or a label that the code does not produce.**

Mercury renders telemetry on a television during an incident. If a reading says
`LIVE` it must have come from a live call, and if it came from a fixture the
screen must say so. Concretely, in this repository:

* Every telemetry report carries a `Provenance` (`src/domain/provenance.py`) and
  the interface layer surfaces it. A new adapter must set one.
* A fallback path states why it fell back, in the text the user sees.
* A benchmark number in a document names the command that prints it.
* A capability and its limitation belong in the same sentence.

A test that asserts a control refuses is worth more here than a test that asserts
it works. Both are welcome; do not skip the first.

## Getting set up

```bash
git clone https://github.com/upgradedev/mercury_amazon.git
cd mercury_amazon
pip install -e ".[dev]"
```

Python 3.11 or newer. Node is optional and only needed for the spatial navigation
spec. The Android SDK is optional and only needed to build the APK locally.

## Running everything

```bash
python -m pytest tests/ -q                                    # the suite
python -m pytest tests/ --cov=src --cov-fail-under=85         # with the coverage floor
node tests/e2e/spatial_nav_spec.js                            # D-pad geometry, real code
python -m ruff check src/ tests/ scripts/ ci/ --ignore E501   # lint
python ci/readiness.py                                        # standards gate audit
./gradlew :app:testDebugUnitTest                              # Kotlin units, needs a JDK
```

The test suite sets `MERCURY_OFFLINE=1`, so running it never makes an outbound
call and never issues a billable AWS Cost Explorer request, whatever credentials
your machine happens to have configured.

## Layout

```
src/domain/           Pure models. Imports no SDK and no framework, and a gate checks that.
src/application/      Use cases depending on protocols, never on concrete adapters.
src/infrastructure/   Adapters: GitHub, Cost Explorer, CloudWatch, local git.
src/interfaces/       The HTTP server.
docs/                 The cockpit page and its scripts, plus written documentation.
app/                  The Fire TV Leanback Android application.
tests/                unit, integration, e2e, security, load, performance.
ci/                   The standards readiness auditor.
scripts/              Benchmark, fixture recorder, deployment probe, security audit.
```

`docs/` is served both by GitHub Pages and by the Python server, so the cockpit
page exists exactly once and cannot drift between the two.

## Adding a data source

1. Add the model to `src/domain` if it needs one. No SDK imports.
2. Write the adapter in `src/infrastructure`. It must return a `Provenance`, must
   have a fallback, and its fallback must say why it fell back.
3. Test the live path with a stub or an `httpx.MockTransport`, and test the
   fallback path separately. Assert on the provenance, not only the numbers.
4. Surface it in `src/interfaces/mcp_server.py` with `provenance.to_dict()`.
5. Render it in `docs/index.html` through `provenanceBlock()`.

## Pull requests

CI runs on every pull request to `master` and `main`:

* `ruff` over `src/` and `tests/`
* the full pytest suite with `--cov-fail-under=85`
* a wheel and sdist build
* `python ci/readiness.py`

`.github/workflows/android.yml` additionally assembles the APK and runs the
Kotlin unit tests when anything under `app/`, `gradle/` or the Gradle files
changes.

Keep the readiness auditor honest. If a gate fails, fix the thing it is measuring.
Changing the check so that it passes is the one change that will be rejected on
sight.

## Commit messages

Conventional-commit prefixes (`feat:`, `fix:`, `docs:`, `test:`, `chore:`) with a
scope where it helps. Say what changed and why; the diff already says how.

## Reporting a security issue

Do not open a public issue for a vulnerability in the rollback governance path.
Email the maintainer listed in the repository metadata instead.
