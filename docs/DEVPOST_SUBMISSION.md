# Devpost submission text: Mercury

**Track:** Fire TV
**Mini challenge:** Open Source

---

## Tagline (23 words)

Mercury tells an on-call engineer when it cannot blame a deployment, and names one
only when exactly one change landed in the window.

---

## Inspiration

An incident starts and everyone opens the same six tabs. The version control host
is in one, the metrics console is in another, the deployment pipeline is in a
third, and the one question that matters is spread across all of them: what
changed just before this broke?

Mercury answers that question from a real commit history, and then it was scored,
and the scoring changed what it claims. It turns out the answer worth having is
usually a refusal: Mercury cannot attribute this to a change, and here is why. That
refusal is never dressed up as proof that a deploy is innocent, because an empty or
crowded window says nothing of the kind, and the only verdict that says nothing
needs reverting is the one where the reading is under the 3.0x anomaly threshold. On the
held-out half of a synthetic labelled corpus, which no setting was tuned on, Mercury
sees an anomaly and names nobody 90.0% of the time, stays quiet on 200 of 200
healthy series, and refuses outright on every telemetry gap. It counts as a deploy
only a commit that changed a file the server is built from. When it does name a
change, it is right 50.0% of the time over 58 namings, and it prints that on the
screen beside the name, with the assumption it rests on: the corpus has every
regression show within 75 minutes, the same as the window. With a longer delay
ceiling the same engine reads 41.5% at 90 minutes and 27.3% at 180. Then it renders where the people are. A Fire TV in the room
is one of those places and the one this entry is built for: a screen everyone can
see, driven by a remote, with the evidence readable from a sofa. The screen is the
delivery; the engine is the thing.

---

## What it does

**Says when it cannot blame a deploy, and never says more than that.** Mercury reads
an error metric series and a commit history, decides whether the metric has stepped
up against a baseline taken from before the step, and looks for changes in the 75
minutes before that step started. It names one only when exactly one landed there. When none
landed it says so; when several landed it says how many and names none of them,
because nothing in a metric series says which of two changes did it. Both refusals
have their own tests, because a war room tool that always has an answer is worse
than one that admits when it does not, and both are more common than the answer that
names something. Each ships as `attribution.refusal_statement`, which names the
reason and says that the reason is not a finding about the deploys, and
`attribution.nothing_to_revert` is true only when the reading is inside its
baseline.

**Publishes how often each answer is right, and ships the figure with the answer.**
`python scripts/correlation_trial.py` scores the correlator against 1160 labelled
incidents built on this repository's real commit log, with the reading times of
every case that has no cause drawn without reference to where any commit falls. The
corpus is synthetic and self-authored: the commits are real, the metric values and
labels are generated. `python scripts/attribution_split.py` cuts that commit log in
time into a train side, where settings are tuned, and a held-out side, where the
published figure is measured. It reports precision, recall and the refusal rate
together, and splits the refusals by reason so a blunter instrument cannot read as
better judgement. Every `what_changed` response carries
`attribution.measured_accuracy`, the held-out figure read from that recorded summary
rather than recomputed, so the operator sees the odds at the moment they would act.

**Publishes what it used to get wrong.** The late-look hit rate was 3.3% because
the baseline contained the spike it was measuring. It was 8.3% at the settings
shipped on 2026-09-08 and 18.7% with the crowding gate off, and the detector that produced the
old number is still selectable so the before-and-after is two runs of committed
code rather than a memory of one.

**Shows velocity and spend.** DORA metrics computed from GitHub Actions runs and
merged pull requests, open pull requests past a 36 hour review SLA, and
month-to-date AWS spend per service from Cost Explorer, all on the big screen.

**Takes a governed rollback from the D-pad.** The only irreversible action is
guarded four ways: a bearer secret, an HMAC token bound to a hash of exactly what
will be rolled back, a nonce consumed on first use, and a 300 second lease. Edit
the target after staging and the token stops working. Confirm twice and the second
attempt is refused by name.

---

## How we built it

Hexagonal Python: a domain layer that imports no SDK, use cases that depend on
protocols, adapters for GitHub, Cost Explorer, CloudWatch and local git, and a
FastAPI server. A Kotlin Leanback application hosts the same cockpit page the web
serves, so the television and the browser run one implementation rather than two.

The design decision that shaped everything else was making data provenance a
first-class domain type. Every report carries where it came from, and the cockpit
prints that on screen. That is what makes a fallback safe to ship: an adapter that
cannot reach its live source returns a fixture **and** says so, visibly, in the
same place as the number.

D-pad navigation is geometric rather than a list walk. For a pressed direction it
keeps only the candidates that lie in that direction, scores them by distance
along the axis of travel plus a penalty for perpendicular drift, and takes the
minimum. The real file is executed in Node against a synthetic grid by 17
assertions, so the geometry is tested rather than asserted.

---

## Challenges

Our own benchmark caught a bug that code review had not: resolving boto3
credentials on every request added over a second to each AWS call, because on a
machine with no credentials that walk includes an instance metadata probe that
must time out. Caching the resolution took the mean from 1154 ms to under 4 ms.

Cost Explorer bills per request and refreshes daily, which makes the obvious
wallboard design, polling on refresh, both expensive and pointless. We cache
successful responses for 15 minutes and say why in the text on screen.

Reconciling a synchronous key handler with an asynchronous WebView bridge for the
Back button took more thought than the rest of the Android code combined. Get it
wrong in one direction and the viewer is trapped; get it wrong in the other and
the war room closes mid-incident.

---

## Accomplishments we are proud of

**We scored the engine instead of demonstrating it, and then we believed the
score.** The cockpit's demo places a simulated spike minutes after a real commit,
which is a demonstration that cannot fail and therefore proves nothing. So the
correlator is also run against a labelled corpus whose reading times were drawn
without looking at the commit log. That corpus found a defect nobody had noticed:
a spike running for three polls was inside its own baseline and read as healthy,
which is why the late-look hit rate was 3.3%. It also found that when the
correlator had the culprit among its candidates and still named the wrong one,
there was always more than one candidate in the window.

Both are fixed. The baseline now stops at the onset, the attribution window ends
when the spike started rather than when somebody looked, and the correlator refuses
to name anything when more than one change landed in the window. The late look went
from 3.3% to 8.3%, naming precision from 27.9% to 52.2%, and naming recall from
20.3% to 9.8%, because refusing more means naming less. That trade is published in
full, with the sweep it was chosen from.

Then we noticed the 52.2% was measured on the corpus the gate was chosen on. We split
the commit log in time into train and held-out sides. On held-out the same engine
read 40.8% over 71 namings. A 75 minute window, chosen on train by a rule stated in
the script that made the choice, reads 62.5% over 40 namings on held-out, and it cost something:
recall 4.8% to 4.2%, refusals 87.8% to 93.1%, and false attribution on spikes no
commit caused from 9 to 14 of 300. Both engines, both sides and the sweep are
published. An audit then pointed out that 75 minutes is also the ceiling of the delay
our generator draws, on both sides of the split, so holding data out could not test
that fit. We now publish held-out precision at other ceilings beside the headline: the
new engine beats the old at every ceiling, but its level falls from 62.5% to 25.0% if
regressions can take three hours to show.

Then a reviewer saw the board blame a commit that only edited the README for a 5XX
spike. A change that touches no runtime file deploys no code, so the engine now counts
only commits that changed a file the server is built from. Our generator's labels
disagree (they let any commit cause a regression), so on held-out the figure fell from
62.5% over 40 namings to 50.0% over 58; 14 of the 16 wrong namings on regressions are
cases labelled as caused by a commit that touched no runtime file. We ship the filter
and print the lower number.

**We changed the headline to match the numbers.** The old one said Mercury tells you
which change broke production. Its own harness said that is right about half the
times it fires, so the headline is now the refusal, which is what the numbers
support and what an on-call engineer can actually act on.

**The refusals work and are tested.** Confirm a rollback and the cockpit's Confirm
control goes dark, saying the token is spent; send the same confirm again from a
shell and the server answers `409 NOT_PENDING`. Let the lease run out and it comes back
`410 LEASE_EXPIRED`. Edit the target after staging and the token stops applying.
Each denial is named on the screen rather than swallowed, and each has a test.

**The page cannot show a number it did not fetch.** Every figure in the cockpit is
written from a response body through `textContent`, with the latency measured in
the page by `performance.now()`. A test fails if a hardcoded metric, a random
pairing code or an `innerHTML` assignment returns to the file.

**Live and recorded data sit side by side, both labelled.** On a machine with AWS
credentials the spend panel shows a `LIVE` badge reading `aws-cost-explorer` while
the velocity panel next to it shows `OFFLINE FIXTURE` and states that `GITHUB_TOKEN`
is not set. The screen never asks to be trusted about which is which.

**The D-pad geometry is real.** Focus moves to the nearest control in the pressed
direction, skips disabled controls instead of landing on them, and holds at an
edge rather than wrapping. The same file drives both arrow keys and the Leanback
bridge, so there is one navigation implementation rather than two.

---

## What is live and what is simulated

Stated plainly, because the cockpit shows it anyway.

| Part | Status |
|---|---|
| Correlation, DORA, cost and governance endpoints | **Live.** Real HTTP, called by the page on load and on every press |
| Commits used for attribution | **Live.** Read from the local checkout with `git log` when no GitHub token is set |
| AWS spend | **Live** when credentials exist, and the badge says `aws-cost-explorer`. Otherwise a synthetic fixture that says so |
| GitHub velocity and pull requests | **Recorded.** A real read of `pallets/flask` replayed from a committed fixture, labelled `offline-fixture` |
| Error metric series | **Simulated.** Generated locally, labelled `offline-fixture`, and the response text says the commits are real but the metric is not |
| The rollback itself | **Simulated dispatch.** Governance is real and enforced; no deployment pipeline is contacted, and the success response says that verbatim |
| Attribution accuracy | **Measured on a synthetic, self-authored corpus.** Held-out split scored by `python scripts/attribution_split.py`: naming precision 50.0% over 58 namings (95% interval 37.5% to 62.5%) under the corpus's assumption that a regression shows within 75 minutes (41.5% at 90, 27.3% at 180), recall 4.8% over 600 regressions, refusal on 90.0% of detected anomalies, with only commits that changed a runtime file counted as deploys, shipped in every answer as `attribution.measured_accuracy`. The in-sample 52.2% it replaced is kept as history |
| Fire TV target | **Candidate runtime pending.** The new workflow builds the intended endpoint, installs the exact APK in Android TV Emulator, normally launches it with no URL override and drives attribution, record-only confirmation and handoff by D-pad. That emulator run is the target proof. The [official FAQ](https://amazonappdev2026.devpost.com/details/faqs) says for Fire TV that "a physical device isn't required at any stage of submission or judging" |

---

## What's next

**Run the candidate APK workflow and retain its receipt.** This is the remaining
track proof: install, normal launch, D-pad journey, logs, screenshot and APK digest.

**Make the dispatch real.** `RollbackDispatcher` is a one-method protocol. Wiring
it to a deployment pipeline turns the governed decision into a governed action
without touching the governance code.

**Rank a crowded window instead of refusing it.** The baseline and the window
anchor are fixed; the remaining half of what the corpus pointed at is not. When
several changes land together Mercury says how many and names none of them, where a
better tool would rank them on what they touched against what the metric measures.
That is the change most likely to move held-out recall off 4.8% without giving back
the precision the crowding gate bought. A runtime file-list filter is on since
2026-09-27; this corpus's labels cannot say whether it helps, because they let any
commit cause a regression.

**Lengthen the series.** 65 of the 300 late-look cases are undetectable by any rule
here, because a six point series polled every ten minutes has no readings left
before an onset four polls back. That ceiling is arithmetic, it is published as
`detectability_ceiling`, and only more data moves it.

**Validate the durable governance ledger under deployed concurrency.** DynamoDB now
stores staged actions, spent nonces, deployment markers and handoffs with conditional
writes. The remaining work is operational evidence under concurrent Lambda instances.

---

## What we learned

A dashboard that does not call its own API is a screenshot. The most valuable
thing we built was not a feature but a constraint: every number carries its
provenance, and the screen shows it. Once that was in place, the honest fallback
stopped being a compromise and started being the design.

---

## What is not finished

Stated here rather than left for a judge to find:

* **Candidate runtime receipt pending.** `.github/workflows/android-tv-emulator.yml`
  is the allowed-target path: it retains the exact APK, logs, screenshot and receipt.
  `docs/FIRE_TV_BUILD.md` documents the evidence contract and official FAQ basis. A local
  dry run of that journey on 2026-09-29 reached 4 of 5 receipt events on an Android TV
  emulator against the deployed build; the fifth, the handoff publish, needed the redeploy
  below, because the deployed page predated the revision retry. Full 5-of-5 journeys
  followed on 2026-09-30 (runs 36661614006 and 36669903334), and run 36798893479 on
  2026-10-01 re-drove all five events against the candidate-language page.
* Mercury ships no deployment pipeline integration. When governance passes, the
  response says in plain words that no pipeline was contacted.
* The public cockpit is deployed at
  `https://leol25sezuvokpankox5cvjopm0gtvfa.lambda-url.eu-west-1.on.aws/`; `/health`
  publishes the deployed build SHA. It runs the current build: probed on 2026-09-30,
  `/health` reported `b2f7868969ff475a2c10ccc686243d48e7d18692`, with the departures board,
  self-hosted fonts and the candidate language. On 2026-09-26 it ran `6dd76bd`, which
  predates the departures board design and loads Google Fonts. It uses labelled offline fixtures and record-only rollback
  dispatch until real telemetry and pipeline credentials are configured.
* Anomaly detection is a threshold, not a model. A regular nightly batch will look
  like an anomaly. The baseline now stops at the onset rather than containing the
  spike, but the detector still needs at least two readings before that onset, so 65
  of the 300 late-look cases in the corpus are undetectable whatever it does. That
  ceiling is published as `detectability_ceiling`.
* Naming a change is right 50.0% of the time over 58 held-out namings, and it
  fires on about one regression in twenty-one there. That level assumes every
  regression shows within 75 minutes, as the generator draws them. That is why the headline is the refusal. The
  figure ships with every answer, so nobody has to take the README's word for it at
  the moment they are deciding whether to revert.
* When several changes land in the window Mercury says how many and names none of
  them. It does not rank them. Ranking is the next thing worth building and it is
  not built.
* The held-out side is small: 17 commits and 58 namings, so the 95% interval on
  precision runs from 37.5% to 62.5%. The 75 minute window won on train partly
  because the corpus's own delay assumption reaches 75 minutes, and the held-out side
  shares that assumption, so it cannot test it. `python scripts/attribution_split.py`
  publishes the held-out precision at delay ceilings of 60 to 180 minutes: 54.0%,
  50.0%, 41.5%, 38.6% and 27.3%.
* That an on-call engineer is in a room with a television during an incident is an
  assumption. It has never been tested with a responder. The same page and the same
  HTTP surface render on a laptop, so what that assumption risks is the surface,
  not the engine.
* Voice output is the browser's speech synthesis. There is no Alexa skill and no
  Alexa integration in this repository, and no voice input anywhere: the TV surface
  is a D-pad and a screen.

---

## Built with

Python 3.11, FastAPI, Pydantic, httpx, boto3, pytest. Kotlin, Android Leanback,
Gradle. AWS Cost Explorer, AWS CloudWatch, AWS Lambda, Terraform. GitHub REST API,
GitHub Actions.

---

## Try it

The repository is private today. The event's [FAQ](https://amazonappdev2026.devpost.com/details/faqs) sets the rule for that
case: "Add the Amazon and Devpost reviewers as collaborators before the submission
deadline". That is an owner step taken near submission; until then, the clone
works only for collaborators. The MIT `LICENSE` file stays in the repository either
way. With the source in hand, start at `pip install`.

```bash
git clone https://github.com/upgradedev/mercury_amazon.git   # needs collaborator access while private
cd mercury_amazon
pip install -e ".[dev]"
python -m pytest tests/ -q
MERCURY_ROLLBACK_SECRET=demo python -m src.interfaces.mcp_server
```

Open `http://127.0.0.1:8002/`. No credentials needed: the commits are read from
your own checkout and every panel labels its data source on screen.

---

## Track declaration

* **Primary track:** Fire TV.
* **Mini challenges:** none. Single-track entry.

---

## Product feedback

* **Fire TV surfaces used:** no Fire TV hardware and no Vega device. The wallboard APK
  was exercised on the Android SDK emulator (37.1.11) with the Android TV API-30 x86
  system image on Windows, hardware-accelerated through WHPX, driven over adb
  (install, Leanback launch, D-pad key events, screencap) with the page reporting
  journey events to logcat over a WebView JavaScript bridge. The FAQ's explicit
  allowance of the Android TV emulator as an evidence target is what makes this entry
  possible without hardware.
* **What worked well.** The emulator booted headless in about a minute and adb needed
  no authentication; the APK installed and launched first try, and every D-pad press
  reached the page. The logcat bridge proved reliable: page load, anomaly
  attribution, rollback staging and the record-only confirmation all arrived as
  journey events in one run.
* **What needs work.** The emulator ignores `ANDROID_USER_HOME`, which every other
  SDK tool honours, and wants `ANDROID_AVD_HOME` or `ANDROID_SDK_HOME` instead; the
  mismatch costs a debugging cycle and is documented nowhere near the error. With
  remote debugging off, a WebView on the emulator offers no DOM introspection over
  adb, so diagnosing a missing page event meant probing the server rather than
  looking at the page.
* **Would we build with these tools again:** yes for the emulator path, which carried
  a D-pad and WebView wallboard end to end. The final receipt still wants hardware
  for what the emulator cannot show (remote auto-repeat, Leanback focus behaviour on
  a real TV), and that run is pending.
