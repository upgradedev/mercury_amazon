# Mercury: a Fire TV incident board that names a deploy only when it can

> **On Fire TV, Mercury names a deploy to the on-call engineer only when exactly one runtime change landed in the window, and otherwise says why.** The remote drives it, from asking what changed to a record-only rollback. On held-out synthetic cases it named an innocent change 29 times where blaming the latest deploy did so 482 times, and it found fewer causes than that rule.

![The Mercury incident board at 1920x1080: the top bar reads Mercury, Fire TV incident board, One deploy, or why not, and API reachable; column heads read Service, Reading, Verdict and Next; the answer row for checkout-api reads 12.9x against its baseline, with a hazard-striped OFFLINE FIXTURE stamp and a dashed STAND-IN stamp for Mercury's own commits beside the figure; the verdict Attributed names one commit, the only runtime change before the spike, at 50.0% held-out precision on a synthetic corpus assuming at most 75 minutes of lag, with its commit message quoted; the next action reads Record-only rollback to the preceding commit; below are the amber Ask what changed button, Stage rollback and Confirm, and five service rows reading Attributed, Nothing to revert, Cannot attribute, Cannot attribute and Insufficient data, above a Fire TV remote key legend](docs/assets/incident-board-1920x1080.png)

*The first screen at Fire TV resolution, from a local run with `MERCURY_OFFLINE=1`, committed on 2026-09-29. The board has changed since, and among the changes: the board's hero panel and its rows now call a named commit a **Temporal candidate**, the deployed board names a commit from an invented, labelled deploy feed, and it adds three LIVE rows under these five ([the eight rows](#how-it-works)). In the picture, the metric is an offline fixture and the stamp beside the number says so, and the named commit is one of this repository's own that changed server code, standing in for a deploy.*

**Status:** hosted runtime `a438bf1` (2026-10-23), verified by Lambda package hash/build revision and the matching public health snapshot in [Android TV run 39961752709](https://github.com/upgradedev/mercury_amazon/actions/runs/39961752709). [Fire TV 1.0.1 debug APK and checksum](https://github.com/upgradedev/mercury_amazon/releases/tag/firetv-v1.0.1) are available. The saved older video predates this release; a current public video URL and judge code access still need to be recorded.

**Try it.** Open the [live board](https://leol25sezuvokpankox5cvjopm0gtvfa.lambda-url.eu-west-1.on.aws/)
in a browser; arrow keys and Enter stand in for the remote. Press **Ask what changed**,
then **Stage rollback**, **Confirm** and **Publish handoff**: the rollback is
record-only and accepts only the labelled fixture target.
[`/health`](https://leol25sezuvokpankox5cvjopm0gtvfa.lambda-url.eu-west-1.on.aws/health)
names the build the board serves and lists the three LIVE rows under `live_sources`.
**Ask the agent**, in the agent deck below the handoff, is the one button that can call a
model: each press makes at most one call to Claude Sonnet 5 on Amazon Bedrock, capped at
40 per server process. A repeat press for the same service can return that process's
earlier answer without a new call, and the card does not mark it as a repeat. The answer
card names the engine that wrote it.

**What it does.** An error metric spikes during an incident and the room asks which
deploy did it. Mercury answers on the room's TV, and most of the time the honest answer
is that it cannot say: no change landed before the spike, or several did. It says which,
and never calls a deploy innocent. It counts as a deploy only a commit that changed a
runtime file, so a README edit is never blamed for a 5XX spike, and it names one only
when exactly one landed in the 75 minutes before the spike started. Beside the name it
prints how often that is right on a held-out split it was not tuned on: 50.0% (n=58
namings, synthetic corpus), under the corpus's assumption that a regression shows within
75 minutes. At longer delays it is lower: 41.5% at 90 minutes, 27.3% at 180
([table](docs/EVIDENCE.md#the-figure-depends-on-an-assumed-delay)). On the same held-out
cases, blaming the latest deploy named an innocent change 482 times in 582 namings,
against Mercury's 29 in 58; that rule finds more causes, 16.7% of regressions against
Mercury's 4.8% ([comparison](docs/EVIDENCE.md#against-two-naive-rules)). A named change
can be rolled back from the remote, behind five checks and a single-use token.

**Amazon technology.** Fire TV, on two platforms. Fire OS: a Leanback Android app
in `app/` hosts the board in a WebView and forwards the remote's D-pad keys to it.
Vega OS: the React Native for Vega app in `vega/` hosts the same board, with native
launch/offline screens and BACK handling; its CI build is not a verified Mac runtime
([Vega OS](#vega-os)). AWS: the server runs on Lambda
behind a function URL, keeps handoffs and spent tokens in DynamoDB, reads
CloudWatch error metrics and Cost Explorer spend when it has credentials, serves
`MCP 2025-11-25` Streamable HTTP on `POST /mcp`, and drafts an advisory brief on
`POST /mcp/tools/agent_incident_brief`. The board's agent deck calls it only when you
press **Ask the agent**; nothing runs on load or when you pick a row. The brief is
written deterministically from Mercury's own correlation unless Claude Sonnet 5
(`anthropic.claude-sonnet-5`) on Amazon Bedrock actually answers. That needs the server
flag `MERCURY_AGENT_MODEL=on` (off by default, and capped at `MERCURY_AGENT_MODEL_MAX_CALLS`
calls per process, default 100), the `anthropic` SDK (a declared dependency), AWS
credentials and Bedrock permission on the caller's role. The answer card names the engine
that wrote it, and which fields a model wrote, beside the
OFFLINE FIXTURE and record-only stamps. The deployed function sets the flag, capped at 40
calls; one owner-approved press on the earlier `e6aae2c` build came back HTTP 200 in
15.37 s with all four fields written by Claude Sonnet 5, one press and not a rate
([details](docs/EVIDENCE.md#the-agent-brief-on-the-deployed-build)). The brief's Bedrock adapter does not read
`MERCURY_OFFLINE`; the test suite keeps it off Bedrock with its own pytest guard.

| Link | What you get today |
|---|---|
| [Live board](https://leol25sezuvokpankox5cvjopm0gtvfa.lambda-url.eu-west-1.on.aws/) | Eight rows; [health](https://leol25sezuvokpankox5cvjopm0gtvfa.lambda-url.eu-west-1.on.aws/health) reports the deployed build |
| [Fire TV 1.0.1 debug APK](https://github.com/upgradedev/mercury_amazon/releases/tag/firetv-v1.0.1) | The exact emulator-tested APK and SHA256SUMS; repository access required while private |
| [Run it locally](#run-it-locally) | The five fixture rows, with no credentials |
| [Evidence](docs/EVIDENCE.md) | The measurements with the commands that produced them, and the audit history |
| [What is real and what is not](#what-is-real-and-what-is-not) | What is measured, what is simulated, and what is still missing |
| [Friction log](docs/FRICTION_LOG.md) | Nine problems we hit building for Fire TV and AWS, each with the task, steps, expected and actual result, severity, workaround and suggestion |

[![CI](https://github.com/upgradedev/mercury_amazon/actions/workflows/ci.yml/badge.svg)](.github/workflows/ci.yml)
[![Tests](https://img.shields.io/badge/tests-963%20collected-brightgreen.svg)](tests/)
[![Coverage](https://img.shields.io/badge/coverage-94%25-brightgreen.svg)](.github/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

The repository is **private** today, so the CI badge does not resolve outside the
organisation. The other three badges are static values that the commands in
[Evidence](docs/EVIDENCE.md#measured-numbers) reproduce.

---

## Table of Contents

1. [How it works](#how-it-works)
2. [The rollback](#the-rollback)
3. [Run it locally](#run-it-locally)
4. [What is real and what is not](#what-is-real-and-what-is-not)
5. [Who it is for and who pays](#who-it-is-for-and-who-pays)
6. [Evidence](#evidence)

---

## How it works

```mermaid
flowchart LR
    Q["Someone asks:<br/>what broke?"]
    Q --> M["1. What broke<br/>the error rate against<br/>a baseline taken from<br/>before the spike started"]
    M --> C["2. Can any one change<br/>be blamed for it?"]
    C -.->|"reading under 3.0x its baseline<br/>(200 of 200 held-out healthy series quiet)"| S["Nothing needs reverting.<br/>The only verdict that<br/>may say so"]
    C -.->|"no runtime change landed before the onset<br/>(198 of 300 held-out exogenous spikes)"| N["Cannot attribute, and says why.<br/>Names no commit, offers no rollback,<br/>and does not call any deploy innocent"]
    C -.->|"more than one runtime change landed<br/>(242 of 600 held-out regressions)"| N
    C ==>|"exactly one runtime change landed"| R["3. Name it, and stage a<br/>governed rollback behind<br/>five conditions"]
```

`POST /mcp/tools/what_changed` reads an error metric series and a commit history. It
decides whether the metric stepped up to 3.0 times a baseline taken from before the
step, then looks at the 75 minutes before the step started, counting only commits that
changed a runtime file: the server code, the board it serves, and what builds and
deploys it (the list is in [Evidence](docs/EVIDENCE.md#the-runtime-filter-v3)). A
README or test edit deploys no code and is set aside, and the answer says how many were.
**The dotted paths are the product.** On the held-out half of a synthetic labelled
corpus the correlator sees an anomaly and names nobody 90.0% of the time, because that
window usually holds no candidate or several. A refusal says which, and never claims a deploy is innocent: an
empty window says nothing about a change outside it. When it does name a change it is
right 50.0% of the time on that held-out split (29 of 58, 95% interval 38% to 62%),
and the board prints that figure next to the name with its condition: `≤75m lag`,
because the corpus assumes no regression takes longer than the window to show.

The board calls a named change a **Temporal candidate**: the only runtime commit in the
window, not proof of cause.

The deployed board shows eight rows, each its own live response from the server. Five
are demo services, one per answer, whose readings come from the offline fixture; a local
run with only `MERCURY_OFFLINE=1` shows these five. Three more read the hackathon's own
Lambda functions from CloudWatch ([live data switches](#live-data-switches)). Mercury
has no deploy feed for those three, so it does not attempt attribution for them: a LIVE
row never names a commit and never offers a rollback.

| Service | API verdict | What the board says | Stamp on the deployed board |
|---|---|---|---|
| `checkout-api` | `ANOMALY_ATTRIBUTED` | Temporal candidate: names the one runtime commit in the window and offers a record-only rollback | FIXTURE |
| `payments-worker` | `NO_ANOMALY` | Nothing to revert: 1.6x its baseline, under the 3.0x threshold | FIXTURE |
| `search-indexer` | `ANOMALY_WITHOUT_ATTRIBUTION` | Cannot attribute: no change in the window, which is not proof of no deploy | FIXTURE |
| `release-train` | `ANOMALY_WITHOUT_ATTRIBUTION` | Cannot attribute: too many runtime changes landed to name one | FIXTURE |
| `quiet-service` | `INSUFFICIENT_DATA` | Insufficient data: a name the fixture does not know, refused rather than invented | FIXTURE |
| `mercury-wallboard-euw1-prod`, `volcan-mcp-euw1-prod`, `aletheia-provenance-euw1-prod` | Never `ANOMALY_ATTRIBUTED` | `AWS/Lambda` `Errors` over the last 24 hours, with attribution not attempted; at worst it says cannot attribute. When read on 2026-10-19 at 22:49 UTC all three were at 0x, nothing to revert ([reading](docs/EVIDENCE.md#on-the-deployed-board)) | LIVE, with the read time |

The same page runs in a laptop browser, where arrow keys drive the same focus ring as
the remote.

---

## The rollback

Mercury stages a governed rollback from the remote. The public cockpit records
that decision only; it does not dispatch a deployment.
`POST /mcp/tools/stage_rollback` mints an HMAC token bound to the exact payload, and
`POST /mcp/tools/confirm_rollback` spends it once.

```mermaid
sequenceDiagram
    autonumber
    participant TV as Fire TV board
    participant API as Mercury server
    participant Dom as Governance domain

    TV->>API: stage_rollback + Bearer secret
    API->>Dom: hash the payload, mint HMAC token bound to it
    Dom-->>TV: governance_token, valid once, for this content only
    TV->>API: confirm_rollback + Bearer secret + token
    API->>Dom: verify signature, bound action, bound content, lease, nonce, recommendation
    alt every condition holds
        Dom-->>TV: RECORDED_ONLY, and the response says no pipeline was contacted
    else any condition fails
        Dom-->>TV: 401 / 403 / 409 / 410 with a named denial reason
    end
```

The five conditions are the bearer secret, the content binding, single use, a
300 second lease, and a recommendation that is still current. Each has a test that
proves it refuses. The default dispatcher only records the decision. A GitHub Actions
dispatcher exists, stays disarmed unless three environment variables are set, and
has never been fired. On the
TV, the labelled demo path stages and confirms against the checked-in fixture target
only and contacts nothing outside the server.

---

## Run it locally

The repository is private today. The event's [FAQ](https://amazonappdev2026.devpost.com/details/faqs) sets the rule for that
case: "Add the Amazon and Devpost reviewers as collaborators before the submission
deadline". That is an owner step taken near submission; until then, `git clone`
works only for collaborators. The MIT [LICENSE](LICENSE) file stays in the repository
either way. If you hold the source, start at `pip install`. The install depends on your
network; one clean install here ran past ten minutes. No credentials and no AWS account
are needed.

### 1. Install

```bash
git clone https://github.com/upgradedev/mercury_amazon.git   # needs collaborator access while private
cd mercury_amazon
pip install -e ".[dev]"
```

### 2. Run the tests (optional)

```bash
python -m pytest tests/ -q
# 963 collected; browser checks skip unless the optional browser is installed
```

The full remote CI run passed all 963 tests. To include the browser measurements locally,
install the optional browser dependencies first (Linux may also need Playwright's
system dependencies):

```bash
pip install -e ".[ux]"
python -m playwright install chromium
```

The suite's runtime moves with machine load; every measured run is in
[Evidence](docs/EVIDENCE.md#suite-runtime).

### 3. Start the server

```bash
export MERCURY_OFFLINE=1          # fixture data adapters
export MERCURY_AGENT_MODEL=off    # keep the optional model path off
python -m src.interfaces.mcp_server
```

On PowerShell use `$env:MERCURY_OFFLINE = "1"` and
`$env:MERCURY_AGENT_MODEL = "off"`. Without `MERCURY_ROLLBACK_SECRET`
the server generates an ephemeral secret for authenticated operator calls and prints
it to its log; the record-only TV demo needs none.

### 4. Open the board

Open `http://127.0.0.1:8002/`. The board asks on load. Press **Ask what changed**,
then **Stage rollback**, **Confirm** and **Publish handoff**. In record-only mode
these accept only the labelled fixture target and contact no deployment system, and
a spent confirmation token cannot be replayed.

### 5. Put it on a Fire TV

**Fire OS / Android TV emulator (verified path).** Download
[mercury-firetv-1.0.1-debug.apk](https://github.com/upgradedev/mercury_amazon/releases/download/firetv-v1.0.1/mercury-firetv-1.0.1-debug.apk)
and [SHA256SUMS.txt](https://github.com/upgradedev/mercury_amazon/releases/download/firetv-v1.0.1/SHA256SUMS.txt)
from the [1.0.1 prerelease](https://github.com/upgradedev/mercury_amazon/releases/tag/firetv-v1.0.1).
This debug sideload build is version 1.0.1 / versionCode 2, 9,266,535 bytes, SHA256
`6d7d097ea9c48d9e3e5f15b8c5d8ab69eee5e6805afacadd3f6c3f47ab9c30b7`.
It is the exact APK installed and driven by
[run 39961752709](https://github.com/upgradedev/mercury_amazon/actions/runs/39961752709)
against hosted `a438bf1`. The release is in this private repository; judges need access.
Check the checksum before installing:

```bash
sha256sum -c SHA256SUMS.txt
adb install -r mercury-firetv-1.0.1-debug.apk
```

On PowerShell, `Get-FileHash .\mercury-firetv-1.0.1-debug.apk -Algorithm SHA256`
prints the digest to compare with the checksum file. The app loads the live board and
needs a network connection. It is not an Amazon Appstore listing.
To build it yourself instead:

```bash
./gradlew :app:assembleDebug     # needs JDK 17 and the Android SDK
adb install -r app/build/outputs/apk/debug/app-debug.apk   # into a running Android TV emulator
# optional, a physical Fire TV instead: adb connect <FIRE_TV_IP>:5555 first
```

[`docs/FIRE_TV_BUILD.md`](docs/FIRE_TV_BUILD.md) covers the build, launch and D-pad
journey. The current proof is the normal online Android TV emulator journey. Native
offline Retry has lifecycle JVM/wiring tests; it has not been exercised with a
physical remote or an assistive-user session. The event's
[official FAQ](https://amazonappdev2026.devpost.com/details/faqs) accepts an Android TV
Emulator; physical Fire TV and a Vega/Mac session are not submission prerequisites.

**Vega OS (optional, build evidence only).** CI
[run 38241968838](https://github.com/upgradedev/mercury_amazon/actions/runs/38241968838)
built armv7, x86_64 and aarch64 packages at `b88c4af`; the `vega/` sources have not
changed since. Its aarch64 `mercurycockpit_aarch64.vpkg` has SHA256
`01b5b93d6106cd00eb33fa07e249cc726b806a3af4c123734f5f58637543b25a`.
That Actions artifact expires on 2026-11-11 and is not delivered as a durable Release
asset. No successful Apple Silicon Mac/Vega Virtual Device session is recorded.
With the Vega SDK and a compatible Virtual Device, the manifest names these commands:

```bash
vega device install-app --packagePath mercurycockpit_aarch64.vpkg
vega device launch-app --appName com.upgradedev.mercury.main
```

These commands are setup instructions, not a claim that they were run on a Mac.
Build with `npm ci && npm run build:release` in `vega/` on Linux or macOS with the
Vega SDK. The Ubuntu Virtual Device rejected this WebView app; see [Vega OS](#vega-os).

---

## What is real and what is not

**Real:** the correlation engine, scored on 1160 labelled cases per side of a train and
held-out split, all synthetic; commits read from real git history, with their file lists,
wherever there is a checkout (the public board has none and shows an invented deploy feed);
the governed rollback and its refusals, each tested; the Leanback app source; an Android
TV runtime receipt from [run 39961752709](https://github.com/upgradedev/mercury_amazon/actions/runs/39961752709),
which installed the exact version 1.0.1 APK and drove the record-only path by D-pad
(receipt: `android_tv_runtime_receipt.json`). The same merged build `a438bf1` was
deployed on 2026-10-23; AWS Lambda Active/Successful, build revision and exact-package
hash were verified. The workflow's public health snapshot names that build.
`MERCURY_OFFLINE=1`, `MERCURY_LIVE_CLOUDWATCH=1` and the existing model-on/cap40 settings
were preserved; this release made no model call. The agent deck now announces results
and errors through an initially silent status region. The Fire OS wrapper offers a
native focused Try again button after main-document HTTP/network failures; its
failure lifecycle has JVM tests. The emulator proof covers the normal online journey,
not a physical Fire TV or assistive-user test. Prior public probes of `e6aae2c` remain
historical in `deploy_teardown_receipt.json`.

**Live on the deployed board:** three rows read
from CloudWatch for the hackathon's own Lambda functions, stamped LIVE
([live data switches](#live-data-switches)). **Simulated:** every metric series of the
five demo services is an offline fixture, and a confirmed rollback is recorded, never
sent to a pipeline. **Built, not deployed:** a live GitHub DORA read. **Missing:**

- **A published video.** One take is rendered and not yet uploaded:
  `reviews/videos_20261006/mercury_amazon/output/mercury-demo.mp4` in the workspace,
  outside git, 163.09 s (ffprobe), 1920x1080. It opens on 23.32 s of Android TV
  emulator footage from CI run 37475795991: the debug APK on an AOSP emulator, API 34,
  loading the public demo (`ea2cff5`, record-only), from the board's first frame, at 1x
  with two static frames held longer. That is emulator footage, not a Fire TV device, and
  it does not show the app being opened from the launcher. A label names each source on
  every frame. The rest is a local run of commit `f7512bf` in a desktop browser at
  1920x1080, not the TV layout, every key sent through the D-pad bridge the Leanback app
  calls, with burned-in captions. It speaks the 50.0% held-out precision where the board
  prints it and the 58 namings over the evidence sentence, and after Confirm shows the
  board holding RECORDED, no pipeline contacted. The
  sync gate passed. Details in [video/README.md](video/README.md).
- **A public repository.** Private until the reviewers are added as collaborators; see
  [Run it locally](#run-it-locally).

| Part | On the board today | Live path |
|---|---|---|
| Error metric | Generated locally from the service name, stamped OFFLINE FIXTURE | CloudWatch via `boto3`. Run once against a real account, it returned no datapoints because no such load balancer exists. An empty or failed read now shows NO LIVE DATA and names nothing; it is never replaced with the generated series. With `MERCURY_LIVE_CLOUDWATCH=1` the board adds three rows for the hackathon's own production functions, read from `AWS/Lambda` (`Errors`, with `Invocations` beside it, last 24 hours) and stamped LIVE with the read time; the four simulated services stay fixtures. Set on the deployed function since 2026-10-19 |
| Commits | Real commits from this repository's `git log` with their file lists (a 20-commit window recorded at merge `a4ec9aa`, so a new commit cannot change the demo's verdicts), stamped STAND-IN because they stand in for a deploy feed; only one that changed a runtime file counts as a deploy. The public cockpit has no git checkout, so it shows an invented, display-only deploy feed (`src/infrastructure/fixtures/deploy_feed_fixture.json`), stamped OFFLINE FIXTURE; no published figure is computed from it | GitHub REST API with `GITHUB_TOKEN`, plus one files read per commit, so the runtime filter applies there too; a failed or capped read stays a candidate |
| Delivery velocity | A recording of a real GitHub read of `pallets/flask`, stamped OFFLINE FIXTURE | GitHub REST API. With `MERCURY_LIVE_GITHUB=1` and no token it reads this repository anonymously, cached for 15 minutes; while the repository is private that read gets HTTP 404 and the board keeps the fixture and says why. Not deployed yet |
| Cloud spend | A synthetic fixture that says it was never read from an AWS account | Cost Explorer. The maintainer ran it once against a private account; no artefact is committed, so treat that as unverified. There is deliberately no live switch for it: Cost Explorer reports the whole account's bill, so under `MERCURY_OFFLINE=1` it is always the fixture |
| Rollback | Recorded, never sent | A GitHub Actions dispatcher that has never been fired |
| Fire TV, Fire OS | Native app source, APK 1.0.1 release and current runtime receipt | Run 39961752709 built and installed the exact a438bf1 APK, normally launched it and drove the record-only D-pad journey; receipt `android_tv_runtime_receipt.json`. Physical Fire TV is optional |
| Fire TV, Vega OS | Source and CI-built packages from run 38241968838 | Build evidence only; the Ubuntu Virtual Device refused the WebView package. No successful Mac/Vega runtime or retail-device run is recorded |

`MERCURY_OFFLINE=1` forces every data adapter (CloudWatch, Cost Explorer, GitHub) into
fixture mode. It can suppress a live call; it cannot make a fixture look live. Two narrower
switches re-open one source each on top of it; see [live data switches](#live-data-switches). The agent
brief's Bedrock adapter is the exception: it does not read the switch. It answers
deterministically unless the server sets `MERCURY_AGENT_MODEL=on`, and whenever the SDK,
credentials or permission is missing or a call fails. Nothing on the page speaks or announces on load, the page calls no agent or
model until a viewer presses Ask the agent, and it makes no request to another origin.

### Live data switches

**The deployed board sets `MERCURY_LIVE_CLOUDWATCH=1` on top of `MERCURY_OFFLINE=1`
since 2026-10-19, and does not set `MERCURY_LIVE_GITHUB`.** The committed probe's
`/health` (`deploy_teardown_receipt.json`) lists the three CloudWatch rows under
`live_sources` and reports `github_dora_and_pr_radar` false.

| Switch | Live when set | Still a fixture |
|---|---|---|
| `MERCURY_OFFLINE=1` | Nothing | Every adapter |
| `MERCURY_LIVE_CLOUDWATCH=1` on top of `MERCURY_OFFLINE=1` | Three extra board rows for the hackathon's own production functions, `mercury-wallboard-euw1-prod`, `volcan-mcp-euw1-prod` and `aletheia-provenance-euw1-prod`: `AWS/Lambda` `Errors`, with `Invocations` in the provenance, Sum per hour over the last 24 hours, each row stamped LIVE with the read time. Only those three names are ever sent to CloudWatch; a read is reused for 60 seconds | The four simulated services and `quiet-service`, whose rows gain a FIXTURE stamp. The rollback demo is unchanged |
| `MERCURY_LIVE_GITHUB=1` | The DORA report and the pull request radar, from the GitHub REST API, anonymously when no `GITHUB_TOKEN` is set, every answer (a refusal included) reused for 15 minutes | The commit feed behind the rollback demo, which still needs a token |
| none | | Cost Explorer under `MERCURY_OFFLINE=1`. It reports the whole account's bill, so it has no live switch |

Without `MERCURY_OFFLINE`, every adapter tries its live path as before: the simulated
service names then go to CloudWatch's load balancer metrics and show NO LIVE DATA, which is
why the hybrid keeps `MERCURY_OFFLINE=1` and adds the switches on top.

A live row is never attributed to a commit and never offers a rollback: no deploy feed for
those functions is connected, and every text the row carries says so rather than describing
an empty deploy window. A row whose errors rose from a zero baseline, including a run of
errors that has lasted several hours after only zeros, is reported as cannot-attribute,
never as nothing to revert. An adapter that fails puts only the
exception class, an AWS error code or HTTP status, and a short reason into the provenance;
ARNs, account ids, access key ids and request ids are removed
(`src/infrastructure/safe_errors.py`). The deployment needs one read-only grant on the
function's role, `cloudwatch:GetMetricStatistics` on `Resource: "*"` (CloudWatch metric
reads take no resource ARN, so the fixed list of three names in
`src/infrastructure/cloudwatch_adapter.py` is the only scope). That grant is applied: the inline policy
`mercury-read-own-lambda-metrics` was attached to the function's role on 2026-10-19 at
22:21 UTC, with the owner's approval and outside Terraform. Setting `MERCURY_LIVE_CLOUDWATCH=1`
changes what the TV renders, eight rows instead of five. Historical run 39334510932
covered the `e6aae2c` page after that switch was enabled. Current run 39961752709
repeated the native D-pad journey against `a438bf1`, with public health matching that
build; its final screenshot shows rollback/handoff, not the rows. The dated hybrid
measurements remain in [Evidence](docs/EVIDENCE.md#hybrid-live-data-deployed-at-e6aae2c).

Of the data switches, the deploy sets `MERCURY_OFFLINE=1` and `MERCURY_LIVE_CLOUDWATCH=1`;
it does not set the GitHub switch. Known issue, not fixed here: with `MERCURY_LIVE_GITHUB=1`,
`/health` reports `github_live` true from the switch alone, even while every read is refused,
and `video/capture-local.py` refuses to record while it is true.

The engine's limits are measured, not hidden. Every figure comes from a synthetic
corpus the authors wrote. Settings are tuned on a train split and reported on a
held-out split (a time cut of the commit stream with fixed seeds, scored by
`python scripts/attribution_split.py`). On held-out, naming recall is 4.8%: it names the
cause of about one regression in twenty-one. The runtime filter, added on 2026-09-27 as
a constraint rather than a tuned setting, moved held-out precision from 62.5% to 50.0%,
recall from 4.2% to 4.8%, refusals from 93.1% to 90.0%, and wrong namings from 15 to
29. The corpus's labels let a README edit cause a 5XX, which the filter will not name:
14 of its 16 wrong namings on regressions are such labels
([breakdown](docs/EVIDENCE.md#the-runtime-filter-v3)). The labels were not changed and
the board prints the lower figure. Before that, widening the window from 60 to 75
minutes on train had moved held-out precision from 40.8% to 62.5%. Both splits share the
generator's 75 minute delay ceiling, which the window equals, so the held-out figure
cannot test that fit: at a 180 minute ceiling the shipped engine reads 27.3%. The 52.2%
this page printed before was in-sample. A crowded window is
refused, not ranked. The full list is in
[Known limitations](docs/EVIDENCE.md#known-limitations).

---

### Vega OS

`vega/` holds the Vega OS app: a React Native for Vega shell around the same board page
the Fire OS app loads, with its own launch and offline screens and BACK handling
(`vega/src/App.tsx`). CI
[run 38241968838](https://github.com/upgradedev/mercury_amazon/actions/runs/38241968838)
built it on 2026-10-12 at `b88c4af` with Vega SDK 0.24.12112, for armv7, x86_64 and
aarch64, with 53 of 53 Jest tests passing; `git diff b88c4af HEAD -- vega/` prints
nothing, so the `vega/` sources are unchanged since. The Vega Virtual Device in that run, on
GitHub's Ubuntu runner, refused to install the package because it has no WebView module
(`vvd_status=builds_but_vvd_blocked`); `vega/manifest.toml` notes that the Vega Virtual
Device runs WebView apps only on an Apple Silicon Mac. No successful
Mac/Vega runtime or video is recorded. The supported Android TV emulator path above
is the verified submission path. No Vega Fire TV stick has run it. To install it, see
[step 5](#5-put-it-on-a-fire-tv).

---

## Who it is for and who pays

**This is a commercial hypothesis, not a finding.** Nobody has been asked yet, and the
price below is an untested hypothesis. The user is the on-call responder; the payer is
whoever owns the on-call rota, from the tooling line that already pays for paging.

| Question | Answer |
|---|---|
| Population | A ceiling, not a count of rotas: "In 2025, more than 10 million persons were employed as ICT specialists across the European Union (EU)", per [Eurostat](https://ec.europa.eu/eurostat/statistics-explained/index.php?title=ICT_specialists_in_employment). How many of them carry a pager is not measured anywhere this repository has read. |
| Price hypothesis | Untested: $20 per responder on the rota per month. It sits just under the [PagerDuty Professional](https://www.pagerduty.com/pricing/incident-management/) list price of $21 per user per month billed yearly, and level with [Grafana Assistant](https://grafana.com/pricing/) at $20 per active AI user, a comparable tool that investigates an alert. |
| Wedge | Platform teams at EU financial entities that run their own services on a rota. Since 17 January 2025 the [Digital Operational Resilience Act](https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:32022R2554) requires processes "to ensure that root causes are identified, documented and addressed". Mercury writes no report; it answers, or refuses on the record, the first question that record has to answer. |
| Why now | The same regulation, applying since 17 January 2025, and a budget line reopening: [Atlassian](https://www.atlassian.com/software/opsgenie/migration) says "Opsgenie customers have until April 5th, 2027 to complete their move to Jira Service Management." Mercury replaces no pager, but the line it would sit on is being re-decided. |
| Riskiest assumption | That incidents are worked in a room with a shared screen. The cheapest test is one question to the four rota owners on the target list: where was your last incident worked, and was a screen on? |

Every quote, the date each page was read, the command that fetched it, the other two
risky assumptions and their tests, and the first ten conversations are in
[Who would buy this, and why](docs/EVIDENCE.md#who-would-buy-this-and-why).

---

## Evidence

[`docs/EVIDENCE.md`](docs/EVIDENCE.md) holds every measurement with its command:

- `python scripts/attribution_split.py` scores the engine on a train and a held-out
  split, 1160 synthetic labelled cases each, and writes the figure the board prints;
  `python scripts/tune_attribution.py` is the train-only sweep the window was chosen from.
- `python scripts/naive_attribution_baselines.py` scores blame-the-latest-deploy and
  blame-every-deploy-in-the-window on the same held-out cases: 29 wrong namings for the
  engine against 482 and 1294, and lower recall, 4.8% against 16.7% and 56.8%.
- `python scripts/correlation_trial.py` scores the whole-stream corpus and prints the
  ablation, the threshold sweep and the density sweep.
- `python scripts/benchmark_suite.py` times every endpoint and the governance token.
- `python scripts/measure_legibility.py` measures every text size on the TV screen
  (smallest 24px).
- `python scripts/security_audit.py` runs the rollback refusal checks over HTTP.
- `python ci/readiness.py` runs the standards gates. Gates I1 to I4 read
  [`docs/PERSONA_REVIEW.md`](docs/PERSONA_REVIEW.md), so the result is reproducible
  in a clone; it is an internal readiness audit, not an organizer judging score.

## Contributing and licence

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the layout, the test commands and what a
pull request is checked against. Licensed under the [MIT Licence](LICENSE).
