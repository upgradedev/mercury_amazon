"""Structural tests for the Fire OS Leanback application project.

These cannot compile Kotlin, so they assert the things that decide whether the app
is a Fire TV app at all: the manifest declarations Amazon checks for, the Gradle
wiring, and the key handling contract between MainActivity and the cockpit page.

The build itself is proved by .github/workflows/android.yml, which assembles the
APK on a runner that has the Android SDK and uploads it.
"""
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
APP = REPO_ROOT / "app"
MANIFEST = APP / "src" / "main" / "AndroidManifest.xml"
KOTLIN = APP / "src" / "main" / "kotlin" / "com" / "amazon" / "mercury" / "wallboard"
KOTLIN_TESTS = APP / "src" / "test" / "kotlin" / "com" / "amazon" / "mercury" / "wallboard"
ANDROID_NS = "http://schemas.android.com/apk/res/android"


def android_attr(element, name):
    return element.get(f"{{{ANDROID_NS}}}{name}")


@pytest.fixture(scope="module")
def manifest_root():
    return ET.parse(MANIFEST).getroot()


@pytest.fixture(scope="module")
def manifest_text():
    return MANIFEST.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def activity_source():
    return (KOTLIN / "MainActivity.kt").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def app_gradle():
    return (APP / "build.gradle.kts").read_text(encoding="utf-8")


# ------------------------------------------------------------------- Manifest

def test_leanback_software_feature_is_declared_required(manifest_root):
    features = {android_attr(f, "name"): android_attr(f, "required")
                for f in manifest_root.findall("uses-feature")}
    assert features.get("android.software.leanback") == "true"


def test_touchscreen_is_declared_not_required(manifest_root):
    """Without this, the app will not install on a device that has only a remote."""
    features = {android_attr(f, "name"): android_attr(f, "required")
                for f in manifest_root.findall("uses-feature")}
    assert features.get("android.hardware.touchscreen") == "false"


def test_the_launcher_activity_is_a_leanback_launcher(manifest_root):
    activities = manifest_root.findall("application/activity")
    assert activities, "the manifest declares no activity"
    categories = [
        android_attr(category, "name")
        for activity in activities
        for intent_filter in activity.findall("intent-filter")
        for category in intent_filter.findall("category")
    ]
    assert "android.intent.category.LEANBACK_LAUNCHER" in categories


def test_the_launcher_activity_is_exported_and_landscape(manifest_root):
    activity = manifest_root.find("application/activity")
    assert android_attr(activity, "exported") == "true"
    assert android_attr(activity, "screenOrientation") == "landscape"


def test_internet_permission_is_declared(manifest_root):
    permissions = [android_attr(p, "name") for p in manifest_root.findall("uses-permission")]
    assert "android.permission.INTERNET" in permissions


def test_the_manifest_has_no_package_attribute(manifest_root):
    """Android Gradle Plugin 8 fails the build when both this and namespace exist."""
    assert manifest_root.get("package") is None


def test_the_manifest_is_well_formed_xml():
    ET.parse(MANIFEST)  # raises on malformed XML


# --------------------------------------------------------------------- Gradle

def test_gradle_project_files_exist():
    for path in [
        REPO_ROOT / "settings.gradle.kts",
        REPO_ROOT / "build.gradle.kts",
        APP / "build.gradle.kts",
        REPO_ROOT / "gradlew",
        REPO_ROOT / "gradlew.bat",
        REPO_ROOT / "gradle" / "wrapper" / "gradle-wrapper.properties",
        REPO_ROOT / "gradle" / "wrapper" / "gradle-wrapper.jar",
    ]:
        assert path.exists(), f"missing {path.relative_to(REPO_ROOT)}"


def test_namespace_matches_the_kotlin_package(app_gradle, activity_source):
    assert 'namespace = "com.amazon.mercury.wallboard"' in app_gradle
    assert "package com.amazon.mercury.wallboard" in activity_source


def test_min_sdk_covers_fire_os_7(app_gradle):
    """Fire OS 7 is Android 9, API 28. A higher minSdk drops those devices."""
    match = re.search(r"minSdk\s*=\s*(\d+)", app_gradle)
    assert match and int(match.group(1)) <= 28


def test_leanback_dependency_is_declared(app_gradle):
    assert "androidx.leanback:leanback" in app_gradle


def test_jvm_unit_tests_are_wired_into_the_build(app_gradle):
    assert "junit:junit" in app_gradle
    assert 'java.srcDirs("src/test/kotlin")' in app_gradle


def test_build_config_carries_the_cockpit_url(app_gradle):
    assert "buildConfig = true" in app_gradle
    assert "MERCURY_COCKPIT_URL" in app_gradle
    assert "mercuryCockpitUrl" in app_gradle, "the URL must be overridable per build"


# ------------------------------------------------------------------- Activity

def test_the_activity_hosts_a_webview_with_javascript_enabled(activity_source):
    assert "WebView(this)" in activity_source
    assert "settings.javaScriptEnabled = true" in activity_source
    assert "settings.domStorageEnabled = true" in activity_source


def test_the_activity_exposes_a_javascript_interface(activity_source):
    assert "@JavascriptInterface" in activity_source
    assert 'addJavascriptInterface(MercuryHost(), "MercuryHost")' in activity_source
    assert 'removeJavascriptInterface("MercuryHost")' in activity_source, "must be torn down"


def test_the_activity_handles_every_dpad_key(activity_source):
    bridge = (KOTLIN / "DpadBridge.kt").read_text(encoding="utf-8")
    for key in [
        "KEYCODE_DPAD_UP", "KEYCODE_DPAD_DOWN", "KEYCODE_DPAD_LEFT",
        "KEYCODE_DPAD_RIGHT", "KEYCODE_DPAD_CENTER", "KEYCODE_BACK",
    ]:
        assert key in bridge, f"{key} is not mapped"
    assert "override fun onKeyDown" in activity_source


def test_back_asks_the_page_before_closing_the_activity(activity_source):
    """Swallowing BACK traps the viewer; forwarding it blindly closes the war room."""
    assert "pageConsumedKey" in activity_source
    assert "canGoBack()" in activity_source
    assert "finish()" in activity_source


def test_the_activity_renders_an_error_screen_rather_than_a_blank_one(activity_source):
    assert "onReceivedError" in activity_source
    assert "offlineHtml" in activity_source
    assert "unreachable" in activity_source.lower()
    assert "isForMainFrame" in activity_source, "a failed sub-resource must not blank the page"


def test_the_activity_does_not_hardcode_a_single_cockpit_url(activity_source):
    assert "CockpitUrlResolver.resolve" in activity_source
    urls = re.findall(r'"https?://[^"]+"', activity_source)
    assert not urls, f"MainActivity hardcodes URLs: {urls}"


def test_the_bridge_direction_names_match_the_cockpit_script():
    bridge = (KOTLIN / "DpadBridge.kt").read_text(encoding="utf-8")
    nav = (REPO_ROOT / "docs" / "firetv_nav.js").read_text(encoding="utf-8")
    assert "window.navigateDpad" in bridge
    for direction in ["UP", "DOWN", "LEFT", "RIGHT", "SELECT", "BACK"]:
        assert f'"{direction}"' in bridge, f"{direction} missing from the Kotlin bridge"
        assert f"'{direction}'" in nav or f'"{direction}"' in nav, f"{direction} missing from the page"


def test_the_bridge_refuses_an_unknown_direction_rather_than_injecting_it():
    bridge = (KOTLIN / "DpadBridge.kt").read_text(encoding="utf-8")
    assert "require(direction in setOf(" in bridge


def test_kotlin_unit_tests_exist_for_both_pure_units():
    assert (KOTLIN_TESTS / "DpadBridgeTest.kt").exists()
    assert (KOTLIN_TESTS / "CockpitUrlResolverTest.kt").exists()


def test_the_url_resolver_refuses_non_http_schemes():
    source = (KOTLIN / "CockpitUrlResolver.kt").read_text(encoding="utf-8")
    assert "ALLOWED_SCHEMES" in source
    assert '"http://"' in source and '"https://"' in source


# ------------------------------------------------------------ CI is the evidence

def test_an_android_ci_workflow_builds_and_uploads_the_apk():
    workflow = (REPO_ROOT / ".github" / "workflows" / "android.yml").read_text(encoding="utf-8")
    assert "android-actions/setup-android" in workflow
    assert "assembleDebug" in workflow
    assert "testDebugUnitTest" in workflow
    assert "actions/upload-artifact" in workflow
    assert "if-no-files-found: error" in workflow, "a run with no APK must fail, not pass quietly"


def test_the_build_document_states_what_has_not_been_run():
    doc = (REPO_ROOT / "docs" / "FIRE_TV_BUILD.md").read_text(encoding="utf-8")
    assert "Not run" in doc
    assert "JAVA_HOME is not set" in doc, "the real local build error must be recorded verbatim"
    assert "No Fire TV hardware was available" in doc
