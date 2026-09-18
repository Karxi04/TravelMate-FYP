# TravelMate Enhanced System

This revision keeps the proposed FR1-FR13 structure but improves the actual usability of the Traveller application and the two management websites.

## Traveller first login

New account registration -> Firebase Authentication -> TravelMate profile -> mandatory Travel Preference questionnaire -> Home.

The questionnaire appears when no preference profile exists. After it is saved, later logins enter the main app directly. It can still be updated from Profile > Travel preferences.

## No-cable usage

The Traveller app now has two runtime modes.

### 1. Standalone mode (works immediately after installation)

No Flask process, USB cable, adb reverse, or PC connection is required. Core data is persisted on the Android device and the same API contracts are handled locally. The following functions work:

- registration/login through Firebase Authentication
- first-login questionnaire
- profile and travel preferences
- destination search/details/favourites
- Hybrid Recommendation Engine
- Personalised Planning
- Smart Itinerary Generator
- Budget Estimation and Comparison
- weather (uses Open-Meteo directly when internet is available)
- flight search/compare/select using the available local provider catalogue
- hotel search/compare/prebook/booking using the available local provider catalogue
- feedback
- TravelMate Assistant
- local payment records

Build with:

    .\build_android_standalone.ps1

### 2. Cloud mode (recommended final deployment)

Deploy `backend_api` once to a public HTTPS host. Put Firebase and external provider credentials in that host. Build the APK with the cloud URL:

    .\build_android_cloud.ps1 -BackendUrl "https://YOUR-BACKEND-URL"

After installation, the phone/tablet connects over normal Internet/Wi-Fi/mobile data. The PC and USB cable are no longer needed. The cloud backend can provide SerpApi, LiteAPI/Nuitee, Gemini and Stripe integration without exposing secret keys in the APK.

## Why both modes exist

Secret provider keys should not be embedded in a mobile APK. Standalone mode therefore keeps the app usable without a server, while cloud mode preserves the proposed secure Flask backend architecture for live third-party integrations.

## Operator and Administrator websites

Both websites remain separate applications. Their dashboards were enhanced with clearer KPIs, quick actions, approval/moderation workspaces, account readiness information and responsive layouts.
