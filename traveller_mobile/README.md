# TravelMate Traveller Mobile App

This is the real Flutter Traveller application starter, not a screenshot-only prototype.

## Main functions included

- Firebase Email/Password registration, login, reset password and logout
- Traveller profile linked to backend + Firestore
- Travel preference questionnaire
- Destination search + favourites
- Simple hybrid-recommendation framework
- Itinerary creation and Firestore storage
- Open-Meteo weather
- SerpApi Google Flights
- LiteAPI/Nuitee hotel search + prebook framework
- Stripe sandbox payment workflow
- Feedback and rating
- Gemini travel chatbot with Firestore chat history

## Create Android/iOS folders

From this directory:

```bash
flutter create .
flutter pub get
```

Then configure Firebase:

```bash
dart pub global activate flutterfire_cli
flutterfire configure
```

This generates `lib/firebase_options.dart`, which is required by `lib/main.dart`.

## Backend URL

Android emulator uses the default:

`http://10.0.2.2:5000`

For a physical phone, use your computer's LAN IP, e.g.:

```bash
flutter run --dart-define=API_BASE_URL=http://192.168.0.15:5000
```

Your phone and computer must be on the same network and your firewall must allow the Flask port.
