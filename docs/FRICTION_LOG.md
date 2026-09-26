# Friction log: building a Fire TV app and an AWS telemetry cockpit

**Track:** Fire TV
**Scope of this log:** only things that happened while building this repository.

Every entry below points at code in this repository, a command that was run, or an
error that was observed. Entries about experiences we did not have have been
removed rather than rewritten, so this log is shorter than it was.

**What we did not exercise, and therefore say nothing about:** the candidate Android
TV workflow has not yet run, we never used the Alexa Voice Service, and we never used
the Amazon Appstore submission pipeline. The event FAQ permits Android TV Emulator
or Fire TV/Vega simulator; our runtime workflow uses the first and physical hardware
is optional.

---

## 1. AGP 8 rejects a manifest that names its own package, and the error is late

**What happened.** The manifest carried `package="com.amazon.mercury.wallboard"`
alongside `namespace` in `app/build.gradle.kts`. Android Gradle Plugin 8 fails the
build on that combination.

**Why it is friction.** Practically every Fire TV tutorial and sample manifest
still shows the `package` attribute, because it was correct for years. A developer
copying a Fire TV sample into a new AGP 8 project gets a build failure at manifest
merge time, well after project setup, and the error does not say "your tutorial is
older than your toolchain."

**What we did.** Removed the attribute and left a comment in
`app/src/main/AndroidManifest.xml` saying why it is absent, plus a test
(`test_the_manifest_has_no_package_attribute`) so it cannot come back.

**Suggestion.** Date-stamp the Fire TV manifest samples with the AGP version they
target, or add a note to the Fire TV getting-started page.

---

## 2. Nothing tells you your app will be filtered off a Fire TV Stick

**What happened.** The first manifest declared only `leanback` and `touchscreen`.
A Fire TV Stick has no GPS, camera or telephony, and any implicitly required
hardware feature filters the app off devices that lack it.

**Why it is friction.** This is a silent, install-time filter. There is no build
error and no lint warning. A developer discovers it when the app fails to appear
for users, not while developing.

**What we did.** Declared `android.hardware.location.gps` and
`android.hardware.camera` explicitly as `required="false"` in the manifest.

**Suggestion.** A lint check in the Fire TV tooling that flags a Leanback app
which has not explicitly opted out of the hardware features a Fire TV Stick lacks
would catch this at build time.

---

## 3. The 10-foot focus problem is not a keyboard problem, and the web platform treats it as one

**What happened.** We had a cockpit page with a grid of tiles. `tabindex` and the
browser's own focus order walk the DOM linearly, so pressing Down from a tile in
the middle of a row moved focus to the tile to its right, because that is what
comes next in the document.

**Why it is friction.** On a remote, Down means down. A linear walk is not
approximately correct on a grid; it is wrong in a way that makes the interface
feel broken. Every TV web app has to reimplement this. The CSS `spatial-navigation`
specification exists but is not available in the WebView we target.

**What we did.** Wrote a geometric navigator in `docs/firetv_nav.js`: for a pressed
direction, keep only the candidates that lie in that direction, score them by
distance along the axis of travel plus a weighted penalty for perpendicular drift,
and take the minimum. It holds focus at an edge rather than wrapping, because
wrapping loses the viewer's place on a large screen. The geometry is tested by
executing the real file in Node against a synthetic grid:
`node tests/e2e/spatial_nav_spec.js`, 22 assertions.

**Suggestion.** Ship a small, supported spatial navigation JavaScript library for
Fire TV web apps and WebView hosts, or enable the CSS specification in the Fire OS
WebView. Every TV developer is writing this same 120 lines.

---

## 4. Two focus systems is the default failure mode, not an unusual mistake

**What happened.** The page had a keydown handler with its own index, and the
included navigation script had another one with a second index. Both ran on every
arrow press, and the two disagreed about where focus was.

**Why it is friction.** This is easy to do accidentally the moment a project has
both a page and a shared navigation include, and it produces a symptom (focus
jumping two positions, or appearing to be in two places) that looks like a
rendering bug rather than a duplicated listener.

**What we did.** Deleted the page's handler, made the script the only owner of
focus, and added a test that fails if a second `keydown` listener ever appears in
the page (`test_there_is_exactly_one_keydown_handler_in_the_cockpit`).

---

## 5. A WebView can only answer "did you handle that key?" asynchronously, and Back is the key where it matters

**What happened.** `WebView.evaluateJavascript` returns its result on a callback.
`Activity.onKeyDown` must return a boolean synchronously. For Back, the correct
behaviour depends on the answer: if the page closed a dialog, the activity must
not also close; if it did not, the activity should.

**Why it is friction.** The synchronous key API and the asynchronous WebView
bridge cannot be reconciled directly, so every WebView-hosted TV app has to invent
a convention. Getting it wrong either traps the viewer inside the app or closes
the app while they are using it.

**What we did.** `onKeyDown` returns `true` for Back immediately and resolves the
outcome in the callback, choosing between the page's own handler, WebView history,
and `finish()`. See `handleBack` in `MainActivity.kt`.

**Suggestion.** A documented pattern for this in the Fire TV WebView guidance, or
a helper that wraps the round trip, would save every team the same reasoning.

---

## 6. boto3 credential resolution is expensive on a machine that has no credentials

**What happened.** Our own benchmark, `python scripts/benchmark_suite.py`, reported
a mean of 1154 ms for the AWS cost endpoint against roughly 3 ms for the endpoints
that did not touch AWS. The cause was calling `boto3.session.Session().get_credentials()`
on every request. On a machine with no credentials, that walk includes an instance
metadata probe that has to time out.

**Why it is friction.** The cost is invisible in code review. It looks like a
cheap capability check, and it is cheap on an EC2 instance, so it can survive
review and staging and only show up as latency in an environment that does not
have credentials, which is exactly a developer laptop or a Fire TV on a home
network.

**What we did.** Cached the resolution outcome per adapter, including the negative
outcome, with an explicit `reset_credential_cache()`. Mean fell from 1154 ms to
under 4 ms in fixture mode.

**Suggestion.** Document the cost of `get_credentials()` on the unauthenticated
path, or provide a cheap, non-probing way to ask whether credentials exist.

---

## 7. Cost Explorer bills per request, which makes the obvious wallboard design wrong

**What happened.** A wallboard refreshes. Cost Explorer charges per API request
and its underlying data only refreshes daily, so a refreshing wallboard spends
money to receive the same answer.

**Why it is friction.** The pricing model and the natural design of the surface
point in opposite directions, and nothing in the API surface signals it. The first
version of any spend dashboard is likely to poll.

**What we did.** Cached successful responses for 15 minutes
(`CACHE_TTL_SECONDS` in `src/infrastructure/aws_cost_adapter.py`) and stated the
reason in the provenance text that the cockpit prints. Failures are deliberately
not cached, so a transient error cannot pin the display to the fixture.

---

## 8. Daily granularity is the wrong shape for an incident surface, and we could not work around it

**What happened.** We wanted spend anomalies on an incident wallboard. Cost
Explorer aggregates daily with up to 24 hours of reporting delay.

**Why it is friction.** During an incident, the useful question is what changed in
the last hour. Cost Explorer cannot answer it by construction. The workaround is
CloudWatch metric streams, which is a different service with a different setup
cost.

**What we did.** Nothing, other than saying so. The cost adapter's provenance text
and the README both state the lag in the same sentence as the capability, so the
number on screen is not mistaken for a real-time reading. We did not build the
CloudWatch metric stream path.

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
