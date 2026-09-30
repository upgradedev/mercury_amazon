# Mercury: a Fire TV incident board that names a deploy only when it can

> **Mercury tells an on-call engineer when it cannot blame a deployment, and names one only when exactly one runtime change landed in the window.** It reads a real commit history against an error metric, publishes how often each answer is right, and renders on a Fire TV as one of its screens.

![The Mercury incident board at 1920x1080: the top bar reads Mercury, Fire TV incident board, One deploy, or why not, and API reachable; column heads read Service, Reading, Verdict and Next; the answer row for checkout-api reads 12.9x against its baseline, with a hazard-striped OFFLINE FIXTURE stamp and a dashed STAND-IN stamp for Mercury's own commits beside the figure; the verdict Attributed names one commit, the only runtime change before the spike, at 50.0% held-out precision on a synthetic corpus assuming at most 75 minutes of lag, with its commit message quoted; the next action reads Record-only rollback to the preceding commit; below are the amber Ask what changed button, Stage rollback and Confirm, and five service rows reading Attributed, Nothing to revert, Cannot attribute, Cannot attribute and Insufficient data, above a Fire TV remote key legend](docs/assets/incident-board-1920x1080.png)

*The first screen at Fire TV resolution, captured from a local run with `MERCURY_OFFLINE=1`. The metric is an offline fixture and the stamp beside the number says so. The named commit is one of this repository's own that changed server code, standing in for a deploy.*

**Status:** runs end to end on a laptop with offline fixtures and no credentials. A 170.61 s demo video is rendered but not uploaded. Fire TV runtime evidence landed in run 36661614006; public access is still pending ([details](#what-is-real-and-what-is-not)).

**What it does.** An error metric spikes during an incident and the room asks which
deploy did it. Mercury answers on the room's TV, and most of the time the honest answer
is that it cannot say: no change landed before the spike, or several did. It says which,
and never calls a deploy innocent. It counts as a deploy only a commit that changed a
runtime file, so a README edit is never blamed for a 5XX spike, and it names one only
when exactly one landed in the 75 minutes before the spike started. Beside the name it
prints how often that is right on a held-out split it was not tuned on: 50.0% (n=58
namings, synthetic corpus), under the corpus's assumption that a regression shows within
75 minutes. At longer delays it is lower: 41.5% at 90 minutes, 27.3% at 180
([table](docs/EVIDENCE.md#the-figure-depends-on-an-assumed-delay)). A named change can be
rolled back from the remote, behind five checks and a single-use token.

**Amazon technology.** Fire TV: a Leanback Android app in `app/` hosts the board in a
WebView and forwards the remote's D-pad keys to it. AWS: the server runs on Lambda
behind a function URL, keeps handoffs and spent tokens in DynamoDB, and reads
CloudWatch error metrics and Cost Explorer spend when it has credentials.

| Link | What you get today |
|---|---|
| [Run it locally](#run-it-locally) | The build in the picture, with no credentials |
| [Evidence](docs/EVIDENCE.md) | The measurements with the commands that produced them, and the audit history |
| [What is real and what is not](#what-is-real-and-what-is-not) | What is measured, what is simulated, and what is still missing |

[![CI](https://github.com/upgradedev/mercury_amazon/actions/workflows/ci.yml/badge.svg)](.github/workflows/ci.yml)
[![Tests](https://img.shields.io/badge/tests-665%20collected-brightgreen.svg)](tests/)
[![Coverage](https://img.shields.io/badge/coverage-92%25-brightgreen.svg)](.github/workflows/ci.yml)
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

The board shows five services, one per answer. Each row is its own live response from
the server; the readings come from the offline fixture.

| Service | Verdict | What the board says |
|---|---|---|
| `checkout-api` | `ANOMALY_ATTRIBUTED` | Names the one runtime commit in the window and offers a record-only rollback |
| `payments-worker` | `NO_ANOMALY` | 1.6x its baseline, under the 3.0x threshold: nothing to revert |
| `search-indexer` | `ANOMALY_WITHOUT_ATTRIBUTION` | Cannot attribute: no change in the window, which is not proof of no deploy |
| `release-train` | `ANOMALY_WITHOUT_ATTRIBUTION` | Cannot attribute: too many runtime changes landed to name one |
| `quiet-service` | `INSUFFICIENT_DATA` | A name the fixture does not know, refused rather than invented |

The same page runs in a laptop browser, where arrow keys drive the same focus ring as
the remote.

---

## The rollback

A rollback is the one irreversible thing Mercury can do from a sofa.
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
# 665 passed
```

The suite's runtime moves with machine load; every measured run is in
[Evidence](docs/EVIDENCE.md#suite-runtime).

### 3. Start the server

```bash
export MERCURY_OFFLINE=1          # never make an outbound call
python -m src.interfaces.mcp_server
```

On PowerShell use `$env:MERCURY_OFFLINE = "1"`. Without `MERCURY_ROLLBACK_SECRET`
the server generates an ephemeral secret for authenticated operator calls and prints
it to its log; the record-only TV demo needs none.

### 4. Open the board

Open `http://127.0.0.1:8002/`. The board asks on load. Press **Ask what changed**,
then **Stage rollback**, **Confirm** and **Publish handoff**. In record-only mode
these accept only the labelled fixture target and contact no deployment system, and
a spent confirmation token cannot be replayed.

### 5. Build the Fire TV APK

```bash
./gradlew :app:assembleDebug     # needs JDK 17 and the Android SDK
adb install -r app/build/outputs/apk/debug/app-debug.apk   # into a running Android TV emulator
# optional, a physical Fire TV instead: adb connect <FIRE_TV_IP>:5555 first
```

[`docs/FIRE_TV_BUILD.md`](docs/FIRE_TV_BUILD.md) covers the build and the Android TV
Emulator workflow. The target proof is an Android TV emulator run, not a physical Fire
TV. The event's [official FAQ](https://amazonappdev2026.devpost.com/details/faqs) says for Fire TV that "a physical device isn't
required at any stage of submission or judging".

---

## What is real and what is not

**Real:** the correlation engine, scored on 1160 labelled cases per side of a train and
held-out split, all synthetic; commits read from real git history, with their file lists;
the governed rollback and its refusals, each tested; the Leanback app source; an Android
TV runtime receipt from [run 36661614006](https://github.com/upgradedev/mercury_amazon/actions/runs/36661614006),
which installed the exact APK on an emulator and drove the record-only path by D-pad
(receipt: `android_tv_runtime_receipt.json`); and a live cockpit that serves this
branch at HEAD (env-bumped on every merge, `/health` reports the build SHA, labelled
offline-fixture mode).
**Simulated:** every metric series on the board is an offline fixture, and a confirmed
rollback is recorded, never sent to a pipeline. **Missing:**

- **A published video.** One take is rendered and not yet uploaded:
  `reviews/videos_20260928/mercury_amazon/output/mercury-demo.mp4` in the workspace,
  outside git, 170.61 s (ffprobe), 1920x1080, recorded at commit `df5db06` in desktop Chromium, every key sent
  through the D-pad bridge the Leanback app calls, with burned-in captions. It shows
  the figures this page prints, 50.0% held-out precision over 58 namings and 90.0%
  refusals, with commit `7bd8b41` named as the only runtime change (the stand-in is
  the newest lone runtime commit, so a later build names a later one), and after Confirm the
  board holding RECORDED, no pipeline contacted. No device or emulator appears in it,
  and it says so. Two presses differ from this build. In the take, Down from an open
  panel walks out to Connection > Check, where this build keeps the remote in the
  panel until Back; and Center on Publish handoff moves the cursor on to Refresh with
  the handoff's answer below the fold, where this build stays on Publish and brings
  the answer up. Details in [video/README.md](video/README.md).
- **A public repository.** Private until the reviewers are added as collaborators; see
  [Run it locally](#run-it-locally).

| Part | On the board today | Live path |
|---|---|---|
| Error metric | Generated locally from the service name, stamped OFFLINE FIXTURE | CloudWatch via `boto3`. Run once against a real account, it returned no datapoints because no such load balancer exists |
| Commits | Real commits from this repository's `git log` with their file lists, stamped STAND-IN because they stand in for a deploy feed; only one that changed a runtime file counts as a deploy | GitHub REST API with `GITHUB_TOKEN`, plus one files read per commit, so the runtime filter applies there too; a failed or capped read stays a candidate |
| Delivery velocity | A recording of a real GitHub read of `pallets/flask`, stamped OFFLINE FIXTURE | GitHub REST API |
| Cloud spend | A synthetic fixture that says it was never read from an AWS account | Cost Explorer. The maintainer ran it once against a private account; no artefact is committed, so treat that as unverified |
| Rollback | Recorded, never sent | A GitHub Actions dispatcher that has never been fired |
| Fire TV | App source, a CI build workflow and a runtime receipt | Run 36661614006 installed the exact APK on an Android TV emulator and drove the D-pad journey; receipt `android_tv_runtime_receipt.json`. The 2026-09-27 attempt stopped before install. The event FAQ does not require a physical Fire TV |

`MERCURY_OFFLINE=1` forces every adapter into fixture mode. It can suppress a live
call; it cannot make a fixture look live. Nothing on the page speaks or announces on
load, and the page makes no request to another origin.

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
- `python scripts/correlation_trial.py` scores the whole-stream corpus and prints the
  ablation, the threshold sweep and the density sweep.
- `python scripts/benchmark_suite.py` times every endpoint and the governance token.
- `python scripts/measure_legibility.py` measures every text size on the TV screen
  (smallest 24px).
- `python scripts/security_audit.py` runs the rollback refusal checks over HTTP.
- `python ci/readiness.py` runs the standards gates. The persona review those gates
  read is [`docs/PERSONA_REVIEW.md`](docs/PERSONA_REVIEW.md), so the score is
  reproducible in a clone.

## Contributing and licence

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the layout, the test commands and what a
pull request is checked against. Licensed under the [MIT Licence](LICENSE).
