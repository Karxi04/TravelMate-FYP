# TravelMate local Windows and Android demo

This is a local-only FYP demonstration. The PC must remain on, the phone must be on the same trusted Wi-Fi, and this is not a public deployment.

1. Copy each `.env.example` to `.env` in `backend_api`, `operator_website`, and `admin_website`. Keep `APP_ENV=development`; set the existing Firebase client web API key only in the two portal files. Do not commit any `.env` file.
2. In `backend_api/.env`, set `LOCAL_LAN_DEMO=true` and `TRUSTED_LAN_CIDR` to the private Wi-Fi subnet, for example `192.168.1.0/24`. Keep provider keys empty unless you deliberately need their sandbox flow.
3. Run `powershell -ExecutionPolicy Bypass -File .\Start-TravelMate-Local.ps1 -TrustedLanCidr 192.168.1.0/24` from the repository root. It starts the backend, Operator, and Admin, then checks their health URLs.
4. Build the explicitly local debug APK, replacing the example address with the PC's active Wi-Fi IPv4 address:

```powershell
cd traveller_mobile
flutter build apk --debug --dart-define=LOCAL_DEMO=true --dart-define=API_BASE_URL=http://192.168.1.25:5000
```

5. Install `build\app\outputs\flutter-apk\app-debug.apk`. From the phone browser, open `http://192.168.1.25:5000/api/health` before opening TravelMate.

The debug manifest permits cleartext HTTP. Production release builds still require a public HTTPS API URL and reject private addresses. If Windows Firewall blocks the phone, create an inbound TCP 5000 rule limited to the **Private** profile and the same trusted subnet; do not expose the port to Public networks.
