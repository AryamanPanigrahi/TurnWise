# Build the debug driver app (APK) from PowerShell:   .\build-debug.ps1
#
# Uses the JDK and Android SDK in %USERPROFILE%\.turnwise-tools when JAVA_HOME / ANDROID_HOME
# are not already set (see docs/setup/android-app.md, "Without Android Studio").
# It changes these variables for this PowerShell window only, not for the system.

$tools = Join-Path $env:USERPROFILE ".turnwise-tools"
$jdk = Join-Path $tools "jdk17"
$sdk = Join-Path $tools "android-sdk"
$localProps = Join-Path $PSScriptRoot "local.properties"

if (-not $env:JAVA_HOME -and (Test-Path $jdk)) { $env:JAVA_HOME = $jdk }
if (-not $env:ANDROID_HOME -and -not (Test-Path $localProps) -and (Test-Path $sdk)) { $env:ANDROID_HOME = $sdk }

& (Join-Path $PSScriptRoot "gradlew.bat") -p $PSScriptRoot :core:test :android:testDebugUnitTest :android:assembleDebug --console=plain
if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host ("APK: " + (Join-Path $PSScriptRoot "android\build\outputs\apk\debug\android-debug.apk"))
}
exit $LASTEXITCODE
