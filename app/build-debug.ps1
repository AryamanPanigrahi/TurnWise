# Build the debug driver app (APK) from PowerShell:   .uild-debug.ps1
# Uses the JDK and Android SDK in %USERPROFILE%\.turnwise-tools if JAVA_HOME is not already set
# (see docs/setup/android-app.md, "Without Android Studio").
$tools = Join-Path $env:USERPROFILE ".turnwise-tools"
if (-not $env:JAVA_HOME -and (Test-Path "$tools\jdk17")) { $env:JAVA_HOME = "$tools\jdk17" }
if (-not (Test-Path "$PSScriptRoot\local.properties") -and (Test-Path "$toolsndroid-sdk")) {
    "sdk.dir=" + ("$toolsndroid-sdk" -replace "\\", "/" -replace ":", "\:") | Out-File -Encoding ascii "$PSScriptRoot\local.properties"
}
& "$PSScriptRoot\gradlew.bat" :core:test :android:testDebugUnitTest :android:assembleDebug --console=plain
if ($LASTEXITCODE -eq 0) { Write-Host "`nAPK: $PSScriptRootndroiduild\outputspk\debugndroid-debug.apk" }
