# Building and running Mercury on Fire TV

This page covers building the Leanback APK, installing it on a Fire TV device,
recording the receipt that readiness gate J4 reads, and why there is no emulator
step in any of it.

## What has and has not been run

Stated plainly, because the difference matters when you are judging this.

| Step | Status |
|---|---|
| Kotlin sources, manifest and Gradle project | Written and committed in `app/` |
| `./gradlew :app:testDebugUnitTest` (D-pad bridge, URL resolver) | **Configured, never executed.** `.github/workflows/android.yml` is committed but has not run |
| `./gradlew :app:assembleDebug` | **Configured, never executed.** No APK has been produced by anyone |
| Build on the maintainer's machine | **Not run.** See "Why the build is configured for CI" below |
| Install on a physical Fire TV Stick | **Not run.** No Fire TV hardware was available |
| Run on a virtual Fire TV | **Not possible.** No Fire TV emulator exists; see "Why there is no emulator step" below |
| `python scripts/write_firetv_receipt.py` | **Written and tested against a throwaway checkout.** Never run against a real APK, because there is none |
| D-pad navigation logic | Tested for real: 17 assertions in `tests/e2e/spatial_nav_spec.js` execute `docs/firetv_nav.js` in Node against a synthetic grid |

The cockpit page the APK loads is the same page served by `docs/` and by the Python
server, so what the WebView renders on a TV is the page you can open in a browser
right now. What has not been observed is that page inside a Fire OS WebView on a
real device.

## What the TV surface is

A D-pad and a screen. The remote's up, down, left, right, centre and back keys reach
the page through `DpadBridge`, and the page paints the verdict, the provenance
stamps and the rollback controls at a size measured for a room. That is the whole of
the surface. There is no voice input: nothing on the device listens for speech, there
is no Alexa skill and no Alexa integration in this repository, and the only sound
the cockpit makes is the browser's own `speechSynthesis` reading a summary aloud,
which is output, not a command channel. A judge watching device footage should
expect a remote moving a focus ring and a television showing an answer, and nothing
else.

## Why the build is configured for CI, and what that is worth right now

Building an Android APK needs a JDK and the Android SDK. Neither was present in the
environment this repository was developed in. Running `./gradlew assembleDebug`
there produces exactly this:

```
$ ./gradlew assembleDebug --no-daemon
ERROR: JAVA_HOME is not set and no 'java' command could be found in your PATH.

Please set the JAVA_HOME environment variable in your profile to point to your
Java installation.
```

So the build is configured to run on a GitHub Actions runner that has both.
`.github/workflows/android.yml` runs the Kotlin unit tests, assembles the debug
APK, prints its sha256, and uploads it as an artifact, failing the job if no APK is
produced. It runs on every push to the default branch, with no paths filter, and on
demand from the Actions tab, so the first push after it was written produces a run
whatever else that push touches.

**That workflow has not run.** Nothing has been pushed since it was written, so
there are zero runs, zero artifacts, and no APK exists anywhere. The repository is
also private, so the Actions tab is not visible to anyone outside the
organisation. Once the repository is public and a commit is pushed, a reader can
open the Actions tab, pick a `Fire TV APK` run and download
`mercury-firetv-debug-apk`. Until then this is a configured intention, not
evidence.

The workflow itself is also unverified: whether
`android-actions/setup-android@v3` resolves platform 34 and accepts its licences
on the runner has not been observed. The first run may need adjustment.

## Why there is no emulator step

An earlier version of this page had a section headed "Run in the Fire TV emulator"
that said Amazon publishes a Fire TV system image for the Android emulator. That was
wrong, and it is retired here rather than deleted so the correction is visible.

Three facts, each read from Amazon's own developer documentation on 2026-09-08 and
cited by URL so a reader can check them rather than take this page's word:

1. **Amazon says to test on an actual Fire TV device.** The Fire TV documentation on
   how Fire TV development differs from Android TV development says that when
   testing Fire TV app code you use an actual Fire TV device, the set-top box or the
   stick, instead of a virtual emulator.
   `https://developer.amazon.com/docs/fire-tv/differences-from-android-tv-development.html`
2. **No Fire TV emulator exists.** Amazon publishes no Fire TV emulator and no Fire
   OS system image. The generic Android TV image that ships with the Android SDK is
   not Fire OS, has no Fire TV launcher, remote mapping or Appstore, and is the thing
   Amazon says is not supported. So there is nothing to install: the device is the
   only place this APK runs.
3. **The Vega Virtual Device is not a way around that.** Amazon's newer Fire TV
   platform, Vega OS, ships a virtual device with its SDK, but the Vega SDK install
   page lists macOS 10.15+ and Ubuntu 20.04+ as the supported operating systems and
   does not list Windows or WSL, and the run-apps page describes the Vega Virtual
   Device as a way to run and test Vega apps, which this Android APK is not.
   `https://developer.amazon.com/docs/vega/0.23/install-vega-sdk.html` and
   `https://developer.amazon.com/docs/vega/0.22/run-apps.html`

The consequence for this entry is that **device footage is mandatory**. A recording
made in a desktop browser shows the cockpit and the governance path but not the
platform, and no virtual device can be substituted for the platform on the machine
this repository is developed on. `video/SHOT_LIST.md` says the same thing in its
own words.

## Prerequisites for a local build

* JDK 17 (Temurin or equivalent)
* Android SDK with platform 34 and build-tools, either via Android Studio or
  `cmdline-tools` plus `sdkmanager "platforms;android-34" "build-tools;34.0.0"`
* `ANDROID_HOME` (or `ANDROID_SDK_ROOT`) pointing at the SDK, or a
  `local.properties` in the repository root containing `sdk.dir=/path/to/sdk`

## Build

```bash
# Unix
./gradlew :app:assembleDebug

# Windows
gradlew.bat :app:assembleDebug
```

The APK lands at `app/build/outputs/apk/debug/app-debug.apk`.

To bake in the cockpit address at build time:

```bash
./gradlew :app:assembleDebug -PmercuryCockpitUrl=http://192.168.1.20:8002/
```

Run the JVM unit tests, which need no device:

```bash
./gradlew :app:testDebugUnitTest
```

## Install on a Fire TV Stick

1. On the device: **Settings → My Fire TV → Developer Options**, then turn on
   **ADB debugging** and **Apps from Unknown Sources**.
2. Find the device IP under **Settings → My Fire TV → About → Network**.
3. Connect and install:

```bash
adb connect 192.168.1.42:5555
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

4. Launch it pointing at the machine running the Mercury server:

```bash
adb shell am start -n com.amazon.mercury.wallboard/.MainActivity \
  --es COCKPIT_URL http://192.168.1.20:8002/
```

The `COCKPIT_URL` extra is validated before it is loaded: only absolute `http` and
`https` URLs are accepted, and anything else falls back to the compiled default
(`CockpitUrlResolver`, with tests in `app/src/test/kotlin/`).

The app also appears on the Fire TV home row, because the activity declares
`android.intent.category.LEANBACK_LAUNCHER`. Launching it from there uses the URL
compiled into the build.

## The receipt readiness gate J4 wants

`ci/readiness.py` used to pass J4, the gate that decides whether the sponsor product
is load-bearing, on a string match: the words "Fire TV" somewhere in the README and
`LEANBACK_LAUNCHER` somewhere in the manifest. Both are text. Mercury is entered in
the Fire TV track, so that was the one gate in the file that could not fail on the
axis it exists to test, and it was contributing a PASS to a published score while
this page said no APK had ever been built.

J4 now asks for evidence of a binary and of somebody watching it run, recorded in
`firetv_build_receipt.json` at the repository root. **That file does not exist, so
J4 fails,** and the published readiness score went down by one when the gate was
rewritten. It is exempt from the CI exit code, with the reason printed in the
auditor's own output, because a JDK, an Android SDK and a Fire TV device cannot be
conjured by running code in a checkout.

### Writing the receipt

Do not write it by hand. `python scripts/write_firetv_receipt.py` writes it from a
real build and a real launch, and refuses to write anything otherwise:

```bash
python scripts/write_firetv_receipt.py \
  --gradle-exit-code 0 \
  --apk app/build/outputs/apk/debug/app-debug.apk \
  --built-by-command "./gradlew :app:assembleDebug" \
  --device-model "Fire TV Stick 4K Max (2nd gen)" \
  --os-version "Fire OS 8.1.0.3" \
  --adb-install-exit-code 0 \
  --observed "The wallboard rendered and the D-pad moved the focus ring across the tiles." \
  --adb-launch-output launch.log        # optional: the verbatim output of adb shell am start
```

What it refuses, each with a test in `tests/unit/test_write_firetv_receipt.py`: an
APK path that is not a file, is outside the checkout, is empty, does not start with
a zip header, or is a zip archive with no `AndroidManifest.xml` inside; a gradle
exit code other than 0; an adb install exit code other
than 0; an empty device model, OS version or observation; a launch time that is not
ISO-8601. It exits 2 and writes nothing in every one of those cases. The sha256 is
computed from the APK by the script and cannot be supplied on the command line, the
`apk_path` is stored relative to the checkout, and the finished receipt is run
through the gate's own predicate before it touches disk. `--dry-run` prints what
would be written and writes nothing.

The APK itself is gitignored, so a clone receives the receipt and its digest but not
the binary. The CI artifact from `.github/workflows/android.yml` is where a reader
downloads the file the digest identifies, and the workflow prints the same digest in
its log.

This is the shape it writes. Every field is required and each is checked:
`gradle_exit_code` must be 0, `apk_path` must name a file that exists in the
checkout, `adb_install_exit_code` must be 0. `tests/unit/test_readiness_gates.py`
drives each missing field and each failure code against the predicate, including
the case where it passes.

```json
{
  "schema": "mercury.firetv_build_receipt/1",
  "recorded_by_command": "python scripts/write_firetv_receipt.py",
  "recorded_at_utc": "2026-09-08T10:05:00Z",
  "built_by_command": "./gradlew :app:assembleDebug",
  "gradle_exit_code": 0,
  "apk_path": "app/build/outputs/apk/debug/app-debug.apk",
  "apk_sha256": "the sha256 the script computed from that file",
  "device_run": {
    "device_model": "Fire TV Stick 4K Max (2nd gen)",
    "fire_os_or_android_version": "Fire OS 8.1.0.3",
    "adb_install_exit_code": 0,
    "launched_at_utc": "2026-09-08T10:00:00Z",
    "observed": "what was on the screen, in words"
  }
}
```

After the script writes it, `tests/unit/test_readiness_gates.py` asserts the file is
absent and will fail; whoever produces the receipt is expected to change that test
to assert its contents, commit both, and run `python ci/readiness.py` to watch J4
pass. Filing what happened in `.github/ISSUE_TEMPLATE/firetv_device_report.yml` is
the other half of the record.

## Driving it with the remote

| Remote key | Effect |
|---|---|
| D-pad up / down / left / right | Moves focus to the nearest control in that direction |
| Select / centre | Activates the focused control |
| Back | Offered to the page first, then to WebView history, then closes the app |

Key handling lives in `DpadBridge`, which maps key codes to direction names and
builds the guarded JavaScript call. `MainActivity` forwards them into the page
through `evaluateJavascript`, and the page's `window.navigateDpad` is the same
entry point a desktop keyboard's arrow keys reach. That is deliberate: there is one
focus implementation, so the remote and a keyboard cannot diverge.

## If the cockpit will not load

The app replaces the screen with an error page naming the exact URL that failed and
the `adb` command to relaunch against a different one. It does not show a blank
screen, and it does not show a cached success state.
