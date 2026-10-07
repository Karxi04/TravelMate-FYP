# Firebase + Firestore Setup

This is the required setup before the real app/websites can save data.

## 1. Create Firebase project

This checkout uses `travelmate2-30a8a`. Use that existing project for the current
demo. If you deliberately change projects, Flutter options, Android Firebase
registration, backend credentials and both portal Web API keys must change
together; do not create a replacement project merely to run this checkout.

## 2. Enable Authentication

Firebase Console:

`Build -> Authentication -> Get started -> Sign-in method -> Email/Password -> Enable`

This is used by:
- Traveller mobile registration/login
- Tourism Operator website registration/login
- Administrator website login

## 3. Create Cloud Firestore

Firebase Console:

`Build -> Firestore Database -> Create database`

For development, choose a region reasonably near your users. You do not need to create collections manually; the backend will create documents when functions are used.

## 4. Create backend service account JSON

Firebase Console:

`Project Settings -> Service accounts -> Generate new private key`

Save the JSON file as:

`backend_api/serviceAccountKey.json`

Do NOT commit or upload this JSON to GitHub.

Then create:

`backend_api/.env`

from `.env.example` and keep:

```env
FIREBASE_SERVICE_ACCOUNT=serviceAccountKey.json
```

## 5. Configure Flutter Traveller app

Install Firebase CLI, sign in, then install FlutterFire CLI.

From `traveller_mobile`:

```powershell
flutter pub get
firebase login
dart pub global activate flutterfire_cli
flutterfire configure
```

The existing checkout is already configured. Run `flutterfire configure` only
when intentionally changing that configuration, selecting the same Firebase
project as the backend/portals and preserving the registered application ID.

`flutterfire configure` generates:

`traveller_mobile/lib/firebase_options.dart`

The existing `main.dart` already imports this file.

## 6. Get Firebase Web API key for Operator/Admin websites

Firebase Console:

`Project Settings -> General -> Your apps / Web API key`

Copy the Web API key.

Create:

`operator_website/.env`

```env
SECRET_KEY=replace-with-a-random-string
FIREBASE_WEB_API_KEY=YOUR_FIREBASE_WEB_API_KEY
BACKEND_URL=http://127.0.0.1:5000
PORT=5001
```

Create:

`admin_website/.env`

```env
SECRET_KEY=replace-with-another-random-string
FIREBASE_WEB_API_KEY=YOUR_FIREBASE_WEB_API_KEY
BACKEND_URL=http://127.0.0.1:5000
PORT=5002
```

The Web API key identifies your Firebase project; do not confuse it with the backend service-account private key.

## 7. Create first Administrator

After backend dependencies are installed and `.env` is configured:

```powershell
cd backend_api
.venv\Scripts\activate
python scripts/create_admin.py --email $env:TM_DEMO_ADMIN_EMAIL --password $env:TM_DEMO_ADMIN_PASSWORD --name "TravelMate Administrator"
```

Supply your own email/password privately in those temporary environment
variables. Do not use or commit shared demo passwords. This is an intentional
live Firebase provisioning action, not part of the automated test suite.
It creates the Firebase Authentication account and its Firestore `users/{uid}`
document with role `admin`. An operator also needs active status and an
administrator-approved `verificationStatus` before using its portal.

## 8. Firestore rules

The architecture routes application database traffic through the backend. Deploy the supplied rules from `firebase/firestore.rules` if you use Firebase CLI.

The rules permit authenticated reads of approved shared packages/campaigns
and limited validated traveller review access; other client data access is
denied and goes through the trusted backend. Preserve these allowlists.
Firebase Authentication still works normally.

## 9. Verify connection

Start backend and open:

`http://127.0.0.1:5000/api/health`

Then register a Traveller from Flutter. In Firestore Console you should see:

`users -> <traveller uid>`

Then save preferences and you should see:

`travel_preferences -> <same uid>`
