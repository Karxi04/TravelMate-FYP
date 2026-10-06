# TravelMate Traveller Mobile App

This is the Flutter Traveller application. Current setup, account prerequisites
and the FYP demo checklist are in `../docs/FINAL_DEMO_READINESS.md`.

## Main functions included

- Firebase Email/Password registration, login, reset password and logout
- Traveller profile linked to backend + Firestore
- Travel preference questionnaire
- Destination search + favourites
- Hybrid recommendations with immutable generation snapshots and preference learning
- Itinerary creation and Firestore storage
- Open-Meteo weather
- SerpApi Google Flights
- LiteAPI/Nuitee hotel search, prebook and booking with explicit demo fallback
- Stripe sandbox payment workflow
- Feedback and rating
- Gemini travel chatbot with Firestore chat history

## Start the existing Android checkout

From this directory:

```bash
flutter pub get
flutter run
```

Android and Firebase are already configured for this checkout. Only if you
intentionally switch Firebase projects, configure it with:

```bash
dart pub global activate flutterfire_cli
flutterfire configure
```

This generates `lib/firebase_options.dart`, which is required by `lib/main.dart`.

## Backend URL

Android emulator uses the default:

`http://10.0.2.2:5000`

For a physical phone, set `TM_DEMO_API_URL` to your reachable backend:

```bash
flutter run --dart-define=API_BASE_URL=$env:TM_DEMO_API_URL
```

Your phone and computer must be on the same network and your firewall must allow the Flask port.

Cloud release requires explicit HTTPS configuration and rejects missing or
emulator-only URLs. From this directory:

```powershell
flutter build apk --release --dart-define=API_BASE_URL=$env:TM_DEMO_API_URL
# Explicit single-device FYP demo alternative, still requiring Firebase login:
flutter build apk --release --dart-define=STANDALONE_MODE=true
```

Release APKs currently use debug signing and are not production/store-ready.
