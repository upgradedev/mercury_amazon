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
needs reverting is the one where the reading is inside its baseline. Mercury sees an
anomaly and names nobody 81.1% of the time, stays quiet on 199 of 200
healthy series, and refuses outright on 60 of 60 telemetry gaps. When it does name
a change, it is right 52.2% of the time over 113 namings, and it prints that on the
screen beside the name. Then it renders where the people are. A Fire TV in the room
is one of those places and the one this entry is built for: a screen everyone can
see, driven by a remote, with the evidence readable from a sofa. The screen is the
delivery; the engine is the thing.

---

## What it does

**Says when it cannot blame a deploy, and never says more than that.** Mercury reads
an error metric series and a commit history, decides whether the metric has stepped
up against a baseline taken from before the step, and looks for changes in the hour
before that step started. It names one only when exactly one landed there. When none
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
every case that has no cause drawn without reference to where any commit falls. It
reports precision and recall together, and splits the refusals by reason so a
blunter instrument cannot read as better judgement. Every `what_changed` response
carries `attribution.measured_accuracy`, read from that recorded summary rather
than recomputed, so the operator sees the odds at the moment they would act.

**Publishes what it used to get wrong.** The late-look hit rate was 3.3% because
the baseline contained the spike it was measuring. It is 8.3% at the shipped
settings and 18.7% with the crowding gate off, and the detector that produced the
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
full, with the sweep it was chosen from, and it was checked on two corpus seeds
that took no part in choosing it.

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
| Attribution accuracy | **Measured.** 1160 labelled cases scored by `python scripts/correlation_trial.py`. Naming precision 52.2% over 113 namings, recall 9.8% over 600 regressions, refusal on 81.1% of detected anomalies, all published and shipped in every answer as `attribution.measured_accuracy` |
| Fire TV device | **Not run.** No APK exists and nothing has been installed on hardware, and there is no Fire TV emulator to have run it in. The TV surface is a D-pad and a screen, with no voice input |

---

## What's next

**Build the APK and run it on hardware.** This is the gap that matters most. The
workflow is written and the Kotlin is there; neither has ever executed.

**Make the dispatch real.** `RollbackDispatcher` is a one-method protocol. Wiring
it to a deployment pipeline turns the governed decision into a governed action
without touching the governance code.

**Rank a crowded window instead of refusing it.** The baseline and the window
anchor are fixed; the remaining half of what the corpus pointed at is not. When
several changes land together Mercury says how many and names none of them, where a
better tool would rank them on what they touched against what the metric measures.
That is the change most likely to move recall off 9.8% without giving back the
precision the crowding gate bought, and it would be re-scored against the same
corpus.

**Lengthen the series.** 65 of the 300 late-look cases are undetectable by any rule
here, because a six point series polled every ten minutes has no readings left
before an onset four polls back. That ceiling is arithmetic, it is published as
`detectability_ceiling`, and only more data moves it.

**Persist the governance ledger.** Staged actions live in memory today, so a
restart forgets them. An audit trail that survives a restart is the difference
between a demo and something an on-call rota would rely on.

---

## What we learned

A dashboard that does not call its own API is a screenshot. The most valuable
thing we built was not a feature but a constraint: every number carries its
provenance, and the screen shows it. Once that was in place, the honest fallback
stopped being a compromise and started being the design.

---

## What is not finished

Stated here rather than left for a judge to find:

* **No APK exists.** A GitHub Actions workflow to assemble one is written and
  committed, but it has never executed: nothing has been pushed since it was
  added, so there are zero runs and zero artifacts. The Kotlin has never been
  compiled, and nothing has been installed on a Fire TV device, because no hardware
  and no Android SDK were available; there is no Fire TV emulator, so a device is
  the only place it can run. `docs/FIRE_TV_BUILD.md` records the verbatim local
  build failure and the receipt a device run would produce.
* Mercury ships no deployment pipeline integration. When governance passes, the
  response says in plain words that no pipeline was contacted.
* The live endpoint answers 200 but runs an older build, so the readiness gates
  for deployment matching (D2, G2) fail and are reported as failing.
* Anomaly detection is a threshold, not a model. A regular nightly batch will look
  like an anomaly. The baseline now stops at the onset rather than containing the
  spike, but the detector still needs at least two readings before that onset, so 65
  of the 300 late-look cases in the corpus are undetectable whatever it does. That
  ceiling is published as `detectability_ceiling`.
* Naming a change is right 52.2% of the time over 113 namings, and it fires on
  fewer than one regression in ten. That is why the headline is the refusal. The
  figure ships with every answer, so nobody has to take the README's word for it at
  the moment they are deciding whether to revert.
* When several changes land in the window Mercury says how many and names none of
  them. It does not rank them. Ranking is the next thing worth building and it is
  not built.
* The crowding gate was chosen on the corpus it is reported on. The direction was
  checked on two held-out seeds and held; the exact 52.2% is an in-sample figure.
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

```bash
git clone https://github.com/upgradedev/mercury_amazon.git
cd mercury_amazon
pip install -e ".[dev]"
python -m pytest tests/ -q
MERCURY_ROLLBACK_SECRET=demo python -m src.interfaces.mcp_server
```

Open `http://127.0.0.1:8002/`. No credentials needed: the commits are read from
your own checkout and every panel labels its data source on screen.
