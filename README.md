# Mercury: what broke, what changed, and a governed rollback

> **Mercury tells an on-call engineer which change broke production, or refuses to name one, and puts the rollback behind four governance conditions.** It reads a real commit history against an error metric, publishes how often that attribution is right, and renders on a Fire TV as one of its screens.

```mermaid
flowchart LR
    Q["Someone asks:<br/>what broke?"]
    Q --> M["1. What broke<br/>the error rate against<br/>its own baseline"]
    M --> C["2. What changed<br/>the closest commit that<br/>landed before the reading"]
    C --> R["3. Governed rollback,<br/>refused unless four<br/>conditions hold"]
    M -.->|reading is inside baseline| N["Mercury names no commit<br/>and offers no rollback"]
    C -.->|no deploy landed close enough| N
    C -.->|more than one change in the window| A["Mercury names the closest<br/>and says it is one of several"]
```

The dotted paths are the point as much as the solid one, and they are the ones
that were measured. `python scripts/correlation_trial.py` scores the correlator
against 1160 labelled incidents and publishes both what it gets right and what it
gets wrong: see [How often it is right](#how-often-it-is-right), which is the
least flattering section in this file and the one to read first.

Mercury answers on load. Each number on the screen carries a badge saying whether
it was read live or served from a recording, and every attribution says how many
changes it had to choose between.

### Run it

```bash
git clone https://github.com/upgradedev/mercury_amazon.git
cd mercury_amazon
pip install -e ".[dev]"
python -m pytest tests/ -q
python -m src.interfaces.mcp_server
```

Open `http://127.0.0.1:8002/`. No credentials and no AWS account are needed: the
commits are read from the checkout you just cloned, the metric series is simulated
and labelled as simulated on screen, and the server prints an ephemeral governance
secret to its log for you to paste into the cockpit. The test run takes 24.8 to
25.7 seconds (three wall-clock runs of `python -m pytest tests/ -q` on the
development machine, timed around the subprocess). The `pip install` before it dominates the total and depends on your
network; a clean-environment install here ran past ten minutes, so budget for that
rather than for a fast one. On PowerShell, set the secret with
`$env:MERCURY_ROLLBACK_SECRET = "pick-any-string"` before the last line if you
would rather choose it yourself. Full detail in [Quickstart](#quickstart).

[![CI](https://github.com/upgradedev/mercury_amazon/actions/workflows/ci.yml/badge.svg)](.github/workflows/ci.yml)
[![Tests](https://img.shields.io/badge/tests-345%20collected-brightgreen.svg)](tests/)
[![Coverage](https://img.shields.io/badge/coverage-93%25-brightgreen.svg)](.github/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**No APK exists.** The Android build is
[`.github/workflows/android.yml`](.github/workflows/android.yml), a plain file link
and deliberately not a status badge: that workflow **has never executed**, nothing
has been pushed since it was added, and a green build badge over zero runs is the
kind of thing a five second scan reads as a shipped app. Detail in
[Fire TV](#fire-tv).

The CI badge points at a repository that is currently **private**, so that badge
will not resolve for anyone outside the organisation until it is made public. It is
listed here because the workflow it names is in this repository and can be read
directly. The other three badges are static and describe values you can reproduce
with the commands in [Measured numbers](#measured-numbers).

---

## Table of Contents

1. [What this is](#what-this-is)
2. [What is real and what is simulated](#what-is-real-and-what-is-simulated)
3. [How often it is right](#how-often-it-is-right)
4. [Architecture](#architecture)
5. [The rollback is the point](#the-rollback-is-the-point)
6. [Quickstart](#quickstart)
7. [Fire TV](#fire-tv)
8. [Measured numbers](#measured-numbers)
9. [Configuration](#configuration)
10. [Known limitations](#known-limitations)
11. [Who would buy this, and why](#who-would-buy-this-and-why)
12. [Contributing and licence](#contributing-and-licence)

---

## What this is

During a production incident the useful information is scattered across a version
control host, a metrics console and a deployment pipeline. The question that
matters is one question: which change did this, and can it be undone safely. The
asset in this repository is the engine that answers it, scored against a labelled
corpus rather than demonstrated once.

The screen is a delivery choice, not the product. Mercury renders on a Fire TV in
a room, and on a laptop browser, from the same HTTP surface and the same page: the
D-pad ring and the arrow keys are one code path. It is entered in the Fire TV track
because the ten-foot surface is built, measured and honest about what has not been
run, and the section on it says exactly what has not.

Three things it does:

**Answers "what changed?"** `POST /mcp/tools/what_changed` reads an error metric
series and a commit history, decides whether the newest reading is an anomaly
against its own baseline, and attributes it to the closest commit that landed
before it. When it cannot attribute the anomaly to anything, it says so and
offers no rollback. That refusal is a feature, and it has its own tests. When more
than one change sits inside the attribution window it names the closest and says
how many others there were, because every wrong answer it gave against the labelled
corpus that it could have got right was a window like that.

**Shows engineering velocity and spend.** `POST /mcp/tools/get_dora_velocity_report`,
`POST /mcp/tools/get_pr_bottlenecks` and `POST /mcp/tools/get_aws_cost_anomalies`
return DORA metrics computed from GitHub Actions runs and merged pull requests,
open pull requests past a 36 hour review SLA, and month-to-date AWS spend per
service from Cost Explorer.

**Takes a governed rollback from the D-pad.** `POST /mcp/tools/stage_rollback`
and `POST /mcp/tools/confirm_rollback` are the only state-changing endpoints, and
both require the deployment's shared secret. See
[The rollback is the point](#the-rollback-is-the-point).

---

## What is real and what is simulated

Every telemetry response carries a provenance stamp, and the cockpit prints it on
screen next to the numbers. A viewer never has to trust the server about whether
a reading is live.

| Data | Live path | What happens without it |
|---|---|---|
| DORA metrics, pull requests | GitHub REST API via `httpx`, needs `GITHUB_TOKEN` | Serves `src/infrastructure/fixtures/github_telemetry_fixture.json`, which is a **recording of a real GitHub read** of `pallets/flask` made by `python scripts/record_github_fixture.py`, labelled `offline-fixture` |
| AWS spend | `ce:GetCostAndUsage` via `boto3`, needs AWS credentials | Serves `src/infrastructure/fixtures/aws_cost_fixture.json`, which says in its own text that it is **synthetic and was never read from an AWS account**, labelled `offline-fixture` |
| Error metric series | `cloudwatch:GetMetricStatistics` via `boto3` | Generates a deterministic local series **from the SHA-256 of the service name**, labelled `offline-fixture`, whose provenance says it was generated and never read from CloudWatch. A service name the fixture does not know is refused, not invented |
| Commits for correlation | GitHub REST API | Falls back to **real commits from the local checkout** via `git log`, labelled `local-git`, never to invented commits |

The Cost Explorer path has been executed successfully against a real AWS account
during development. The CloudWatch path has been executed and returned no
datapoints, because there is no load balancer named `checkout-api` to read. The
account's actual figures are not committed to this repository.

Those two sentences are the only claims in this README that you cannot check by
running something. They describe work done against a private AWS account outside
this repository, no artefact of which is committed here, so treat them as an
unverified maintainer statement rather than as evidence. Nothing the running
product shows depends on them: without credentials every adapter serves a fixture
and says so on screen.

Set `MERCURY_OFFLINE=1` to force every adapter into fixture mode whatever
credentials the machine has. That switch can only ever suppress a live call; it
can never make a fixture look live.

### The demo path, and what it does to the data

With no credentials at all, the war room still works end to end: the commits are
real ones read from your checkout, and the simulated metric series is anchored
relative to the newest of them so the correlation is coherent. The response says
exactly that, in the text the screen shows:

> The final reading is placed 4 minutes after the newest known commit so the
> correlation is demonstrable; the commits are real, this metric is not.

### The refusals are the first thing you can press

Three of the four answers the correlator can give are refusals, so the cockpit
offers four services on the hero, one per answer. The numbers behind each are
derived from the SHA-256 of the service name, so no two services read the same
and every machine reads the same as this one.

| Press | Verdict | What it shows |
|---|---|---|
| `checkout-api` | `ANOMALY_ATTRIBUTED` | A spike four minutes after a real commit. Names the commit, offers the rollback |
| `payments-worker` | `NO_ANOMALY` | A reading above its baseline but under the 3.0x threshold. Names nothing, offers nothing |
| `search-indexer` | `ANOMALY_WITHOUT_ATTRIBUTION` | A spike placed four hours after the newest commit, outside the 60 minute attribution window. Calls it an anomaly, then declines to blame anything |
| `quiet-service` | `INSUFFICIENT_DATA` | A name the fixture does not know. Refused outright rather than given an invented spike |

Reproduce all four from a shell against a running server:

```bash
for s in checkout-api payments-worker search-indexer quiet-service; do
  curl -s -X POST localhost:8002/mcp/tools/what_changed \
       -H 'Content-Type: application/json' -d "{\"service_name\":\"$s\"}" \
    | python -c "import json,sys; d=json.load(sys.stdin); print(d['service'], d['verdict'], d['metric'])"
done
```

The fixture used to be two module constants, so every service name returned the
same spike and neither refusal verdict was reachable from any input a reader
could supply. `tests/integration/test_mcp_endpoints.py` now drives all four
through the endpoint the cockpit calls.

Those four are a demonstration, not evidence. The evidence is below.

---

## How often it is right

The demo above cannot fail, and a demo that cannot fail says nothing about the
engine. So the correlator is scored against a labelled corpus it did not author:

```bash
python scripts/correlation_trial.py
# Scored 1160 labelled cases against IncidentCorrelator (3.0x threshold, 60 minute window), seed 20260908
```

It writes `correlation_trial_summary.json`, and a test compares the numbers below
against that file, so they cannot drift away from the run that produced them.

**Where the corpus comes from.** The deployment stream is this repository's own
`git log`, 59 real commits over 6.1 days, recorded once into
`src/infrastructure/fixtures/commit_stream_fixture.json` at commit `dc800ef` so a
published figure does not move every time somebody commits. The reading time of
every case with **no** cause is drawn over the span of that log and snapped to a
fixed 10 minute polling grid, with no reference at all to where individual commits
fall: that generator is handed two dates and never the commits.
`tests/unit/test_correlation_trial.py` regenerates those cases against a commit log
whose times have been shuffled inside the same span and asserts that not one
reading time moves. For a regression the reading necessarily follows its cause, but
the propagation delay is drawn from a range that reaches past the 60 minute window,
and how many polls late somebody looks at the screen is drawn separately. The error
values are generated here and were never read from a monitored service.

| Measure | Value | Over |
|---|---|---|
| Hit rate, fresh look | **22.0%** | 300 regressions seen on the first poll after onset |
| Hit rate, late look | **3.3%** | 300 regressions seen one to four polls later |
| Correct refusal, exogenous spikes | **62.0%** | 300 anomalies no commit caused |
| False attribution, exogenous spikes | **13.3%** | the same 300 |
| Stayed quiet on a healthy series | 99.5% | 200 ordinary series |
| Refused for want of data | 100% | 60 telemetry gaps |
| Naming precision | 27.9% | the 272 times it named a commit |

Those are the numbers. They are bad, and each one is bad for a reason that is
worth more than the number:

**The late look is the real defect.** `MetricSeries.baseline_mean` drops only the
newest point, so a spike that has been running for three polls is most of its own
baseline and the factor collapses. A tenfold regression looked at three polls late
reads as `NO_ANOMALY`: 254 of those 300 cases were missed outright.
`tests/unit/test_correlation_trial.py::test_a_spike_running_for_three_polls_is_inside_its_own_baseline`
pins that behaviour with a hand-built series, so it cannot change silently. Nobody
designed it, the corpus found it, and fixing it needs a baseline drawn from a
window before the onset rather than from the same six points, which is a change to
the detector rather than a change to the wording.

**The wrong names split two ways, and only one of them is the rule's fault.** Of
the 156 attributions that named an innocent commit, **47** had the real cause
outside the 60 minute window, where no rule with that window could have named it.
The other **109** had the cause inside the window and picked a different change
from the same window. Not one of the 156 had the cause inside the window with only
one candidate in it: when this rule had the culprit among its candidates and still
got it wrong, there was always more than one candidate. This repository commits in
bursts: the median gap between commits in the recorded stream is 20.58 minutes, 42
of its 58 gaps are under an hour, and a 60 minute window ending on a commit holds
2.78 commits on average and 9 at the worst. That is why the answer now carries
`attribution.commits_in_window` and says on screen that the name is one of several.
It does not silently pick differently, because nothing in a metric series says
which of two changes in the same window did it. The disclosure fires on 130 of the
156, and on 35 of the 76 correct namings as well, which is what it costs.

The corpus treats every commit in the log as an independently deployable change.
Real deployments often ship a burst of commits as one release, which would collapse
several of those candidate sets into a single change and raise the hit rate. This
is the pessimistic reading of the same log, and it is the one published.

**The false-attribution rate is half a number without the commit density.** An
anomaly with no cause is attributed exactly when some commit happens to fall in the
60 minutes before the reading, so the rate is a joint property of the window and of
the stream. `--commit-stride` thins the recorded log and the report sweeps it:

| Commits in the stream | Commits per hour | False attribution rate |
|---|---|---|
| 59 (every commit) | 0.405 | 8.0% |
| 30 (every 2nd) | 0.206 | 5.8% |
| 15 (every 4th) | 0.103 | 3.2% |
| 8 (every 8th) | 0.055 | 1.4% |

Read that as: on a service that deploys as often as this repository commits, one
anomaly in twelve that no deployment caused will still get a deployment blamed for
it.

**What this trial is not.** Not a field trial, and not a claim about production.
No real error metric appears in it, the noise model and the severity spread are
assumptions written by the authors rather than observations, and the commits are
development commits from this repository rather than deployments of a monitored
service. `--noise-sigma` and `--seed` are there so a reader can see how much of any
figure is those assumptions.

---

## Architecture

```mermaid
graph TD
    Remote["On-call engineer with a Fire TV remote"] -->|D-pad| APK["Leanback APK (app/)"]
    APK -->|WebView + JavascriptInterface| Cockpit["Cockpit page (docs/index.html)"]
    Keyboard["Desktop keyboard"] -->|arrow keys| Cockpit
    Cockpit -->|"fetch()"| Server["FastAPI tool server (src/interfaces)"]

    subgraph "Application layer"
        Server --> Diagnose["DiagnoseIncidentUseCase"]
        Server --> Dora["CalculateDORAUseCase"]
        Server --> Cost["DetectCostAnomaliesUseCase"]
        Server --> Rollback["GovernedRollbackUseCase"]
    end

    subgraph "Adapters, each with a labelled fallback"
        Diagnose --> CW["CloudWatchMetricAdapter"]
        Diagnose --> Git["GitHub API, then local git log"]
        Dora --> GH["GitHubTelemetryAdapter"]
        Cost --> CE["AWSCostAdapter"]
    end
```

The layering is hexagonal. `src/domain` holds pure models and imports no SDK,
which gate A5 checks by reading the imports. `src/application` holds use cases
that depend on protocols. `src/infrastructure` holds the adapters that talk to
GitHub, Cost Explorer, CloudWatch and git. `src/interfaces` holds the HTTP server
and the cockpit assets.

---

## The rollback is the point

A rollback is the one irreversible thing Mercury can do from a sofa, so it is
guarded by four independent conditions. Each has a test that proves it refuses.

```mermaid
sequenceDiagram
    autonumber
    participant TV as Fire TV cockpit
    participant API as Mercury server
    participant Dom as Governance domain

    TV->>API: POST /stage_rollback + Bearer secret
    API->>Dom: hash the payload, mint HMAC token bound to it
    Dom-->>TV: governance_token, valid once, for this content only

    TV->>API: POST /confirm_rollback + Bearer secret + token
    API->>Dom: verify signature, bound action, bound content, lease, nonce
    alt every condition holds
        Dom-->>TV: EXECUTED, and the response says no pipeline was contacted
    else any condition fails
        Dom-->>TV: 401 / 403 / 409 / 410 with a named denial reason
    end
```

1. **Authorization.** Both endpoints require `Authorization: Bearer <MERCURY_ROLLBACK_SECRET>`,
   compared in constant time. Without it the request is refused with 401.
2. **Content binding.** Staging mints an HMAC over the action id and a
   length-prefixed SHA-256 hash of the rollback payload. Edit the target commit
   after staging and the token stops applying, with reason `TOKEN_CONTENT_MISMATCH`.
3. **Single use.** Each token carries a nonce consumed on the first successful
   confirm. A replay is refused with `TOKEN_ALREADY_USED`.
4. **Lease.** A staged action expires after `lease_sec` seconds, default 300, and
   then confirms with `LEASE_EXPIRED`.

A refused confirmation moves the action to `REJECTED`, so it cannot be confirmed
afterwards even with the correct token. That is fail-closed on purpose: a
tampering attempt burns the action it was aimed at, and the operator stages
again. `python scripts/security_audit.py` runs 28 checks over this path against
the real HTTP surface and exits non-zero if any of them stops holding.

### What happens after governance passes

The default is unchanged and stays the default: `RecordOnlyDispatcher` writes the
decision locally, and its own response says so verbatim, *"No deployment pipeline
was contacted."* `GET /health` reports `"rollback_dispatch": "record-only"` when
that is what a confirmed rollback would reach.

One real dispatcher now exists behind that default.
`src/infrastructure/github_actions_dispatcher.py` asks a GitHub Actions workflow
to run through `POST /repos/{owner}/{repo}/actions/workflows/{file}/dispatches`,
carrying the action id, the target service, the target commit, the reason and the
payload hash as workflow inputs. It is selected only by
`MERCURY_ROLLBACK_DISPATCH=github_actions`, and being selected is not being armed:
without `MERCURY_ROLLBACK_DISPATCH_ARMED=1`, a token and a repository, it builds
the request, prints it with the token redacted, and opens no socket. A dispatch
that is attempted and does not return HTTP 204 raises, the API answers 502, and
the spent governance nonce means the action cannot be confirmed again.

**It has never been fired.** No request has ever been sent to github.com from this
repository: that needs a token with `actions:write` on a repository that has such
a workflow, and neither exists here. What is proved is the shape. The 15 tests in
`tests/unit/test_rollback_dispatcher.py` drive it through `httpx.MockTransport`
and assert the exact method, URL, headers and body it would send, that an unarmed
or half-configured dispatcher leaves the transport untouched, and that a refusal
raises rather than reporting success. Firing it for real is an owner action.

---

## Quickstart

Time to first result on a machine with Python 3.11 and no credentials, measured
rather than guessed: `python -m pytest tests/ -q` takes 24.8 to 25.7 seconds over
three wall-clock runs, and starting the server and getting an answer on screen is
immediate after that. It grew from 11 to 18 seconds when the correlation trial and
the legibility measurement joined the suite, which is what those two cost. The variable is `pip install`, which depends on your
network. A clean-environment install measured here ran past ten minutes, so it
dominates everything else in this section.

### 1. Install

```bash
git clone https://github.com/upgradedev/mercury_amazon.git
cd mercury_amazon
pip install -e ".[dev]"
```

### 2. Run the tests

```bash
python -m pytest tests/ -q
# 345 passed
```

### 3. Start the server

```bash
export MERCURY_ROLLBACK_SECRET="pick-any-string-for-a-local-demo"
export MERCURY_OFFLINE=1          # optional: never make an outbound call
python -m src.interfaces.mcp_server
```

On PowerShell, which is where this repository is developed:

```powershell
$env:MERCURY_ROLLBACK_SECRET = "pick-any-string-for-a-local-demo"
$env:MERCURY_OFFLINE = "1"        # optional: never make an outbound call
python -m src.interfaces.mcp_server
```

Leaving `MERCURY_ROLLBACK_SECRET` unset is allowed for a local run: the server
generates an ephemeral one and prints it to its log for you to paste into the
cockpit. It changes on every restart.

### 4. Open the cockpit and use it

Open `http://127.0.0.1:8002/`. Press **Check connection** to send a real
`GET /health` and watch the state pill change from *API not checked*. Then
**Ask what changed**, paste the governance secret, **Stage governed rollback**,
and **Confirm rollback**. Confirm a second time to watch it refuse.

Arrow keys move focus to the nearest control in that direction, which is the same
code path the Fire TV remote drives.

### 5. Build the Fire TV APK

```bash
./gradlew :app:assembleDebug     # needs JDK 17 and the Android SDK
adb connect <FIRE_TV_IP>:5555
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

Full device, emulator and troubleshooting instructions are in
[`docs/FIRE_TV_BUILD.md`](docs/FIRE_TV_BUILD.md).

---

## Fire TV

The app in `app/` is a Leanback Android application. `AndroidManifest.xml`
declares `android.software.leanback` as required, `android.hardware.touchscreen`
as not required, and a `LEANBACK_LAUNCHER` activity, which is what makes it a Fire
TV app rather than a phone app.

`MainActivity` hosts the cockpit in a WebView with JavaScript enabled, exposes a
small `MercuryHost` JavaScript interface, and forwards D-pad key codes into the
page. Back is resolved by asking the page first, then WebView history, then
closing the activity, so the viewer is never trapped and the war room is never
closed by accident. `CockpitUrlResolver` accepts only absolute `http` and `https`
URLs, so a hostile `COCKPIT_URL` intent extra cannot redirect the WebView.

A Fire TV stick on a home network usually reaches the cockpit over plain `http`
from a laptop, so a debug build has to permit cleartext and a release build must
not. `app/src/main/AndroidManifest.xml`, which is the only manifest a release
build merges, declares `android:usesCleartextTraffic="false"`. The permission
lives in `app/src/debug/AndroidManifest.xml` with `tools:replace`, so the merger
applies it to debug variants alone. Three tests in
`tests/unit/test_firetv_app_structure.py` assert that split, including one that
fails if any manifest outside the debug source set permits cleartext. They assert
the manifests the merger is given, not its output: no merged manifest has been
produced here, for the same reason no APK has.

### Ten-foot legibility, measured

```bash
pip install -e ".[ux]" && playwright install chromium
python scripts/measure_legibility.py
# Measured 220 visible text readings across 4 views at 1920x1080 (root font 24px)
#   smallest rendered text anywhere: 24px (floor 24px)
#   readings under the floor: 0 of 220
#   smallest operational text (reasons, provenance, pills): 25.9px over 29 readings
```

That script starts the server, opens the page in Chromium at 1920x1080, drives it
until all three evidence panels have loaded content, and reports the rendered
`font-size` of every element painting text of its own. Three numbers matter and a
test holds this README to all three: the smallest size anywhere, the count under
the floor, and the smallest **operational** reading, which is the text an operator
acts on rather than the labels around it. The total number of readings is not
pinned: it moves with whatever the page rendered on the day, which includes a
commit message read from `git log`. Reproduce a failing measurement by raising the
floor: `python scripts/measure_legibility.py --floor 26` exits 1.

Two defects have been fixed here, and the second was invisible while only the
first was measured.

**The floor.** Before commit `da99c6a` this reported 173 of 226 readings under
24px, with the smallest at 17.3px: the page set a 24px root at the television
breakpoint and then wrote every label, badge and provenance stamp in fractions of
that root, so the headline read across a room at 55.7px while the state pill under
it rendered at 17.3px, the provenance note at 18.7px and the rollback sentence at
19.7px. Those four figures describe the build before that commit and nothing
since; the run above is the current one.

**The reading order.** Clearing the floor put the sentence that says what the
D-pad is about to do at exactly the same size as the decorative wordmark caption,
because a floor says nothing about which text matters. The reason strings, the two
provenance chips and the connection pill now sit a tier above the body copy at
25.9px and 27.6px, and the measurement reports that tier separately so it cannot
quietly sink back to the floor.

**The setup form is off the first screen.** The API URL and the governance secret
were two text inputs in the top bar, which is a form standing between a viewer and
the incident and the worst thing in this product to operate with a D-pad. They are
now behind a `Setup` toggle, hidden on load, and the D-pad ring skips hidden
controls so the remote cannot land in them. The API defaults to the origin the page
was served from, and pressing **Stage governed rollback** with no secret opens the
setup row by itself and says why. The first screen is the incident.

The floor is a CSS pixel floor at a 1920x1080 CSS viewport. A Fire TV device that
reports a smaller CSS viewport at the same physical resolution is not covered by
this measurement, and nothing here has been measured on Fire TV hardware.

**What has been run, and what has not.** Be clear about this, because it is the
weakest part of the submission.

**No APK exists.** [`.github/workflows/android.yml`](.github/workflows/android.yml)
is written and committed to assemble one on a runner with the Android SDK, run the
Kotlin unit tests, and upload the APK as an artifact. It **has never executed**:
nothing has been pushed since it was added, so there are zero runs and zero
artifacts. The repository is private, so its Actions tab is not visible externally
either. It has also **not been built on the maintainer's machine** (no JDK, no
Android SDK; the verbatim failure is recorded in `docs/FIRE_TV_BUILD.md`), and it
**has never been installed on a physical Fire TV Stick or run in the Fire TV
emulator**.

What *is* verified: the manifest declarations, the Gradle wiring and the key
handling contract are checked by 28 structural tests, and the D-pad navigation
logic the APK drives is tested by executing `docs/firetv_nav.js` in Node against
a synthetic grid, 17 assertions in `tests/e2e/spatial_nav_spec.js`. The Kotlin
itself has unit tests written but never compiled or run.

---

## Measured numbers

Every number below is produced by a committed command. Run it and it prints them.

### Latency

`python scripts/benchmark_suite.py` measures each endpoint in-process through the
ASGI application and writes `benchmarks_summary.json` with the timestamp, the
iteration count and the data mode it observed.

| Endpoint | Requests | Mean | p95 | Command |
|---|---|---|---|---|
| `get_dora_velocity_report` | 60 | 3.21 ms | 5.46 ms | `python scripts/benchmark_suite.py` |
| `get_pr_bottlenecks` | 60 | 2.48 ms | 3.17 ms | `python scripts/benchmark_suite.py` |
| `get_aws_cost_anomalies` | 60 | 2.35 ms | 2.75 ms | `python scripts/benchmark_suite.py` |
| `what_changed` | 60 | 52.09 ms | 77.03 ms | `python scripts/benchmark_suite.py` |
| Governance mint and verify | 2000 | 0.0335 ms | 0.0451 ms | `python scripts/benchmark_suite.py` |

Measured on Windows, CPython 3.11.0, with `MERCURY_OFFLINE=1`. These exclude
network transit, so they are a floor for a local run rather than a field
measurement from a Fire TV on a home network. `what_changed` is the slow one
because it shells out to `git log` for the commit fallback.

**The one comparative number:** the full four-condition governance check costs 0.0335 ms mean over 2000 cycles, against a 2.35 ms mean for the cheapest endpoint round trip measured in the same run. Guarding the rollback therefore adds 1.43 percent to the request it guards. Baseline, margin and sample size all come from that one command.

### Tests and coverage

```bash
python -m pytest tests/ -q                                    # 345 passed
python -m pytest tests/ --cov=src --cov-report=term-missing   # 93% of 1218 statements
node tests/e2e/spatial_nav_spec.js                            # 17/17 assertions
python scripts/correlation_trial.py                           # 1160 labelled cases scored
python scripts/measure_legibility.py                          # needs the ux extra
python ci/readiness.py                                        # standards gate audit
```

### Data fixtures

```bash
python scripts/record_github_fixture.py pallets/flask   # re-record the GitHub fixture
python scripts/correlation_trial.py --record            # re-record the commit stream from git log
python scripts/probe_deployment.py                      # re-probe the deployment
```

`src/infrastructure/fixtures/commit_stream_fixture.json` is the output of that
second command: 59 real commits from `git log`, recorded at `dc800ef`, with the
head it was recorded at written into the file. It is a recording rather than a live
read so that the accuracy figures above stay attached to the corpus that produced
them instead of moving on every commit.

`deploy_teardown_receipt.json` is the output of that probe. It records only what
was observed, and it reports `deployed_commit_sha` as `null` because the deployed
build does not report one. Gate G2 therefore fails, correctly, and says so.

---

## Configuration

| Variable | Effect | Default |
|---|---|---|
| `MERCURY_ROLLBACK_SECRET` | Bearer secret for both rollback endpoints | An ephemeral one is generated and logged |
| `MERCURY_OFFLINE` | Force every adapter to skip its live call | off |
| `GITHUB_TOKEN` | Enables the live GitHub path | unset, fixture mode |
| `MERCURY_GITHUB_REPO` | Repository to measure | `upgradedev/mercury_amazon` |
| `MERCURY_DORA_WINDOW_DAYS` | DORA measurement window | 30 |
| `MERCURY_SIMULATE_INCIDENT` | `0` flattens every simulated service. It cannot make an unknown service known | `1`, each service takes its own shape |
| `MERCURY_BUILD_SHA` | Build SHA reported by `/health` | read from `git rev-parse HEAD` |
| `AWS_REGION` | Region for CloudWatch | `eu-west-1` |
| `MERCURY_ROLLBACK_DISPATCH` | `github_actions` selects the real dispatcher | unset, record only |
| `MERCURY_ROLLBACK_DISPATCH_ARMED` | `1` lets the dispatcher open a socket. Without it, dry run | unset, dry run |
| `MERCURY_ROLLBACK_REPO` | `owner/name` holding the rollback workflow | unset, cannot arm |
| `MERCURY_ROLLBACK_WORKFLOW` | Workflow file to dispatch | `rollback.yml` |
| `MERCURY_ROLLBACK_REF` | Git ref the workflow runs on | `main` |

### How DORA is computed

GitHub does not expose DORA, so these are proxies and they are stated rather than
implied. Deployment frequency is successful default-branch workflow runs divided
by the window in days. Lead time is the mean hours from pull request creation to
merge. Change failure rate is failed completed runs over all completed runs.
Recovery time is the mean hours from a failed run to the next successful one. A
repository with no workflow runs reports zero and says why, rather than being
given a substitute number.

---

## Known limitations

* **No rollback dispatch has ever been fired.** The default dispatcher records the
  decision locally and its response says so. A GitHub Actions dispatcher exists
  and is shape-tested against a mock transport, but no request has ever left this
  repository, and it stays disarmed unless three environment variables are set.
* **The simulated metric series is still simulated.** It is derived from the
  service name rather than from a constant, which makes the four verdicts
  reachable and reproducible, but it is generated locally and every surface that
  shows it says so.
* **No APK and no device run.** The Android CI workflow is configured but has
  never executed, so no APK has been produced. Nothing has been installed on Fire
  TV hardware or run in the emulator, and the Kotlin has never been compiled.
* **The live deployment is stale.** `https://t7h6us4q0f.execute-api.eu-west-1.amazonaws.com`
  answers 200 but runs an older build and reports no build SHA, so gate G2 fails.
  Its teardown has never been tested, so gate D2 fails too.
* **No video.** Gates E2 and E4 fail for that reason.
* **No browser-driver end-to-end test.** Gate C5 fails. The Node spatial navigation
  spec is a DOM shim, not a browser, and is not counted as one.
* **Cost Explorer lags.** It aggregates daily with up to 24 hours of reporting
  delay, so a spend spike in the last hour will not appear. Sub-hour spend alerting
  needs CloudWatch metric alarms, which Mercury does not implement.
* **Anomaly detection is a threshold, not a model.** The newest reading against the
  mean of the rest, with a fixed factor. It has no seasonality and no trend.
* **A spike that has been running for three polls hides inside its own baseline.**
  The baseline is the mean of the same six points minus the newest, so by the third
  poll after onset a tenfold regression reads as healthy. Measured: **3.3%** hit
  rate on the late-look stratum against **22.0%** on a fresh look, over 300 cases
  each. Both numbers are in [How often it is right](#how-often-it-is-right), and
  the fix is a baseline drawn from before the onset, which is not implemented.
* **Attribution names the closest change, and often that is the wrong one.** Every
  wrong name it gave against the labelled corpus was a window holding more than one
  change. The answer now says how many candidates there were, on the wire and on
  the screen, but it still names one of them rather than ranking them.
* **The delivery-channel premise is an assumption, not a finding.** That an on-call
  engineer is in a room with a television during an incident has never been tested
  with a responder. Nobody has been asked. If they are all remote, the ten-foot
  surface is the wrong surface and the engine is what survives, which is why the
  engine is what this README leads with.
* **Voice is browser speech synthesis.** The cockpit reads its summaries aloud with
  the browser's `speechSynthesis`. There is no Alexa skill and no Alexa integration
  in this repository.
* **In-memory state.** Staged rollbacks and spent nonces live in the server
  process, so a restart forgets them. A multi-instance deployment needs shared
  storage before the single-use guarantee holds across instances.

---

## Who would buy this, and why

**This section is a commercial hypothesis, not a finding.** Nothing in it has been
tested against a buyer. There is no price in it, no market size, no revenue
projection and no conversion rate, because no figure of that kind exists here that
was produced by anything, and an invented one would be worth less than the gap it
fills.

**The buyer.** An engineering organisation that carries on-call: one production
service, a paging rota, and someone whose week is worse when an incident runs long.
The signing name is whoever owns that rota, usually a head of platform or of
engineering. The user is the responder answering the page at two in the morning,
and the two are not the same person.

**What is being sold, and what is being assumed.** What is being sold is the
what-broke, what-changed, governed-rollback path over a real commit history, with
its accuracy published rather than asserted. What is being assumed is that a
television is a screen that responder is near. The first is measurable and is
measured above; the second is a guess about where this work happens, and it has
never been checked with a responder. Those two are not the same kind of claim and
this section does not treat them as one.

**The budget line.** The engineering tooling line that already carries the on-call
paging subscription and the observability subscription. Mercury is not asking for a
new line: it sits on the screen those two tools are already read on, and its claim
is about the minutes between the page and the rollback, which is what that line is
bought to shorten.

**The willingness-to-pay basis.** These organisations already pay per seat for
incident management and paging, and per host or per ingested gigabyte for metrics
and logs. The comparable line items, with list prices their vendors publish openly,
are PagerDuty and Atlassian Opsgenie or Jira Service Management for paging, and
Datadog and Grafana Cloud for observability. Those published pages are the basis a
price should be argued from, and the honest state of it is that **no figure from
them is restated here, because none has been read and recorded against a date by
anyone working on this repository.** Doing that, and writing down the date the page
was read, is the next step and is not one that can be faked from memory.

**The first ten conversations.** A target list, not a pipeline. None of these has
been contacted, and no one has agreed to anything.

1. Upgrade (`upgrade.net.gr`), the maintainer's own consultancy: its own on-call
   rota, and the only place where the access to install this already exists.
2. to 4. The three client engineering organisations Upgrade already runs production
   services for. Deliberately unnamed here, because none of them has been asked and
   naming a client as a prospect before asking is not a thing to do in public.
5. Engineering teams in Greece and Cyprus that publish a public status page. The
   status page is the checkable signal: a company that runs one has a rota.
6. The AWS Partner Network consultancies in Athens whose practice is already
   observability and cost work, approached as a channel rather than as a customer.
7. Organisations whose postmortems appear in the public `danluu/post-mortems`
   collection: a team that writes postmortems in the open already spends money on
   the tooling around them.
8. Responders met at SREcon EMEA, which is where this buyer goes on purpose.
9. Maintainers of the open-source on-call and status page tooling Mercury would sit
   beside, approached about an integration rather than a sale.
10. Amazon's Fire TV developer relations, as a distribution conversation rather
    than a revenue one.

**What would falsify it.** Two different things, and they fail differently.

If responders say the television is the wrong screen, because everyone is remote
and the room is empty, then the delivery premise is wrong and no price fixes it.
That is the first question to ask and it has not been asked. It would cost the
surface, not the product: the same page and the same HTTP surface already render
on a laptop, and the four-condition governance path does not care what screen
confirmed it.

If responders say the attribution is not worth reading, that is fatal, and the
measured hit rate in [How often it is right](#how-often-it-is-right) is the reason
to take that seriously: on the evidence there, the engine is not a product yet.
What would make it one is a baseline drawn from before the onset and a ranked
candidate set instead of a single closest name, both of which the corpus points
straight at. No commercial claim here rests on a figure that has not been
measured, and none of the figures above is a commercial figure.

---

## Contributing and licence

Contributions are welcome. See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the layout,
the test commands and what a pull request is checked against. Issue templates live
in [`.github/ISSUE_TEMPLATE`](.github/ISSUE_TEMPLATE).

Licensed under the [MIT Licence](LICENSE).
