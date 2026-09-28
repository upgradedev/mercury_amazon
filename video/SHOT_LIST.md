# Mercury demo video: shot list

**Status: RENDERED LOCALLY, NOT UPLOADED.** The current take of this plan was recorded on
2026-09-28 from a local run of this repository; `video/README.md` names the commit and
says how and where the render lives. The beat order below was probed the same day by driving the page with the
D-pad bridge against a local server and reading what each press brings on screen. Beat lengths are set by the
narration, not by this file: `video/generate-narration.py` measures each beat's
synthesized audio and the capture holds every beat for exactly that length.

The words spoken and the words captioned for each beat live in
`scripts/build_video_plan.py`, which writes `video/narration.json` and
`video/cue_sheet.json`. Edit the beat there and rerun it; never edit the JSON.

## The rule this list follows

Every beat is the page reacting to a real response from the running server, reached
with the remote's keys. No beat asks for a screen that has to be built first, no beat
narrates something the frame does not show, and no beat claims a number that is not
on screen or in `correlation_trial_summary.json`.

## Platform shown, and what that costs

**Every beat is desktop Chromium at 1920x1080 against a local server** started with
`MERCURY_OFFLINE=1 python -m uvicorn src.interfaces.mcp_server:app --port 8873`, driven
by calling `window.navigateDpad` with `UP`, `DOWN`, `LEFT`, `RIGHT`, `SELECT` and
`BACK`, which is the bridge the Leanback `MainActivity` calls for each remote key.
No mouse is used.

**The desktop rehearsal is not the final Fire TV track proof.** The event FAQ accepts
Android TV Emulator, and `.github/workflows/android-tv-emulator.yml` installs the
exact APK, launches it normally and drives the same D-pad path. That runtime receipt
is still pending, and the video says so in its closing beat.

## What the page does that shaped the order

* The D-pad navigator scrolls only as far as the focused control. Nothing is focusable
  above **Ask what changed**, so once the page has scrolled down the board's top row
  does not come back into view. The staging beat therefore comes before any beat
  that scrolls down.
* Confirm leaves the board where it is: the large figure reads **RECORDED, no
  pipeline contacted**, and **Publish handoff** is the next stop without a ring. The
  confirm beat holds on that board, and the capture refuses to go on unless the page
  is still at the top with the legend reading Next press: Publish responder handoff.
  Center then publishes and scrolls to the rollback steps, where **02 Confirm** says
  the token has been spent and confirming again is refused.
* How it answers and Who it is for open from a fourth tile on its own row under the
  three evidence tiles, so Down from Refresh handoff still lands on Incident evidence
  and Right from there on Delivery velocity, as the capture journey expects.
* Down from Refresh handoff scrolls past the handoff's own answer to Evidence behind
  the board, which prints the held-out sentence: 50.0% over 58 namings in 1160
  synthetic labelled cases. The handoff's next step stays below the fold.
* A panel's answer renders below its buttons. Center brings the top of it into view.
  An open panel holds the remote until Back closes it: Down at its foot scrolls the
  rest into view and the cursor stays on the panel's button. Check, in the Connection
  section, is reached from the wall, under the How it answers tile.
  The current take was recorded before this change, at `df5db06`: in it, Down from
  the Delivery velocity panel walks out to Check, and so does Down from Cloud spend.
* `DPAD_RECORD_ONLY_DEMO` and the `NONE` external effect are in the server's response
  but are not rendered on the page, so no beat claims to show them.
* Never press Center on **Read aloud** or **Setup**; the video has no product audio.

## Beats

| # | Beat | Keys | On screen |
|---|---|---|---|
| 1 | `beat_01_question` | none | The loaded board, focus on Ask what changed |
| 2 | `beat_02_board_on_load` | none | Five rows answered on load: Attributed, Nothing to revert, Cannot attribute, Cannot attribute, Insufficient data |
| 3 | `beat_03_crowded_refusal` | Down x4, Center | release-train: Cannot attribute this, N runtime changes landed; Next: No rollback offered; Stage and Confirm disabled |
| 4 | `beat_04_named_with_odds` | Up x3, Center | checkout-api: the commit named as the only runtime change, its message quoted, 50.0% held-out precision (synthetic, at most 75 minutes of lag) |
| 5 | `beat_05_provenance` | none | OFFLINE FIXTURE stamp under the reading, dashed STAND-IN against Mercury's commits |
| 6 | `beat_06_stage` | Up, Right, Center | Rollback staged, the lease counting down as the large figure, Next: confirm, record-only |
| 7 | `beat_07_confirm` | Right, Center | The board, not scrolled: RECORDED, no pipeline contacted, under Rollback recorded, not sent; the legend reads Next press: Publish responder handoff |
| 8 | `beat_08_handoff` | Center, Down | Publish handoff answers HTTP 200 and the page shows the rollback steps (token spent, confirming again refused); Down lands on Incident evidence under the held-out sentence: 50.0% over 58 namings in 1160 synthetic labelled cases |
| 9 | `beat_09_dpad` | Right, Center | Delivery velocity opens; the BACK legend changes to Back to the wall |
| 10 | `beat_10_fixtures` | Down, Back, Right, Center, Back | DORA answer with OFFLINE FIXTURE, scrolled within the panel; Back to the wall; Cloud spend answer with OFFLINE FIXTURE and SYNTHETIC figures; Back to the wall |
| 11 | `beat_11_build_check` | Down, Down, Center on Check | GET /health returned 200, the build's short SHA, GitHub live: no, fixture mode |

The title card before beat 1 says what the product is first: Mercury. An incident
board for the team's Fire TV. It names the deploy behind a spike only when it can.
One smaller line under it gives the provenance: a local run of commit `<sha7>` in
desktop Chromium, offline fixtures, record-only rollback, public deployment pending.
The closing card repeats the commit and says the public deployment and the Fire TV
runtime receipt are pending.

## Numbers policy for the recording

Numbers on screen are read off the screen, and they vary per run: the reading, the
number of changes in the release-train window, the lease, the latency and the SHA.
The spend figures are synthetic and are not read aloud.

Two figures are spoken from the script because they describe the labelled corpus,
not this run: 90.0% named nobody on a real anomaly (beat 2), and 50.0% precision over
58 namings (beat 4), both on the held-out split of the synthetic corpus with the runtime
filter shipped on 2026-09-27. Beat 4 also says the precision holds only if a fault
shows within 75 minutes, the generator's delay ceiling, which the window equals. Both
are written by `python scripts/attribution_split.py` into
`attribution_holdout_summary.json`, and the README quotes the same two. Beat 8 reads
the 58 namings and the 1160 synthetic cases off the evidence sentence on screen,
which prints the same summary. Earlier takes
quoted the in-sample 81.1% and 52.2% over 113 namings, and then the pre-filter held-out
93.1% and 62.5% over 40; neither is current, and the takes that spoke them are
superseded. If a re-run moves them, change the beat in `scripts/build_video_plan.py`,
rerun it, and re-render that beat: `video/generate-narration.py` synthesizes only the
beats whose words changed, and the measured holds are copied back into the plan.
