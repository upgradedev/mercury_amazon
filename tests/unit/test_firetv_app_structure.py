"""Unit tests for Fire TV / Fire OS Leanback Application Project Structure."""
from pathlib import Path
import xml.etree.ElementTree as ET


def test_firetv_android_manifest_compliance():
    repo_root = Path(__file__).resolve().parent.parent.parent
    manifest_path = repo_root / "app" / "src" / "main" / "AndroidManifest.xml"
    assert manifest_path.exists(), "AndroidManifest.xml must exist in app/src/main"

    content = manifest_path.read_text(encoding="utf-8")
    assert "android.software.leanback" in content, "Must declare Leanback software feature"
    assert "android.hardware.touchscreen" in content, "Must declare touchscreen false for TV"
    assert "android.intent.category.LEANBACK_LAUNCHER" in content, "Must declare LEANBACK_LAUNCHER"


def test_firetv_gradle_build_configuration():
    repo_root = Path(__file__).resolve().parent.parent.parent
    settings_gradle = repo_root / "settings.gradle.kts"
    root_gradle = repo_root / "build.gradle.kts"
    app_gradle = repo_root / "app" / "build.gradle.kts"

    assert settings_gradle.exists(), "settings.gradle.kts must exist"
    assert root_gradle.exists(), "Root build.gradle.kts must exist"
    assert app_gradle.exists(), "app/build.gradle.kts must exist"

    app_gradle_text = app_gradle.read_text(encoding="utf-8")
    assert "com.amazon.mercury.wallboard" in app_gradle_text
    assert "androidx.leanback:leanback" in app_gradle_text


def test_firetv_main_activity_and_dpad_handler():
    repo_root = Path(__file__).resolve().parent.parent.parent
    activity_path = repo_root / "app" / "src" / "main" / "kotlin" / "com" / "amazon" / "mercury" / "wallboard" / "MainActivity.kt"
    assert activity_path.exists(), "MainActivity.kt must exist"

    text = activity_path.read_text(encoding="utf-8")
    assert "class MainActivity" in text
    assert "KEYCODE_DPAD_UP" in text
    assert "KEYCODE_DPAD_DOWN" in text
    assert "KEYCODE_DPAD_CENTER" in text
