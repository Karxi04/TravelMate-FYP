$ErrorActionPreference = "Stop"

Set-Location "$PSScriptRoot\traveller_mobile"

Write-Host "Preparing Flutter Android project..."
flutter create . --platforms=android
flutter pub get

$manifest = Join-Path $PWD "android\app\src\main\AndroidManifest.xml"
if (Test-Path $manifest) {
    $text = Get-Content $manifest -Raw
    if ($text -notmatch "android.permission.INTERNET") {
        $text = $text -replace "<manifest([^>]*)>", "<manifest`$1>`r`n    <uses-permission android:name=`"android.permission.INTERNET`" />"
    }
    if ($text -notmatch "usesCleartextTraffic") {
        $text = $text -replace "<application", "<application android:usesCleartextTraffic=`"true`""
    }
    Set-Content -Path $manifest -Value $text -Encoding UTF8
}

Write-Host "Next:"
Write-Host "1. Restore/generate lib\firebase_options.dart with flutterfire configure"
Write-Host "2. Start backend_api\app.py on port 5000"
Write-Host "3. adb reverse tcp:5000 tcp:5000"
Write-Host "4. flutter analyze"
Write-Host "5. flutter run"
