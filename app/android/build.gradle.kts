plugins {
    id("com.android.application")
    kotlin("android")
    kotlin("plugin.serialization")
}

android {
    namespace = "com.turnwise.driver"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.turnwise.driver"
        minSdk = 26            // Android 8.0: covers almost every phone drivers use
        targetSdk = 35
        versionCode = 1
        versionName = "0.1-fieldtest"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }

    testOptions { unitTests.isReturnDefaultValues = true }
    lint { abortOnError = true; warningsAsErrors = false }
}

dependencies {
    implementation(project(":core"))
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.7.3")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")        // HTTP + the events WebSocket
    implementation("org.osmdroid:osmdroid-android:6.1.20")      // OpenStreetMap view (no Google Maps)

    testImplementation(kotlin("test-junit"))                     // JUnit 4, the Android unit-test default
    testImplementation("junit:junit:4.13.2")
    testImplementation("com.squareup.okhttp3:mockwebserver:4.12.0")
}
