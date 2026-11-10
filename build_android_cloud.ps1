param(
  [Parameter(Mandatory=$true)]
  [string]$BackendUrl
)

$ErrorActionPreference = "Stop"
Set-Location "$PSScriptRoot\traveller_mobile"
flutter clean
flutter pub get
flutter build apk --release --dart-define=API_BASE_URL=$BackendUrl --dart-define=ENABLE_ANDROID_PUSH=true
Write-Host ""
Write-Host "APK created with cloud backend:" $BackendUrl
Write-Host "Output: build\app\outputs\flutter-apk\app-release.apk"
