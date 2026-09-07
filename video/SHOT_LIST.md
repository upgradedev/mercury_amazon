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
for the product running on a Fire TV device or in the official Fire TV emulator.
No APK exists, the Kotlin has never been compiled, and nothing has been installed
on a device, so a recording made from this shot list shows the cockpit and the
governance path but not the platform. The arrow keys drive
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

Open `http://127.0.0.1:8002/` at 1920x1080. Leave the Secret field empty; beat 7
depends on it being empty. Do not paste the secret until beat 8.

---

## Beats

### 1. The question. 0:00 to 0:12

**On screen:** the cockpit at rest, one second before the page has answered.
**Action:** none. Hard cut in on the loaded page.
**Narration:** an incident starts, somebody asks what broke, and the answer is
spread across six tabs on six laptops.
**Expected result:** the hero fills the frame with a single sentence, not a grid.

### 2. The answer arrives without being asked. 0:12 to 0:30

**Action:** reload the page. Do not click anything.
**Expected on screen:** the page calls `GET /health` then
`POST /mcp/tools/what_changed` on load. The hero reads
`Commit <sha> raised HTTPCode_Target_5XX_Count on checkout-api`, with the anomaly
factor as the large figure to its left, the baseline underneath it, and the commit
message quoted below with its author.
**Point to make:** nothing was clicked. The wallboard answers the question the
room walked in with.

The sha and the factor come from the response and change with the checkout. Read
whatever is on screen. Do not say a number from this document.

### 3. Where each half of that answer came from. 0:30 to 0:45

**Action:** none. Hold on the two badges in the hero footer.
**Expected on screen:** two badges, side by side, from the same response:
`offline-fixture` against *metric series*, and `local-git` against *commit
history*. Beside them the measured latency line,
`POST /mcp/tools/what_changed answered 200 in NNN ms`, timed in the page with
`performance.now()`.
**Point to make:** the metric is simulated and the screen says so in the same
place as the number. The commits are real ones read from the checkout. A viewer
never has to trust the server about which is which.

### 4. The D-pad moves in space. 0:45 to 1:02

**Action:** press Right, Right, Down, Right, Left on the keyboard.
**Expected on screen:** the amber focus ring jumps to the nearest control in the
pressed direction, and the label at the right of the key hint bar changes with it:
`Focused: Ask what changed`, then `Focused: Stage governed rollback`, then
`Focused: Delivery velocity panel`, then `Focused: Cloud spend panel`.
**Point to make:** movement is geometric, not a walk down the DOM. The disabled
Confirm button is skipped rather than focused, because a ring on a dead control is
a lie about what the remote can do.

### 5. CENTER drills in, BACK returns. 1:02 to 1:18

**Action:** press Enter on the Delivery velocity tile, then Escape.
**Expected on screen:** on Enter the three tiles are replaced by the Delivery
velocity panel and the hint bar's BACK legend changes from
`Exit to the Fire TV launcher` to `Back to the wall`. On Escape the wall returns
and the legend changes back.
**Point to make:** BACK is answered by the page before it would close the
application, so the war room is never shut by accident mid-incident.

### 6. Two data sources, one screen. 1:18 to 1:35

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

### 7. The refusal. 1:35 to 1:48

**Action:** Escape to the wall, focus **Stage governed rollback**, press Enter with
the Secret field still empty.
**Expected on screen:** the incident panel opens with
`No governance secret entered. Staging a rollback needs the deployment secret from
the Secret field.`
**Point to make:** the one irreversible control on the screen refuses in plain
words rather than failing silently or pretending to work.

### 8. Staging mints a token bound to the change. 1:48 to 2:05

**Action:** type the secret into the Secret field, then press **Stage governed
rollback** again.
**Expected on screen:** state `PENDING_CONFIRMATION`, the action id, the target
service and commit, a truncated SHA-256 payload hash, and the lease in seconds.
The hero figure becomes the lease remaining and the confirmation prompt appears
beneath it. The Confirm button becomes enabled and its reason line changes to say
a token was issued.
**Point to make:** the token is an HMAC over the action id and a hash of exactly
this payload. Edit the target after staging and it stops applying.

### 9. Confirming says what it did and did not do. 2:05 to 2:22

**Action:** press **Confirm rollback**.
**Expected on screen:** status `EXECUTED`, and the output verbatim:
`Governance passed for 'checkout-api' to commit <sha>. Recorded locally. No
deployment pipeline was contacted`, followed by the line naming the record-only
dispatcher this deployment is running.
**Point to make:** read that sentence out. The product tells the room it did not
deploy anything, on the screen, in the moment of success.

### 10. The same button, refused by name. 2:22 to 2:35

**Action:** press **Confirm rollback** a second time.
**Expected on screen:** `Request failed HTTP 409. NOT_PENDING: Action '<id>' is in
state EXECUTED, not PENDING_CONFIRMATION.` The Confirm reason line reads that the
token has been spent.
**Point to make:** single use is enforced by the server and the denial is named,
not swallowed. Leaving the staging on screen past its lease produces
`HTTP 410. LEASE_EXPIRED` in the same way.

### 11. What is not built. 2:35 to 2:48

**Action:** cut to `docs/FIRE_TV_BUILD.md` open in an editor, on the recorded
build failure.
**Narration:** no APK exists, the Kotlin has never been compiled, and nothing has
run on Fire TV hardware. The navigation, the correlation and the governance path
are real and were driven live in this recording. The Fire TV device is not.
**Point to make:** end on the limitation rather than letting a judge find it.

---

## Numbers policy for the recording

Read numbers off the screen as they appear. Latency, the anomaly factor, the sha,
the lease and the spend all vary per machine and per run. This document contains
no measured value for that reason.
