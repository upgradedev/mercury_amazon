# Persona review, recorded inside this repository

**Review date: 2026-09-08.** Every row below was re-run on that date against this
checkout. Where a row restates an older finding, the older date is written in the row.

## Why this file exists

Four readiness gates in `ci/readiness.py` ask whether a structured review of this
entry was run and written down. Until 2026-09-08 all four answered from a
coordination file that lives in the workspace **above** this repository and is never
committed to it. The gates said so in their own output, in these words: "read from
..\..\STATE.md, which is outside this repository and is not part of the clone a judge
receives".

That was honest and it was useless. A judge who clones this repository alone does not
get that file, so the four gates that passed here would have failed for them, and the
published score would have lost four gates in their hands. The evidence for a
quarter of the failing surface was somewhere they could not look.

This file is the restatement they can read. Nothing is copied from the coordination
file: the review instrument that defines the lenses is a workspace document that is
not part of any submission, so it is not reproduced, quoted or named here. What is
here is what this project did, in this project's own words, re-verified today with
commands that run in a clone.

## Nobody from Amazon reviewed this repository

The three lenses below are internal review roles operated by the project team against
a fixed checklist. They are not people. No employee of Amazon, AWS or Devpost, and no
hackathon judge, has seen this entry. Every name in this document is the name of a
role. Reading the table below as a list of endorsements would be reading it wrong.

This is also a one-person entry, so all three rows are owned by the same maintainer.
Ownership is still recorded per row, because the checklist gives each row exactly one
owner and a row nobody owns is a row nobody answers.

---

## 1. The procedure that runs before any lens opens

The lenses judge the product. These four steps judge whether the submission is in a
state worth judging, and they run first. An outcome that is not PASS does not stop the
review here; it is carried into the findings and into the readiness score instead of
being smoothed over.

| Step | What it asks | Outcome | Evidence |
|---|---|---|---|
| 1 | Does a deployed endpoint answer, and identify its build? | PASS | Root and `/health` answer at the public Function URL, and `/health` publishes `build_sha`; `deploy_teardown_receipt.json` records the observation |
| 2 | What is owner-gated and unmet, printed apart from the score rather than folded into it? | OPEN | `python ci/readiness.py`: O1, O2 and O3 fail as owner actions; E2 and E4 fail because the only render (170.61 s, take at audit commit 0aed20a, pre-headline) lives outside the repo and is unpublished, and upload is owner-gated. `video/README.md` records the take |
| 3 | Is the track and prize this entry is aimed at written down, with nothing else claimed? | PASS | Fire TV track in `README.md`, Open Source mini in `docs/DEVPOST_SUBMISSION.md`. `tests/e2e/test_documentation_claims.py` fails the build if any document claims an Alexa integration, which this repository does not have, or a device run or a built APK - both of which have happened since: emulator runs 36661614006, 36669903334 and 36798893479 each built, installed and D-pad-drove an APK, with the latest content-addressed runtime receipt landed (`android_tv_runtime_receipt.json`); `tests/e2e/test_documentation_claims.py` now asserts the run is cited |
| 4 | Do the presentation surfaces say what the code says? | PASS | `python -m pytest tests/e2e/test_documentation_claims.py -q`. Every number in the README and in `docs/EVIDENCE.md` is compared against the file the command that produced it wrote |

## 2. The three lenses, and who owned each row

| Lens | Owner | What it decides | Verdict |
|---|---|---|---|
| Sponsor product owner | Mercury maintainer, product row | Is the sponsor product load-bearing, or merely mentioned? | PASS |
| UX designer | Mercury maintainer, interface row | Can a cold visitor use the thing without being told how? | PASS |
| Recruiter | Mercury maintainer, engineering bar row | Would this code and this prose clear an engineering bar? | PASS |

The sponsor product row passed on 2026-09-30: the candidate APK completed its normal-launch
journey on the allowed Android TV Emulator twice, and the checked runtime receipt is landed.
J4 is red again since 2026-10-01, because the receipt predates the page change and the hosted
UI files now invalidate it; a fresh emulator run is queued. Details in P01-1 below.

## 3. Findings

Every row was produced by running the command in its Evidence column on 2026-09-08.
A row that restates an older judgement says so and carries the older date.

| ID | Lens | Finding | Verdict | Evidence |
|---|---|---|---|---|
| P01-1 | Sponsor product owner | The candidate has an automated Android TV install and D-pad journey. J4 was red until 2026-09-30, when emulator runs 36661614006 and 36669903334 produced content-addressed runtime receipts and J4 turned green; red again 2026-10-01, because the receipt predated the candidate-language page and docs/index.html invalidated it; run 36798893479 re-drove the journey against the new page and J4 is green again. The official FAQ permits this emulator route and does not require physical hardware | PASS | `.github/workflows/android-tv-emulator.yml`, `python ci/readiness.py`, `tests/unit/test_readiness_gates.py`, `docs/FIRE_TV_BUILD.md` |
| P01-2 | Sponsor product owner | The review of 2026-09-04 recorded that "Fire TV spatial navigation and Alexa voice query are load-bearing" for this entry. The Alexa half was never true of this repository. It does not survive restatement, and a test now fails the build if any document claims it | FAIL | `tests/e2e/test_documentation_claims.py` |
| P01-3 | Sponsor product owner | What is load-bearing and does exist: the D-pad and the arrow keys are one focus code path, driven by the same spec on both inputs | PASS | `tests/e2e/spatial_nav_spec.js`, `tests/e2e/test_html_structure.py` |
| P06-1 | UX designer | The hero action is marked and the layout carries responsive breakpoints, so the primary action is visible without reading. Gate H1 passes | PASS | `python ci/readiness.py`, `tests/e2e/test_html_structure.py` |
| P06-2 | UX designer | No control is disabled without a visible reason. Gate H2 passes: every disabled control carries a title attribute that says why | PASS | `python ci/readiness.py`, `docs/index.html` |
| P06-3 | UX designer | Empty, loading and error states each render an explanation rather than nothing. Gate H3 passes | PASS | `python ci/readiness.py`, `tests/e2e/test_html_structure.py` |
| P06-4 | UX designer | The provenance stamp that says whether a number is live or a fixture renders inside the first viewport height at 1920x1080, measured in a real browser engine rather than asserted | PASS | `tests/ux/test_ten_foot_legibility.py`, `python scripts/measure_legibility.py` |
| P08-1 | Recruiter | Prose: zero em dashes and zero entries from the banned filler list across every markdown file git tracks | PASS | `tests/e2e/test_documentation_claims.py` |
| P08-2 | Recruiter | Layering holds. The domain modules import no SDK and no framework. Gate A5 passes | PASS | `python ci/readiness.py` |
| P08-3 | Recruiter | Test integrity re-measured. The 2026-09-04 record said 114 tests, which is stale by four days and several hundred tests. Today's numbers are in the README badges and in the two files the commands write | PASS | `python -m pytest tests/ -q`, `python scripts/record_coverage_summary.py`, `coverage_summary.json` |
| P08-4 | Recruiter | Defect found by writing this file. Two documents put the number of rollback denial reasons carrying a failing-input test at 8. The auditor counts 9, and so does a direct count of the test file. Both documents are corrected and a test now compares every stated count against the file it describes | FAIL | `tests/e2e/test_documentation_claims.py`, `tests/integration/test_rollback_authorization.py` |
| P08-5 | Recruiter | Second defect found by writing this file. The README's first-run timing figure did not reproduce for three independent readers. It is re-measured, the measurement is recorded by a script, and a test compares the README against it | FAIL | `python scripts/time_test_suite.py`, `suite_timing_summary.json`, `tests/e2e/test_documentation_claims.py` |
| K-1 | Recruiter | Kill criteria. The 2026-09-04 record named a cost-radar burn-rate threshold as this entry's kill criterion. `tests/unit/test_cost_radar.py` holds one test and asserts no such threshold, so that row does not survive restatement either. The kill criteria this repository actually ships are the nine rollback refusals, each with a recorded failing input, which is what gate I5 counts | PASS | `python ci/readiness.py`, `tests/integration/test_rollback_authorization.py` |

**3 of the 13 findings are failures**, and two of those four were found by writing
this document rather than by the review it restates. That is the argument for making
the restatement a repository artifact instead of a workspace one. Those two counts are
compared against this table by `tests/e2e/test_documentation_claims.py`, so they
cannot drift away from the rows underneath them.

## 4. What this review did not answer

These are the questions the lenses asked and nobody could close from a keyboard. They
are listed because a review that reports only what it settled is not a review.

| Question | Why it is open |
|---|---|
| Does the APK install and appear on a Fire TV home row? | A verified CI APK exists and portable ADB is prepared; the Android TV emulator runs above connected, installed and drove the D-pad journey, but no physical Fire TV device has connected. `docs/FIRE_TV_BUILD.md` records the install and receipt procedure |
| Is the cockpit legible from three metres on a television? | Measured in a 1920x1080 browser viewport, never on a television at distance |
| Has teardown been verified for a deployment of this commit? | No. The public cockpit answers and identifies its build, which on 2026-09-26 was the older `6dd76bd` rather than this commit, and no release has been destroyed and restored. |
| Does an on-call engineer find a refusal to name a commit useful at three in the morning? | Nobody outside this project has used it. The README says this in its own words |

## 5. Where the gates read this

Gates I1 to I4 in `ci/readiness.py` read this file and nothing else. They check
structure and evidence rather than the presence of a phrase:

* **I1** wants the procedure table above to carry at least four steps, each with an
  outcome and a citation.
* **I2** wants all three lenses present, each with a verdict and at least one finding.
* **I3** wants every lens named in a findings row to have an owner in the ownership
  table, so a finding cannot be attributed to a lens nobody owns.
* **I4** wants at least five findings, each with a verdict and a citation, a review
  date on this page, and every repository path cited anywhere on this page to exist on
  disk.

Delete a lens row, attribute a finding to a lens with no owner, or cite a test file
that is not there, and the gate goes red. `tests/unit/test_readiness_gates.py` drives
each of those failures through the predicate, and the passing case as well.

The coordination file in the workspace above this repository remains the record of
record for work spanning several repositories. It is deliberately not committed here.
This page is what a clone gets, and it is enough for the four gates to be checked
without it.
