# Run TravelMate on Windows

Use four terminals.

## Terminal 1 — Backend API

```powershell
cd backend_api
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
# edit .env, then:
python app.py
```

Backend: `http://127.0.0.1:5000`

## Terminal 2 — Tourism Operator Website

```powershell
cd operator_website
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
# edit .env, then:
python app.py
```

Operator website: `http://127.0.0.1:5001`

## Terminal 3 — Administrator Website

```powershell
cd admin_website
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
# edit .env, then:
python app.py
```

Admin website: `http://127.0.0.1:5002`

## Terminal / Android Studio — Traveller Mobile

```powershell
cd traveller_mobile
flutter create .
flutter pub get
flutterfire configure
flutter run
```

Android emulator uses `http://10.0.2.2:5000` to reach your PC backend.

For a physical phone, run with your PC LAN IP:

```powershell
flutter run --dart-define=API_BASE_URL=http://192.168.0.15:5000
```

Replace `192.168.0.15` with your computer's actual IPv4 address from `ipconfig`.

## Local Android HTTP note

The starter backend uses local `http://` URLs during development. If your generated Android project blocks clear-text HTTP, edit:

`traveller_mobile/android/app/src/main/AndroidManifest.xml`

and add this to the `<application ...>` element for local development:

```xml
android:usesCleartextTraffic="true"
```

Do this only for the local-development build. A deployed system should use HTTPS.

If a physical phone cannot reach the backend, confirm that the phone and PC are on the same Wi-Fi network and allow Python through Windows Firewall for your private network.
