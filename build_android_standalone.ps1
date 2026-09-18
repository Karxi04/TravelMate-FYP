$ErrorActionPreference = "Stop"
Set-Location "$PSScriptRoot\traveller_mobile"
flutter clean
flutter pub get
flutter build apk --release --dart-define=STANDALONE_MODE=true
Write-Host ""
Write-Host "Standalone APK created. No local Flask server or adb reverse is required."
Write-Host "Output: build\app\outputs\flutter-apk\app-release.apk"
