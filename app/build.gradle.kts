plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.amazon.mercury.wallboard"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.amazon.mercury.wallboard"
        // Fire OS 7 is based on Android 9 (API 28). Fire OS 8 is Android 11 (API 30).
        minSdk = 28
        targetSdk = 34
        versionCode = 1
        versionName = "1.0.0"

        // The cockpit this build points at. Override per build with
        //   ./gradlew assembleDebug -PmercuryCockpitUrl=http://192.168.1.20:8002/
        // or per launch with the COCKPIT_URL intent extra.
        buildConfigField(
            "String",
            "MERCURY_COCKPIT_URL",
            "\"${project.findProperty("mercuryCockpitUrl") ?: "http://10.0.2.2:8002/"}\"",
        )
    }

    buildFeatures {
        buildConfig = true
    }

    buildTypes {
        debug {
            // Fire TV sticks on a home network usually serve the cockpit over
            // plain http from a laptop, so cleartext is allowed in debug only.
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
