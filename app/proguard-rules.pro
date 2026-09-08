# ProGuard/R8 rules for the Mercury Fire TV wallboard.
#
# app/build.gradle.kts names this file in the release build type:
#
#     proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
#
# Gradle resolves that path when it configures the release variant, so the build
# fails without this file even though `isMinifyEnabled = false` means none of the
# rules below would be applied. It was missing until 2026-09-08, and it stayed
# missing because this module has never been compiled: no JDK and no Android SDK
# are installed on the machine that wrote it, which docs/FIRE_TV_BUILD.md records
# verbatim. tests/unit/test_firetv_app_structure.py now asserts that every file
# the build script names exists, so a name without a file fails the Python suite
# rather than waiting for the first person with an SDK.
#
# The file is deliberately empty of rules. Adding keep rules that nothing has run
# would be writing configuration for a build that has never happened.
#
# When minification is turned on, the WebView JavascriptInterface is the first
# thing that will need a keep rule: R8 strips methods reached only from JavaScript,
# because nothing in the Kotlin call graph reaches them. The rule is written below
# and commented out rather than active, because an active rule in a build that
# never runs is an untested claim, and this repository does not make those.
#
# -keepclassmembers class com.amazon.mercury.wallboard.DpadBridge {
#     @android.webkit.JavascriptInterface <methods>;
# }
