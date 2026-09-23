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
| A-09 | An anomaly with no commit in the window is reported as cannot-attribute, not as no-deploy | `tests/unit/test_incident_correlation.py` | Verdict is `ANOMALY_WITHOUT_ATTRIBUTION`, refusal reason `NO_CANDIDATE_IN_WINDOW`, no rollback is offered, and `nothing_to_revert` stays false |
| A-09b | An anomaly with several changes in the window names none of them | `tests/unit/test_incident_correlation.py`, `tests/unit/test_correlation_trial.py` | Refusal reason `WINDOW_TOO_CROWDED`, the candidate count is reported, no rollback is offered, and the spoken summary says rolling back on it would be a guess rather than that the changes are innocent |
| A-09g | Every refusal is worded as a refusal on every surface | `tests/unit/test_incident_correlation.py`, `tests/integration/test_mcp_endpoints.py`, `tests/e2e/test_refusal_wording.py` | `nothing_to_revert` is true only on `NO_ANOMALY`; the voice summary, the refusal statement, the cockpit page and the judge-facing documents contain none of the certainty phrasing the domain publishes as `REFUSAL_MUST_NOT_CLAIM`, and the list is proved to catch the retired wording |
| A-09c | A spike running for three polls is still detected | `tests/unit/test_correlation_trial.py` | The pre-onset baseline calls the identical series an anomaly that the trailing baseline calls healthy, and the trailing mode is still runnable so the before state is reproducible |
| A-09d | The attribution window ends at the onset, not at the reading | `tests/unit/test_incident_correlation.py` | A change 55 minutes before a reading whose spike began 20 minutes ago is inside the window; a change that landed after the onset is not |
| A-09e | The crowding gate buys precision on corpora it was not chosen on | `tests/unit/test_correlation_trial.py` | At two held-out seeds the gate raises naming precision and lowers recall and the namings count |
| A-09f | Every answer carries the measured worth of naming a commit | `tests/integration/test_mcp_endpoints.py`, `tests/unit/test_trial_summary.py` | `attribution.measured_accuracy` equals the recorded summary, and a checkout without that summary reports the accuracy as unknown rather than guessing |
| A-10 | A zero baseline does not manufacture an incident | `tests/unit/test_incident_correlation.py` | Verdict is `NO_ANOMALY` with factor 0.0 |
| A-10a | Git order cannot become a rollback target | `tests/unit/test_deployment_evidence.py`, `tests/integration/test_deployment_target_and_handoff.py` | An arbitrary SHA is refused; only the immediately preceding authenticated deployment marker with matching revision, digest and healthy readback can be staged |
| A-10b | A second responder can read shared state without overwriting newer work | `tests/unit/test_incident_handoff.py`, `tests/integration/test_deployment_target_and_handoff.py` | Responder, current action, confirmed facts and next step round-trip; a stale expected revision returns 409 |
| A-11 | Staging a rollback without the secret is refused | `tests/integration/test_rollback_authorization.py` | HTTP 401, and the response does not contain the secret |
| A-12 | A governance token works exactly once | `tests/integration/test_rollback_authorization.py` | A token replayed against a re-staged action returns 409 with `TOKEN_ALREADY_USED`; a second confirm of an executed action returns 409 with `NOT_PENDING` |
| A-13 | Editing the rollback target invalidates the token | `tests/integration/test_rollback_authorization.py` | HTTP 403 with `TOKEN_CONTENT_MISMATCH` |
| A-14 | A forged token is refused | `tests/integration/test_rollback_authorization.py` | HTTP 403 with `BAD_SIGNATURE` |
| A-15 | An expired lease is refused | `tests/integration/test_rollback_authorization.py` | HTTP 410 with `LEASE_EXPIRED` |
| A-16 | Every telemetry response declares its provenance | `tests/integration/test_mcp_endpoints.py` | `data_source`, `detail` and `is_live` present on each report |
| A-17 | Fixture mode is labelled as fixture mode | `tests/integration/test_mcp_endpoints.py` | `display_label` is `OFFLINE FIXTURE` when no token is set |
| A-17b | The fixture label is on the same screenful as the number it qualifies | `tests/ux/test_ten_foot_legibility.py` | At 1920x1080 a provenance stamp reading `OFFLINE FIXTURE` or `LIVE` renders inside the first viewport height, measured in Chromium |
| A-17c | Every file the Android build script names exists | `tests/unit/test_firetv_app_structure.py` | `app/proguard-rules.pro` and every other path named in `app/build.gradle.kts` is present, so the release variant configures |
| A-17d | The Fire TV readiness gate cannot pass on a string match | `tests/unit/test_readiness_gates.py` | J4 requires a gradle exit code, an APK that exists and a recorded device launch; every missing field is driven through the predicate |
| A-17e | The Fire TV build receipt cannot be written without evidence | `tests/unit/test_write_firetv_receipt.py` | `scripts/write_firetv_receipt.py` refuses, writes nothing and exits 2 on a missing, empty or non-zip APK, a zip with no `AndroidManifest.xml`, an APK outside the checkout, a non-zero gradle or adb exit code, or an empty device description; the receipt it does write hashes the APK itself and passes the gate's own predicate |
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
| M-03 | A push runs `.github/workflows/android.yml`, which assembles and uploads `app-debug.apk` | **Passed.** Run `35500282701` executed JVM tests and assemble, then uploaded artifact `10601069697`; downloaded SHA-256 matched the log | Use that artifact for M-01/M-02, then write the device receipt with `python scripts/write_firetv_receipt.py` |
| M-04 | Text is legible from three metres on a large screen | No television was available | Open the cockpit on a TV at 1080p and read it from a sofa |
| M-05 | A real CloudWatch 5xx spike is correlated to a real deployment | No monitored service exists to produce one | Point `MERCURY_SIMULATE_INCIDENT=0` at a real load balancer with AWS credentials |
| M-06 | A rollback reaches a deployment pipeline | The default dispatcher records locally. The GitHub Actions dispatcher exists but has never been fired and stays disarmed unless three variables are set | Set `MERCURY_ROLLBACK_DISPATCH`, `MERCURY_ROLLBACK_REPO`, `GITHUB_TOKEN` and `MERCURY_ROLLBACK_DISPATCH_ARMED`, against a repository that has the workflow |
| M-07 | The public cockpit answers and reports its deployed commit | **Passed for the web cockpit.** Root and `/health` answer; the latter publishes `build_sha` | `python scripts/probe_deployment.py` |
| M-08 | Two responders resume from the TV state faster or with fewer omissions than the laptop dashboard | No comparative responder session has been run | Run the same incident once with the shared handoff panel and once with the existing dashboard; record recap time, omissions and preference |

If you run any of these, `.github/ISSUE_TEMPLATE/firetv_device_report.yml` is the
place to report what happened, whether it worked or not.

---

## 3. Exit criteria

| Criterion | Status | Evidence |
|---|---|---|
| Automated suite green | Met | `python -m pytest tests/ -q`, 544 passed |
| Line coverage at or above 85 percent | Met | `python scripts/record_coverage_summary.py`, 93 percent of 1646 statements |
| Every rollback denial reason has a failing-input test | Met | 10 distinct denial reasons asserted in `tests/integration/test_rollback_authorization.py`, counted by `python ci/readiness.py` at gate I5 |
| Readiness gates with no blocking failure | Met | `python ci/readiness.py`, 44/53 passed, 0 blocking |
| A Fire TV binary that somebody has watched run | **Not met** | A verified APK exists, but gate J4 still fails because there is no `firetv_build_receipt.json` and no device observation |
| Verified on a Fire TV device | **Not met** | No hardware run has taken place |
| Verified against a live web deployment | Met | Root and `/health` answer; the deployment publishes its build SHA |
