# Driver app: set up Android Studio (build phase 3)

Goal: open the app in Android Studio, run the `core` tests, and create the
Android module that will become the driver app. You do each step yourself
the first time (CLAUDE.md working rules).

## Step 1 — install Android Studio

**What:** Android Studio is the editor for Android apps. It bundles three
things you need: a JDK (Java runtime, which Gradle and Kotlin run on), the
Android SDK (the libraries and tools for building an APK), and an emulator
(a virtual phone).

Download it from developer.android.com/studio and run the setup wizard with
the standard options. It downloads the SDK (a few GB).

## Step 2 — run the `core` tests from the terminal

**What:** Gradle is the build tool. `./gradlew` is the *Gradle wrapper*: a
small script, committed to the repo, that downloads the exact Gradle version
this project uses (8.14.3), so everyone builds the same way. The first run
downloads Gradle, Kotlin and the libraries, which takes a few minutes.

Gradle needs a JDK (17 or newer). Use the one inside Android Studio:

```bash
# macOS
export JAVA_HOME="/Applications/Android Studio.app/Contents/jbr/Contents/Home"
# Windows (PowerShell)
$env:JAVA_HOME = "C:\Program Files\Android\Android Studio\jbr"
```

Then:

```bash
cd app
./gradlew :core:test
```

(On Windows: `.\gradlew.bat :core:test`.) Expect `BUILD SUCCESSFUL`. The
test report is at `app/core/build/reports/tests/test/index.html`.

## Step 3 — open the project

**What:** Android Studio reads `app/settings.gradle.kts` to find the modules.
"Gradle sync" is it running Gradle to work out the dependencies.

File → Open → choose the **`app/`** folder (not the repo root). Wait for the
sync to finish, then open `core/src/test/...` and press the green arrow next
to a test.

## Step 4 — create the Android module

**What:** a *module* is a part of the project with its own build file. The
Android module is the installable app; it depends on `:core` for all logic.

1. File → New → New Module… → **Phone & Tablet**.
2. Module name: `android`. Package name: `com.turnwise.driver`.
   Minimum SDK: **API 26 (Android 8.0)**, which covers almost every phone
   drivers use. Language: Kotlin. Build configuration language: Kotlin DSL.
3. Template: **Empty Views Activity**. (Compose is fine later; the first
   screen is one big push-to-talk button.)
4. Finish. Android Studio adds `include(":android")` to `settings.gradle.kts`
   and the Android Gradle plugin to `build.gradle.kts`.
5. In `android/build.gradle.kts`, inside `dependencies { }`, add:
   ```kotlin
   implementation(project(":core"))
   ```
6. Sync, then Run ▶ on the emulator. You should see "Hello World".

Commit the new module on a branch (`ram/app-android-shell`) and open a PR.

## Step 5 — permissions the app will need (next PR, not now)

Write these down; they come with the location service and the mic:

| Permission | Why |
|---|---|
| `ACCESS_FINE_LOCATION` | 1 Hz GPS for the route engine. |
| `FOREGROUND_SERVICE`, `FOREGROUND_SERVICE_LOCATION` | Keep GPS running with the screen off, with a visible notification (Android requires one). |
| `RECORD_AUDIO` | Push-to-talk only. The mic opens on press and closes on release. |
| `INTERNET` | GPS upload, events WebSocket, Sarvam. |
| `POST_NOTIFICATIONS` | The foreground-service notification on Android 13+. |

Background location (`ACCESS_BACKGROUND_LOCATION`) is **not** needed: a
foreground service with a notification counts as foreground, and asking for
background location triggers a much stricter Play Store review.

## Without Android Studio: build the debug app from the command line

The `android` module (the installable app) is in the repo, so Step 4 above is already done.
To build it without Android Studio you need two things in `%USERPROFILE%\.turnwise-tools`:
a JDK 17 (folder `jdk17`, the Eclipse Temurin zip) and the Android SDK (folder `android-sdk`
with `platforms/android-35`, `build-tools/35.0.0` and `platform-tools`, installed with Google's
command-line tools after accepting the SDK licence). Then, in PowerShell:

```powershell
cd app
```
```powershell
.\build-debug.ps1
```

It runs the `core` and `android` unit tests and writes
`app\android\build\outputs\apk\debug\android-debug.apk`.

### Put it on a phone

Either copy the APK to the phone and open it (Android asks to allow installing from that
source), or, with USB debugging switched on and the phone plugged in, from the repo root:

```powershell
& "$env:USERPROFILE\.turnwise-tools\android-sdk\platform-tools\adb.exe" install -r app\android\build\outputs\apk\debug\android-debug.apk
```

### Run a test with it

1. Laptop on the phone's hotspot; `docker start valhalla`; then
   `.venv\Scripts\python.exe -m backend.fieldserver --http` (plain http: the debug app allows it,
   release builds do not). It prints the server address and the token.
2. In the app: agree to location tracking, enter the address and token, allow location and
   notifications, tap a destination on the map, press **Start trip**.
3. The screen can be off: a notification shows while the trip is tracked. **End trip** stops GPS.

What this build is: a field-test shell on `core`. Speech is the phone's own voice and questions
are buttons; push-to-talk and Sarvam audio come when the voice service has an HTTP endpoint.
The GPS buffer is in memory (lost if Android kills the app), and the token is stored unencrypted.
