# Run TravelMate on Windows

Use four terminals.

See `FINAL_DEMO_READINESS.md` for account approval, current Firebase state,
test requirements, and release safety. Copy an `.env.example` only when `.env`
does not already exist; preserve privately configured local files.

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
flutter pub get
flutter run
```

Android emulator uses `http://10.0.2.2:5000` to reach your PC backend.

This checkout already has Android/Firebase platform configuration. Do not run
`flutter create .` or reconfigure Firebase just to start the existing demo.
For a physical phone, set `TM_DEMO_API_URL` to your reachable backend URL:

```powershell
flutter run --dart-define=API_BASE_URL=$env:TM_DEMO_API_URL
```

For a local debug backend, use your own PC address from `ipconfig`; the phone
must be able to reach it. Cloud release requires explicit HTTPS configuration.

## Local Android HTTP note

The debug Android manifest allows local HTTP. Do not enable clear-text HTTP
in the main/release manifest; deployed cloud releases require HTTPS.

If a physical phone cannot reach the backend, confirm that the phone and PC are on the same Wi-Fi network and allow Python through Windows Firewall for your private network.
