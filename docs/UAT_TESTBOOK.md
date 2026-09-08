# Acceptance testbook

**Product:** Mercury Fire TV Incident Commander
**Persona:** the on-call engineer holding the remote during a production incident.

Each scenario below is either **Automated** and names the test that covers it, or
**Manual, not executed** and says why. Nothing here claims a result that was not
observed. Run `python -m pytest tests/ -q` to execute every automated row.

---

## 1. Automated scenarios

| ID | Scenario | Covered by | What the test asserts |
|---|---|---|---|
| A-01 | D-pad moves focus to the control that is actually in the pressed direction, on a grid | `tests/e2e/spatial_nav_spec.js` (run by `test_spatial_navigation_spec_passes`) | Down from a grid centre lands below, not on the next DOM sibling; a nearer candidate beats a farther one; perpendicular drift is penalised |
| A-02 | Focus holds at an edge instead of wrapping | `tests/e2e/spatial_nav_spec.js` | Up at the top row and Left at the left column keep focus where it is |
| A-03 | The remote and a desktop keyboard produce identical focus | `tests/e2e/spatial_nav_spec.js` | `navigateDpad('DOWN')` and a synthetic `ArrowDown` keydown land on the same element |
| A-04 | Only one focus system exists | `tests/e2e/test_html_structure.py` | The page registers zero keydown handlers; the navigation script registers exactly one |
| A-05 | The cockpit calls its own API rather than painting literals | `tests/e2e/test_html_structure.py` | `fetch(` is present and all eight endpoints are referenced; no fabricated telemetry number appears in the markup |
| A-06 | DORA tiers are computed correctly from metrics | `tests/unit/test_dora_metrics.py` | Elite and Medium tier boundaries |
| A-07 | DORA metrics are derived from real GitHub payload shapes | `tests/unit/test_github_adapter.py` | Deployment frequency, lead time, change failure rate and recovery time against a constructed payload; in-progress runs excluded |
| A-08 | Spend anomalies are detected and sub-threshold rises are not | `tests/unit/test_aws_adapters.py` | A 300 percent day-over-average jump flags; a 10 percent rise does not |
| A-09 | An anomaly with no nearby commit blames nothing | `tests/unit/test_incident_correlation.py` | Verdict is `ANOMALY_WITHOUT_ATTRIBUTION`, refusal reason `NO_CANDIDATE_IN_WINDOW`, and no rollback is offered |
| A-09b | An anomaly with several changes in the window blames none of them | `tests/unit/test_incident_correlation.py`, `tests/unit/test_correlation_trial.py` | Refusal reason `WINDOW_TOO_CROWDED`, the candidate count is reported, no rollback is offered, and the spoken summary says not to roll back |
| A-09c | A spike running for three polls is still detected | `tests/unit/test_correlation_trial.py` | The pre-onset baseline calls the identical series an anomaly that the trailing baseline calls healthy, and the trailing mode is still runnable so the before state is reproducible |
| A-09d | The attribution window ends at the onset, not at the reading | `tests/unit/test_incident_correlation.py` | A change 55 minutes before a reading whose spike began 20 minutes ago is inside the window; a change that landed after the onset is not |
| A-09e | The crowding gate buys precision on corpora it was not chosen on | `tests/unit/test_correlation_trial.py` | At two held-out seeds the gate raises naming precision and lowers recall and the namings count |
| A-09f | Every answer carries the measured worth of naming a commit | `tests/integration/test_mcp_endpoints.py`, `tests/unit/test_trial_summary.py` | `attribution.measured_accuracy` equals the recorded summary, and a checkout without that summary reports the accuracy as unknown rather than guessing |
| A-10 | A zero baseline does not manufacture an incident | `tests/unit/test_incident_correlation.py` | Verdict is `NO_ANOMALY` with factor 0.0 |
| A-11 | Staging a rollback without the secret is refused | `tests/integration/test_rollback_authorization.py` | HTTP 401, and the response does not contain the secret |
| A-12 | A governance token works exactly once | `tests/integration/test_rollback_authorization.py` | Second use returns 409 with `TOKEN_ALREADY_USED` |
| A-13 | Editing the rollback target invalidates the token | `tests/integration/test_rollback_authorization.py` | HTTP 403 with `TOKEN_CONTENT_MISMATCH` |
| A-14 | A forged token is refused | `tests/integration/test_rollback_authorization.py` | HTTP 403 with `BAD_SIGNATURE` |
| A-15 | An expired lease is refused | `tests/integration/test_rollback_authorization.py` | HTTP 410 with `LEASE_EXPIRED` |
| A-16 | Every telemetry response declares its provenance | `tests/integration/test_mcp_endpoints.py` | `data_source`, `detail` and `is_live` present on each report |
| A-17 | Fixture mode is labelled as fixture mode | `tests/integration/test_mcp_endpoints.py` | `display_label` is `OFFLINE FIXTURE` when no token is set |
| A-17b | The fixture label is on the same screenful as the number it qualifies | `tests/ux/test_ten_foot_legibility.py` | At 1920x1080 a provenance stamp reading `OFFLINE FIXTURE` or `LIVE` renders inside the first viewport height, measured in Chromium |
| A-17c | Every file the Android build script names exists | `tests/unit/test_firetv_app_structure.py` | `app/proguard-rules.pro` and every other path named in `app/build.gradle.kts` is present, so the release variant configures |
| A-17d | The Fire TV readiness gate cannot pass on a string match | `tests/unit/test_readiness_gates.py` | J4 requires a gradle exit code, an APK that exists and a recorded device launch; every missing field is driven through the predicate |
| A-18 | Running the suite makes no billable AWS call | `tests/unit/test_aws_adapters.py` plus `tests/conftest.py` | `MERCURY_OFFLINE=1` suppresses the call even when a working client is injected |
| A-19 | The Fire TV manifest is a TV manifest | `tests/unit/test_firetv_app_structure.py` | Leanback required, touchscreen not required, `LEANBACK_LAUNCHER` present, no `package` attribute |
| A-20 | A hostile cockpit URL cannot redirect the WebView | `app/src/test/kotlin/.../CockpitUrlResolverTest.kt` | `javascript:`, `file:`, `content:` and embedded whitespace all fall back to the safe default |
| A-21 | Log output masks credentials and emails | `tests/unit/test_observability_harness.py` | Email addresses and tokens are replaced before emission |
| A-22 | The asset route cannot be walked out of `docs/` | `tests/integration/test_mcp_endpoints.py` | Encoded traversal returns 404 |

---

## 2. Manual scenarios, not executed

These need hardware, a network or a person, and none of them has been performed.
They are listed so the gap is explicit rather than absent.

| ID | Scenario | Why it has not been run | How to run it |
|---|---|---|---|
| M-01 | The APK installs on a Fire TV Stick and appears on the home row | No Fire TV hardware was available | `docs/FIRE_TV_BUILD.md`, install section |
| M-02 | The physical remote D-pad drives focus on a television | No Fire TV hardware was available | Install the APK, press the D-pad |
| M-03 | The app runs in the Fire TV emulator | No Android SDK in the build environment | `docs/FIRE_TV_BUILD.md`, emulator section |
| M-04 | Text is legible from three metres on a large screen | No television was available | Open the cockpit on a TV at 1080p and read it from a sofa |
| M-05 | A real CloudWatch 5xx spike is correlated to a real deployment | No monitored service exists to produce one | Point `MERCURY_SIMULATE_INCIDENT=0` at a real load balancer with AWS credentials |
| M-06 | A rollback reaches a deployment pipeline | The default dispatcher records locally. The GitHub Actions dispatcher exists but has never been fired and stays disarmed unless three variables are set | Set `MERCURY_ROLLBACK_DISPATCH`, `MERCURY_ROLLBACK_REPO`, `GITHUB_TOKEN` and `MERCURY_ROLLBACK_DISPATCH_ARMED`, against a repository that has the workflow |
| M-07 | The deployment answers at the submitted commit | No deploy of the current commit has been run | `terraform apply`, then `python scripts/probe_deployment.py` |

If you run any of these, `.github/ISSUE_TEMPLATE/firetv_device_report.yml` is the
place to report what happened, whether it worked or not.

---

## 3. Exit criteria

| Criterion | Status | Evidence |
|---|---|---|
| Automated suite green | Met | `python -m pytest tests/ -q`, 440 passed |
| Line coverage at or above 85 percent | Met | `python scripts/record_coverage_summary.py`, 94 percent of 1318 statements |
| Every rollback denial reason has a failing-input test | Met | 9 distinct denial reasons asserted in `tests/integration/test_rollback_authorization.py`, counted by `python ci/readiness.py` at gate I5 |
| Readiness gates with no blocking failure | Met | `python ci/readiness.py`, 44/53 passed, 0 blocking |
| A Fire TV binary that somebody has watched run | **Not met** | Gate J4 fails: no `firetv_build_receipt.json`, no APK, no device |
| Verified on a Fire TV device | **Not met** | No hardware run has taken place |
| Verified against a live deployment of this commit | **Not met** | Gates D2 and G2 fail |
