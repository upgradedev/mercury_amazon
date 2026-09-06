# Building and running Mercury on Fire TV

This page covers building the Leanback APK, installing it on a Fire TV device, and
running it in the official Fire TV emulator image.

## What has and has not been run

Stated plainly, because the difference matters when you are judging this.

| Step | Status |
|---|---|
| Kotlin sources, manifest and Gradle project | Written and committed in `app/` |
| `./gradlew :app:testDebugUnitTest` (D-pad bridge, URL resolver) | **Configured, never executed.** `.github/workflows/android.yml` is committed but has not run |
| `./gradlew :app:assembleDebug` | **Configured, never executed.** No APK has been produced by anyone |
| Build on the maintainer's machine | **Not run.** See "Why the build is configured for CI" below |
| Install on a physical Fire TV Stick | **Not run.** No Fire TV hardware was available |
| Run in the Fire TV emulator image | **Not run.** No Android SDK was available in the build environment |
| D-pad navigation logic | Tested for real: 17 assertions in `tests/e2e/spatial_nav_spec.js` execute `docs/firetv_nav.js` in Node against a synthetic grid |

The cockpit page the APK loads is the same page served by `docs/` and by the Python
server, so what the WebView renders on a TV is the page you can open in a browser
right now. What has not been observed is that page inside a Fire OS WebView on a
real device.

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
APK, and uploads it as an artifact, failing the job if no APK is produced.

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

## Run in the Fire TV emulator

Amazon publishes a Fire TV system image for the Android emulator. With the Android
SDK installed:

```bash
sdkmanager --install "system-images;android-30;android-tv;x86"
avdmanager create avd -n firetv -k "system-images;android-30;android-tv;x86" \
  -d "tv_1080p"
emulator -avd firetv
```

Then, in another terminal:

```bash
adb install -r app/build/outputs/apk/debug/app-debug.apk
adb shell am start -n com.amazon.mercury.wallboard/.MainActivity
```

The default cockpit URL is `http://10.0.2.2:8002/`, which is how an emulator reaches
a server running on the host machine, so a locally running Mercury server is picked
up with no extra flags.

Amazon's own Fire TV developer documentation is the authority on which emulator
image matches which Fire OS generation; the commands above target the generic
Android TV image, which is what the emulator ships by default.

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
