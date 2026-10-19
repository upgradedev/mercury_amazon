# Friction log: building a Fire TV app and an AWS telemetry cockpit

**Track:** Fire TV
**Scope of this log:** only things that happened while building this repository.

Every entry below points at code in this repository, a command that was run, or an
error that was observed. Entries about experiences we did not have have been
removed rather than rewritten, so this log is shorter than it was.

**What we exercised.** The Android TV emulator workflow,
`.github/workflows/android-tv-emulator.yml`, has run green several times:
`docs/EVIDENCE.md` lists runs 36661614006, 36669903334, 36798893479, 36922314984,
37464864870, 38808232691 and 39210785053. Run 39210785053 produced the runtime receipt checked in as
`android_tv_runtime_receipt.json`, which readiness gate J4 reads.

**What we did not exercise, and therefore say nothing about:** we never used the
Alexa Voice Service, and we never used the Amazon Appstore submission pipeline. The
event FAQ permits Android TV Emulator or Fire TV/Vega simulator; our runtime
workflow uses the first and physical hardware is optional.

---

## How each entry is written

Each entry has the six fields the event rules ask for: the specific task attempted,
the steps taken, the expected and the actual result, a severity rating, the
workaround used, and an actionable suggestion. Where a field is not known, the entry
says so rather than filling it in.

Severity uses one scale for every entry:

| Severity | What it means here |
|---|---|
| Blocking | The task could not be completed with the tool as it is. A way forward needs a different service, or a design we did not build. |
| Major | The task was completed only with new code or a design change that the documentation did not prepare us for, or the failure is silent and would have reached users. |
| Minor | A small, local fix once the cause was known. It cost a debugging cycle, not a design change. |
| Cosmetic | Wording or documentation only. The result was not affected. |

The nine entries at a glance:

| # | Entry | Area | Severity |
|---|---|---|---|
| 1 | AGP 8 rejects a manifest that names its own package | Android build | Minor |
| 2 | Nothing warns that an app will be filtered off a Fire TV Stick | Fire TV manifest | Major |
| 3 | TV focus is not a keyboard problem | D-pad navigation in a WebView | Major |
| 4 | Two focus systems is the default failure mode | D-pad navigation in a WebView | Minor |
| 5 | A WebView answers "did you handle that key?" asynchronously | Android key handling | Major |
| 6 | boto3 credential resolution is expensive without credentials | AWS SDK for Python | Major |
| 7 | Cost Explorer bills per request | AWS Cost Explorer | Major |
| 8 | Daily granularity is the wrong shape for an incident surface | AWS Cost Explorer | Blocking |
| 9 | No documented, reliable way to film a TV emulator journey in CI | Android TV emulator | Major |

---

## 1. AGP 8 rejects a manifest that names its own package, and the error is late

**Task attempted.** Build the Leanback wallboard APK with Android Gradle Plugin 8.

**Steps taken.** The manifest carried `package="com.amazon.mercury.wallboard"`
(the id at the time; since 2026-09-27 the app is `io.github.upgradedev.mercury.wallboard`,
because a third-party app should not ship inside Amazon's own namespace) alongside
`namespace` in `app/build.gradle.kts`, and we built the APK. The exact build command
and the verbatim error were not kept.

**Expected vs. actual result.** Expected: a manifest shaped like the Fire TV
tutorials builds. Practically every Fire TV tutorial and sample manifest still shows
the `package` attribute, because it was correct for years. Actual: Android Gradle
Plugin 8 fails the build on that combination. The failure arrives at manifest merge
time, well after project setup, and the error does not say "your tutorial is older
than your toolchain."

**Severity.** Minor. The build fails loudly and the fix is one deleted attribute,
but a developer copying a Fire TV sample into a new AGP 8 project meets it late.

**Workaround used.** Removed the attribute and left a comment in
`app/src/main/AndroidManifest.xml` saying why it is absent, plus a test
(`test_the_manifest_has_no_package_attribute`) so it cannot come back.

**Suggestion.** Date-stamp the Fire TV manifest samples with the AGP version they
target, or add a note to the Fire TV getting-started page.

---

## 2. Nothing tells you your app will be filtered off a Fire TV Stick

**Task attempted.** Declare the wallboard's hardware features so that the APK is
offered on a Fire TV Stick.

**Steps taken.** Wrote the first manifest with only `leanback` and `touchscreen`
declared. How we noticed the gap is not recorded in this log.

**Expected vs. actual result.** Expected: a build error or a lint warning when a TV
app would be hidden from a Fire TV Stick. Actual: there is no build error and no
lint warning. A Fire TV Stick has no GPS, camera or telephony, and any implicitly
required hardware feature filters the app off devices that lack it. This is a
silent, install-time filter, so a developer discovers it when the app fails to
appear for users, not while developing.

**Severity.** Major. The failure is silent and would have reached users.

**Workaround used.** Declared `android.hardware.location.gps` and
`android.hardware.camera` explicitly as `required="false"` in the manifest.

**Suggestion.** A lint check in the Fire TV tooling that flags a Leanback app
which has not explicitly opted out of the hardware features a Fire TV Stick lacks
would catch this at build time.

---

## 3. The 10-foot focus problem is not a keyboard problem, and the web platform treats it as one

**Task attempted.** Move focus around a grid of tiles on the cockpit page with the
remote's D-pad.

**Steps taken.** Built the cockpit page as a grid of tiles, relied on `tabindex`
and the browser's own focus order, and pressed Down from a tile in the middle of a
row.

**Expected vs. actual result.** Expected: on a remote, Down means down, so focus
moves to the tile below. Actual: `tabindex` and the browser's own focus order walk
the DOM linearly, so focus moved to the tile to its right, because that is what
comes next in the document. A linear walk is not approximately correct on a grid;
it is wrong in a way that makes the interface feel broken. The CSS
`spatial-navigation` specification exists but is not available in the WebView we
target.

**Severity.** Major. Every TV web app has to reimplement this, and we had to write
and test a navigator of our own.

**Workaround used.** Wrote a geometric navigator in `docs/firetv_nav.js`: for a
pressed direction, keep only the candidates that lie in that direction, score them
by distance along the axis of travel plus a weighted penalty for perpendicular
drift, and take the minimum. It holds focus at an edge rather than wrapping,
because wrapping loses the viewer's place on a large screen. The geometry is tested
by executing the real file in Node against a synthetic grid:
`node tests/e2e/spatial_nav_spec.js`, 25 assertions when this entry was written. The
spec has grown since, and `docs/EVIDENCE.md` carries the current count.

**Suggestion.** Ship a small, supported spatial navigation JavaScript library for
Fire TV web apps and WebView hosts, or enable the CSS specification in the Fire OS
WebView. Every TV developer is writing this same 120 lines.

---

## 4. Two focus systems is the default failure mode, not an unusual mistake

**Task attempted.** Add the shared navigation script to the cockpit page.

**Steps taken.** The page already had a keydown handler with its own index. We
included the navigation script, which had another one with a second index, and
pressed the arrow keys.

**Expected vs. actual result.** Expected: one arrow press moves focus one
position. Actual: both handlers ran on every arrow press, and the two disagreed
about where focus was. The symptom, focus jumping two positions or appearing to be
in two places, looks like a rendering bug rather than a duplicated listener. This
is easy to do accidentally the moment a project has both a page and a shared
navigation include.

**Severity.** Minor. Once the cause was known, the fix was deleting one handler.

**Workaround used.** Deleted the page's handler, made the script the only owner of
focus, and added a test that fails if a second `keydown` listener ever appears in
the page (`test_there_is_exactly_one_keydown_handler_in_the_cockpit`).

**Suggestion.** State in the Fire TV web app and WebView guidance that one script
should own D-pad focus on a page, and show how a page asks that owner for custom
key behaviour instead of adding a second `keydown` listener. A supported navigation
library, as suggested in entry 3, could expose that hook.

---

## 5. A WebView can only answer "did you handle that key?" asynchronously, and Back is the key where it matters

**Task attempted.** Make Back on the remote close an open dialog in the page, and
leave the app only when the page has nothing to close.

**Steps taken.** Forwarded remote keys from `Activity.onKeyDown` to the page with
`WebView.evaluateJavascript`. For Back, `onKeyDown` needed the page's answer before
it could return.

**Expected vs. actual result.** Expected: a way to ask the page whether it handled
Back and return that answer from `onKeyDown`. Actual: `WebView.evaluateJavascript`
returns its result on a callback, and `Activity.onKeyDown` must return a boolean
synchronously. If the page closed a dialog, the activity must not also close; if it
did not, the activity should. The synchronous key API and the asynchronous WebView
bridge cannot be reconciled directly, so every WebView-hosted TV app has to invent a
convention. Getting it wrong either traps the viewer inside the app or closes the
app while they are using it.

**Severity.** Major. There is no supported pattern, so the convention had to be
designed, and either wrong answer is visible to the viewer.

**Workaround used.** `onKeyDown` returns `true` for Back immediately and resolves
the outcome in the callback, choosing between the page's own handler, WebView
history, and `finish()`. See `handleBack` in `MainActivity.kt`.

**Suggestion.** A documented pattern for this in the Fire TV WebView guidance, or
a helper that wraps the round trip, would save every team the same reasoning.

---

## 6. boto3 credential resolution is expensive on a machine that has no credentials

**Task attempted.** Serve the AWS cost endpoint quickly on a machine that may or
may not have AWS credentials.

**Steps taken.** The cost adapter called `boto3.session.Session().get_credentials()`
on every request as a capability check. We then ran our own benchmark,
`python scripts/benchmark_suite.py`.

**Expected vs. actual result.** Expected: a cheap capability check, close to the
roughly 3 ms of the endpoints that did not touch AWS. Actual: the benchmark reported
a mean of 1154 ms for the AWS cost endpoint. On a machine with no credentials, the
resolution walk includes an instance metadata probe that has to time out. It is
cheap on an EC2 instance, so it can survive review and staging and only show up as
latency in an environment that does not have credentials, which is exactly a
developer laptop or a Fire TV on a home network.

**Severity.** Major. The cost is invisible in code review, because it looks like a
cheap capability check, and the fix was new caching code.

**Workaround used.** Cached the resolution outcome per adapter, including the
negative outcome, with an explicit `reset_credential_cache()`. Mean fell from
1154 ms to under 4 ms in fixture mode.

**Suggestion.** Document the cost of `get_credentials()` on the unauthenticated
path, or provide a cheap, non-probing way to ask whether credentials exist.

---

## 7. Cost Explorer bills per request, which makes the obvious wallboard design wrong

**Task attempted.** Show AWS spend on a wallboard that refreshes.

**Steps taken.** Wired Cost Explorer into the cost adapter,
`src/infrastructure/aws_cost_adapter.py`, as the spend source for a refreshing
wallboard. This log does not record how many requests an uncached version made.

**Expected vs. actual result.** Expected: a refreshing display can read its data
source on each refresh, and the API signals when that is a bad idea. Actual: Cost
Explorer charges per API request and its underlying data only refreshes daily, so
a refreshing wallboard spends money to receive the same answer. The pricing model
and the natural design of the surface point in opposite directions, and nothing in
the API surface signals it. The first version of any spend dashboard is likely to
poll.

**Severity.** Major. The obvious design costs money without any error, and avoiding
it took a caching design change.

**Workaround used.** Cached successful responses for 15 minutes
(`CACHE_TTL_SECONDS` in `src/infrastructure/aws_cost_adapter.py`) and stated the
reason in the provenance text that the cockpit prints. Failures are deliberately
not cached, so a transient error cannot pin the display to the fixture.

**Suggestion.** Return with each Cost Explorer response the time its underlying
data will next change, so a refreshing client can cache until then instead of
guessing a lifetime such as our 15 minutes. Failing that, state next to the
per-request price how often the data behind each granularity refreshes.

---

## 8. Daily granularity is the wrong shape for an incident surface, and we could not work around it

**Task attempted.** Show spend anomalies on an incident wallboard, where the useful
question is what changed in the last hour.

**Steps taken.** Used Cost Explorer, already wired into the cost adapter for entry
7, as the source of the spend signal.

**Expected vs. actual result.** Expected: a spend reading recent enough to show a
change within the last hour of an incident. Actual: Cost Explorer aggregates daily
with up to 24 hours of reporting delay, so it cannot answer the question by
construction. The workaround is CloudWatch metric streams, which is a different
service with a different setup cost.

**Severity.** Blocking. The task could not be done with Cost Explorer, and we did
not build the alternative.

**Workaround used.** None for the task itself, other than saying so. The cost
adapter's provenance text states the lag in the same sentence as the capability,
and so does the known-limitations list in `docs/EVIDENCE.md` (the README carried it
when this entry was written), so the number on screen is not mistaken for a
real-time reading. We did not build the CloudWatch metric stream path.

**Suggestion.** Document, next to the Cost Explorer granularity options, how old
the newest data point can be, and point to the service to use for sub-hour spend
signals with a short worked example. That would send an incident tool to the right
service before it is built on the wrong one.

---

## 9. There is no documented, reliable way to film a TV emulator journey in CI

**Task attempted.** Film the wallboard's D-pad journey on an Android TV emulator
in a hosted CI run.

**Steps taken.** On 2026-10-05, run 37349947785 of the footage workflow
(`android-tv-footage.yml`, added in draft pull request #40 and not yet merged)
booted the AOSP Android TV API 34 x86 emulator with `-gpu swiftshader_indirect`. It
recorded the journey with `adb shell screenrecord`, and as a fallback ran a loop of
`adb exec-out screencap -p` with a 1 s sleep between captures.

**Expected vs. actual result.** Expected: a documented, reliable way to record a
video of an emulator journey in CI. Actual: `adb shell screenrecord` produced a
32.0 s, 1920x1080, H.264 `journey.mp4` in this run, but its behaviour under the
software GPU is not documented, so one good run does not tell us the next will
work. The screencap fallback produced only 18 PNGs across roughly 40 s of journey,
so each capture took about 2 s, which is too slow for video.

**Severity.** Major. The footage depends on behaviour that is not documented, and
the fallback is too slow for video.

**Workaround used.** The workflow keeps both: `screenrecord` for the video, and the
screencap loop so that a run still yields stills if `screenrecord` fails. One good
run is not evidence that `screenrecord` works every time.

**Suggestion.** Document whether `adb shell screenrecord` is supported on the
emulator images, including under the software GPU (`-gpu swiftshader_indirect`),
or ship a recording option in the Vega and Fire TV tooling.

---

## What went well

* Leanback is plain Android. `WebView` plus `onKeyDown` was enough to host a real
  interface, with no TV-specific framework to learn first.
* `LEANBACK_LAUNCHER` as the single declaration that makes an app a TV app is a
  good design: one line, one obvious effect.
* `adb connect <ip>:5555` over the network, without a cable, makes the device
  loop fast for a device that lives behind a television.
* GitHub's hosted Android SDK action made the build reproducible for us despite
  having no local Android toolchain, which is the only reason there is an APK to
  download at all.
