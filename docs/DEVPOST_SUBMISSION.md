# Devpost submission text: Mercury

**Track:** Fire TV
**Mini challenge:** Open Source

---

## Tagline (22 words)

Mercury puts an on-call engineer's incident evidence on the Fire TV in the room,
and takes the governed rollback from the remote.

---

## Inspiration

An incident starts and everyone opens the same six tabs on six different laptops.
The version control host is in one, the metrics console is in another, the
deployment pipeline is in a third, and the one question that matters is spread
across all of them: what changed just before this broke?

There is already a screen in that room that everyone can see. It is showing
nothing. Mercury puts the answer on it, and lets the person holding the remote act
on the answer without opening a laptop at all.

---

## What it does

**Answers "what changed?"** Mercury reads an error metric series and a commit
history, decides whether the newest reading is an anomaly against its own
baseline, and attributes it to the closest commit that landed before it. When it
cannot attribute the anomaly to anything, it says so and offers no rollback. That
refusal has its own tests, because a war room tool that always has an answer is
worse than one that admits when it does not.

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
minimum. The real file is executed in Node against a synthetic grid by 16
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

## What we learned

A dashboard that does not call its own API is a screenshot. The most valuable
thing we built was not a feature but a constraint: every number carries its
provenance, and the screen shows it. Once that was in place, the honest fallback
stopped being a compromise and started being the design.

---

## What is not finished

Stated here rather than left for a judge to find:

* The APK is assembled by GitHub Actions and uploaded as an artifact. It has never
  been installed on a Fire TV device or run in the emulator, because no hardware
  and no Android SDK were available. `docs/FIRE_TV_BUILD.md` records the verbatim
  local build failure.
* Mercury ships no deployment pipeline integration. When governance passes, the
  response says in plain words that no pipeline was contacted.
* The live endpoint answers 200 but runs an older build, so the readiness gates
  for deployment matching (D2, G2) fail and are reported as failing.
* Anomaly detection is a threshold, not a model. A regular nightly batch will look
  like an anomaly.
* Voice output is the browser's speech synthesis. There is no Alexa skill and no
  Alexa integration in this repository.

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
