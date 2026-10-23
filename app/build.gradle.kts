plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "io.github.upgradedev.mercury.wallboard"
    compileSdk = 34

    defaultConfig {
        applicationId = "io.github.upgradedev.mercury.wallboard"
        // Fire OS 7 is based on Android 9 (API 28). Fire OS 8 is Android 11 (API 30).
        minSdk = 28
        targetSdk = 34
        versionCode = 2
        versionName = "1.0.1"

        // The cockpit this build points at. The normal artifact opens the exact
        // public candidate without an adb intent override. Override per build with
        //   ./gradlew assembleDebug -PmercuryCockpitUrl=http://192.168.1.20:8002/
        // or per launch with the COCKPIT_URL intent extra.
        buildConfigField(
            "String",
            "MERCURY_COCKPIT_URL",
            "\"${project.findProperty("mercuryCockpitUrl") ?: "https://leol25sezuvokpankox5cvjopm0gtvfa.lambda-url.eu-west-1.on.aws/"}\"",
        )
    }

    buildFeatures {
        buildConfig = true
    }

    buildTypes {
        debug {
            // Cleartext is permitted for this build type and no other. The
            // permission lives in app/src/debug/AndroidManifest.xml, which the
            // manifest merger applies to debug variants only; the main manifest
            // declares usesCleartextTraffic="false" and is the only manifest a
            // release build merges.
            isMinifyEnabled = false
        }
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    sourceSets {
        getByName("main") {
            java.srcDirs("src/main/kotlin")
        }
        getByName("test") {
            java.srcDirs("src/test/kotlin")
        }
    }

    testOptions {
        unitTests {
            isReturnDefaultValues = true
        }
    }

    lint {
        abortOnError = false
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.12.0")
    implementation("androidx.appcompat:appcompat:1.6.1")
    implementation("androidx.leanback:leanback:1.0.0")

    testImplementation("junit:junit:4.13.2")
}
