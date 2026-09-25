# Mercury demo video: shot list

**Status: PLAN ONLY. No video has been recorded.** Every timing below is intended,
not measured against a take.

Total intended runtime **168 seconds**, inside the 180 second limit.

## The rule this list follows

Every beat is an action that exists in the repository today and was performed
during the session that wrote this file. No beat asks the presenter to show a
screen that has to be built first, and no beat asks for a number that is not
computed on screen from a response.

## Platform shown, and what that costs

**Every beat is a desktop browser at 1920x1080 against a local server**
(`python -m src.interfaces.mcp_server` on `http://127.0.0.1:8002/`), driven with
the arrow keys and Enter and Escape.

**The desktop rehearsal is not the final Fire TV track proof.** The event FAQ accepts
Android TV Emulator, and `.github/workflows/android-tv-emulator.yml` installs the
exact APK, launches it normally and drives the same D-pad path. The final recording
should use that allowed target after its receipt exists. Arrow keys in this rehearsal
still drive `docs/firetv_nav.js`, the same navigator the Leanback `MainActivity`
calls through its bridge; they prove the interaction before the APK runtime proof,
not in place of it.

## Setup before recording

```bash
python -m pytest tests/ -q
MERCURY_ROLLBACK_SECRET=demo python -m src.interfaces.mcp_server
```

Open `http://127.0.0.1:8002/` at 1920x1080. Leave the Secret field empty; beat 8
depends on it being empty. Do not paste the secret until beat 9.

---

## Beats

### 1. The question, and why it is usually the wrong one. 0:00 to 0:13

**On screen:** the cockpit at rest, one second before the page has answered.
**Action:** none. Hard cut in on the loaded page.
**Narration:** an incident starts, somebody asks what we just deployed, and half
the time that is the wrong question. Reverting on it costs an hour.
**Expected result:** the hero fills the frame with a single sentence, not a grid.

### 2. The answer arrives without being asked, and it is usually a refusal. 0:13 to 0:31

**Action:** reload the page. Do not click anything.
**Expected on screen:** the page calls `GET /health` then
`POST /mcp/tools/what_changed` on load, and the hero renders whatever the
correlator concluded, with the anomaly factor as the large figure to its left.
**Point to make:** nothing was clicked, and the headline claim of this product is
that against 1160 labelled incidents it sees a real anomaly and names nobody 81.1%
of the time. Say that figure; it is in the README and in
`correlation_trial_summary.json`, and it is one of only two numbers in this
document that do not come off the screen. Say what the refusal is and what it is
not: Mercury cannot attribute, and it never says the deploy is innocent.

The sha and the factor come from the response and change with the checkout. Read
whatever is on screen. Do not say any other number from this document.

### 3. The refusal that carries the product. 0:31 to 0:47

**Action:** press **release-train** in the demo row.
**Expected on screen:** the board's verdict line flips to `Cannot attribute this:`
followed by the number of changes that landed before the spike started, and the eyebrow reads
`Incident, too many changes to name one`. The cause line beneath is the server's
own refusal statement: a refusal to guess, not a finding that none of them caused
it, and rolling back on this answer would be a guess. Both rollback buttons stay
disabled and their reason lines are visible underneath.
**Point to make:** the anomaly is real and Mercury still names nothing, because a
burst of changes landed and nothing in a metric series says which of them did it.
Read the cause line out, because it is the sentence that keeps this honest: the
refusal is not an acquittal of the changes it refused to choose between.

The number of changes in the window comes from the checkout's own `git log` and
changes with it. Read what is on screen.

### 4. When it does name one, it prints its own odds. 0:47 to 1:08

**Action:** press **checkout-api**.
**Expected on screen:** the verdict line names the commit, the board quotes its
message, and the line under the verdict gives the measured naming precision
(52.2%). The Evidence section further down carries the full sentence: over 113
namings in a corpus of 1160 labelled cases, with the command that produced it.
**Point to make:** it names a change only when exactly one landed in the window,
and it still shows the odds at the moment somebody would act. That line is read
from `correlation_trial_summary.json` and shipped in the response as
`attribution.measured_accuracy`; the page never computes it.

### 5. Where each half of that answer came from, without scrolling. 1:08 to 1:24

**Action:** none. Hold on the two badges in the board's answer row, beside the
anomaly factor. Do not scroll.
**Expected on screen:** two badges from the same response: `OFFLINE FIXTURE`
against *metric*, and `LIVE` against *commits: local-git*.
**Point to make:** the words, not the slug, and next to the number rather than
below the fold. Measured at 1920x1080 the factor renders at y=189 and the stamp at
y=337, both inside the first screenful, which matters because a wallboard is never
scrolled. `python scripts/measure_legibility.py` exits 1 if that stops being true.

### 6. The D-pad moves in space, and BACK does not close the room. 1:24 to 1:41

**Action:** press Right, Down, Down, Up, then Down until the ring reaches the
Evidence tiles and Right to Delivery velocity, Enter, then Escape.
**Expected on screen:** the amber focus ring jumps to the nearest control in the
pressed direction and the label at the right of the key hint bar changes with it.
On Enter the tiles are replaced by the Delivery velocity panel and the BACK legend
changes from `Exit to the Fire TV launcher` to `Back to the wall`. On Escape the
wall returns and the legend changes back.
**Point to make:** movement is geometric, not a walk down the DOM. The disabled
Confirm button is skipped rather than focused, because a ring on a dead control is
a lie about what the remote can do, and BACK is answered by the page before it
would close the application.

### 7. Two data sources, one screen. 1:41 to 1:56

**Action:** in the Delivery velocity panel press Enter on **Load DORA velocity**.
Then Escape, Right to Cloud spend, Enter, then Enter on **Scan AWS spend**.
**Expected on screen:** the DORA response carries an `OFFLINE FIXTURE` badge whose
detail begins `GITHUB_TOKEN is not set, so no live call was attempted`. If the
recording machine has AWS credentials, the spend response carries a `LIVE` badge
reading `aws-cost-explorer` with the real `GetCostAndUsage` call described beneath
it. If it does not, that panel shows `offline-fixture` too.
**Point to make:** the same screen shows a live source and a recorded one at the
same moment, each labelled. Say on camera which machine state you are recording
in. Do not read the spend figures aloud if they are live: they are a real account's
numbers.

### 8. Fixture boundary: the public control stays effect-free. 1:56 to 2:09

**Action:** Escape to the wall, press **checkout-api** so a rollback target exists
again, focus **Stage governed rollback**, and press Enter with the Secret field empty.
**Expected on screen:** `PENDING_CONFIRMATION`, `DPAD_RECORD_ONLY_DEMO` and the
explicit `NONE` external effect. Confirm becomes enabled.
**Point to make:** this route accepts only the labelled recorded fixture and is
disabled whenever any external dispatcher is selected.

### 9. Staging mints a token bound to the change. 2:09 to 2:20

**Action:** hold on the staged proposal produced by the previous D-pad press.
**Expected on screen:** state `PENDING_CONFIRMATION`, the action id, the target
service and commit, a truncated SHA-256 payload hash, and the lease in seconds.
The hero figure becomes the lease remaining and the confirmation prompt appears
beneath it. The Confirm button becomes enabled and its reason line changes to say
a token was issued.
**Point to make:** the token is an HMAC over the action id and a hash of exactly
this payload. Edit the target after staging and it stops applying.

### 10. Confirm, then publish the responder handoff. 2:20 to 2:34

**Action:** press **Confirm rollback**, then **Publish handoff**.
**Expected on screen:** status `RECORDED_ONLY` and the output verbatim:
`Governance passed for 'checkout-api' to commit <sha>. Recorded locally. No
deployment pipeline was contacted`, followed by the line naming the record-only
dispatcher. Confirm then goes dark, with its reason line underneath:
`That token has been spent. Confirming again is refused by name. Stage again for a
new one.` The handoff shows its fixed responder, confirmed facts, next step and
revision. Single use is enforced by the server too.
**Point to make:** read the first sentence out. The product tells the room it did
not deploy anything, on the screen, in the moment of success. Single use is then
enforced on the screen and by the server, and the denial is named rather than
swallowed. Leaving the
staging on screen past its lease produces `HTTP 410. LEASE_EXPIRED` in the same
way.

### 11. Runtime evidence boundary. 2:34 to 2:48

**Action:** cut to `docs/FIRE_TV_BUILD.md` and the Android TV workflow.
**Narration:** the exact APK must complete the same normal-launch D-pad journey in
Android TV Emulator before a runtime receipt is claimed. The official FAQ permits
this route and makes physical hardware optional.
**Point to make:** end on the current evidence boundary rather than implying it.

---

## Numbers policy for the recording

Read numbers off the screen as they appear. Latency, the anomaly factor, the sha,
the lease, the number of changes in the window and the spend all vary per machine
and per run.

Two figures are exceptions and are spoken from the script rather than read off the
screen, because they describe the labelled corpus and not this run: the 81.1%
refusal rate in beat 2, and the 52% precision over 113 namings in beat 4. Both are
written by `python scripts/correlation_trial.py` into
`correlation_trial_summary.json`, the README quotes the same file, and a test
compares the two. If a re-run moves them, re-record those beats rather than saying
the old number.
