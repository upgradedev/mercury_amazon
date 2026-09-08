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

**This does not satisfy the Fire TV track's device requirement.** That track asks
for the product running on a Fire TV device, and no Fire TV emulator exists to
stand in for one. No APK exists, the Kotlin has never been compiled, and nothing has
been installed on a device, so a recording made from this shot list shows the
cockpit and the governance path but not the platform. What the platform would add
is a D-pad and a television; nothing in it listens for speech. The arrow keys drive
`docs/firetv_nav.js`, which is the same file the Leanback `MainActivity` calls
through its JavaScript bridge, so the navigation being shown is the navigation the
APK would drive. That is the honest limit of what this recording proves.
`docs/FIRE_TV_BUILD.md` records the verbatim build failure that stops it going
further.

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
**Expected on screen:** the hero reads `Cannot attribute this.` followed by the
number of changes that landed before the spike started, and the eyebrow reads
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
**Expected on screen:** the hero names the commit, quotes its message with the
author, and the line beneath reads that when this correlator names a commit it is
the one that caused the reading 52% of the time, over 113 namings in a corpus of
1160 labelled cases, with the command that produced the figure.
**Point to make:** it names a change only when exactly one landed in the window,
and it still shows the odds at the moment somebody would act. That line is read
from `correlation_trial_summary.json` and shipped in the response as
`attribution.measured_accuracy`; the page never computes it.

### 5. Where each half of that answer came from, without scrolling. 1:08 to 1:24

**Action:** none. Hold on the two badges inside the hero card, beside the anomaly
factor. Do not scroll.
**Expected on screen:** two badges from the same response: `OFFLINE FIXTURE`
against *metric series (offline-fixture)*, and `LIVE` against *commit history
(local-git)*.
**Point to make:** the words, not the slug, and next to the number rather than
below the fold. Measured at 1920x1080 the factor renders at y=274 and the stamp at
y=453, both inside the first screenful, which matters because a wallboard is never
scrolled. `python scripts/measure_legibility.py` exits 1 if that stops being true.

### 6. The D-pad moves in space, and BACK does not close the room. 1:24 to 1:41

**Action:** press Right, Right, Down, Right, Left, then Enter on the Delivery
velocity tile, then Escape.
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

### 8. The governance refusal. 1:56 to 2:09

**Action:** Escape to the wall, press **checkout-api** so a rollback target exists
again, focus **Stage governed rollback**, press Enter with the Secret field still
empty.
**Expected on screen:** the incident panel opens with
`No governance secret entered. Staging a rollback needs the deployment secret from
the Secret field.`
**Point to make:** the one irreversible control on the screen refuses in plain
words rather than failing silently or pretending to work.

### 9. Staging mints a token bound to the change. 2:09 to 2:20

**Action:** type the secret into the Secret field, then press **Stage governed
rollback** again.
**Expected on screen:** state `PENDING_CONFIRMATION`, the action id, the target
service and commit, a truncated SHA-256 payload hash, and the lease in seconds.
The hero figure becomes the lease remaining and the confirmation prompt appears
beneath it. The Confirm button becomes enabled and its reason line changes to say
a token was issued.
**Point to make:** the token is an HMAC over the action id and a hash of exactly
this payload. Edit the target after staging and it stops applying.

### 10. Confirming says what it did not do, and the second press is refused. 2:20 to 2:34

**Action:** press **Confirm rollback**, then press it a second time.
**Expected on screen:** first, status `EXECUTED` and the output verbatim:
`Governance passed for 'checkout-api' to commit <sha>. Recorded locally. No
deployment pipeline was contacted`, followed by the line naming the record-only
dispatcher. Then, on the second press,
`Request failed HTTP 409. NOT_PENDING: Action '<id>' is in state EXECUTED, not
PENDING_CONFIRMATION.`
**Point to make:** read the first sentence out. The product tells the room it did
not deploy anything, on the screen, in the moment of success. Single use is then
enforced by the server and the denial is named rather than swallowed. Leaving the
staging on screen past its lease produces `HTTP 410. LEASE_EXPIRED` in the same
way.

### 11. What is not built. 2:34 to 2:48

**Action:** cut to `docs/FIRE_TV_BUILD.md` open in an editor, on the recorded
build failure.
**Narration:** no APK exists, the Kotlin has never been compiled, and nothing has
run on Fire TV hardware. The refusals, the correlation and the governance path are
real and were driven live in this recording. The Fire TV device is not.
**Point to make:** end on the limitation rather than letting a judge find it.

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
