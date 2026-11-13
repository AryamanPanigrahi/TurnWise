// The driver app. `core` is pure Kotlin (no Android imports), so its logic runs
// and is tested on a plain JVM. The Android module that wraps it is created in
// Android Studio (see docs/setup/android-app.md) and depends on `:core`.
// `android` is the installable driver app: a thin shell around `core`.
rootProject.name = "turnwise-driver"

pluginManagement {
    repositories {
        gradlePluginPortal()
        google()
        mavenCentral()
    }
}

dependencyResolutionManagement {
    repositories {
        google()
        mavenCentral()
    }
}

include(":core")
include(":android")
