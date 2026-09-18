# TravelMate: Use the Android app without USB or a local Flask server

## Fastest option: Standalone APK

From the project root:

    .\build_android_standalone.ps1

Install:

    traveller_mobile\build\app\outputs\flutter-apk\app-release.apk

The installed app uses Firebase Authentication plus its local persistent application data. It does not point to `127.0.0.1:5000` and does not require `adb reverse`.

## Recommended final option: deploy Flask once

The project includes:

- `render.yaml`
- `backend_api/Procfile`
- `backend_api/Dockerfile`

A public HTTPS backend lets the installed APK use live third-party providers without storing secret keys in Flutter.

Configure the cloud service with:

    FIREBASE_SERVICE_ACCOUNT_JSON={...full service-account JSON...}
    FALLBACK_MODE=true
    SERPAPI_KEY=...
    LITEAPI_KEY=...
    STRIPE_SECRET_KEY=...
    GEMINI_API_KEY=...
    GEMINI_MODEL=...

Then build:

    .\build_android_cloud.ps1 -BackendUrl "https://YOUR-BACKEND-URL"

No cable is needed after the APK is installed.
