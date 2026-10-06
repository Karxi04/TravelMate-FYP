# TravelMate final demo and release setup (Batch 6D)

This guide is the current operational checklist. Keep the existing Android
application ID `com.example.travelmate_traveller`: it matches this checkout's
Firebase Android registration. The configured project is `travelmate2-30a8a`.
Do not regenerate platform folders or migrate Firebase identity for this demo.

## Accounts and Firebase prerequisites

Use your own accounts and privately supplied credentials. No passwords/tokens
are embedded in this guide or provisioned by the regression suite.

| Account | Required state |
| --- | --- |
| Traveller | Firebase Email/Password account; active `users/{auth UID}` with `role: traveller`; completed `travel_preferences/{same UID}` questionnaire |
| Administrator | Firebase account and active `users/{auth UID}` with `role: admin`; no public admin registration |
| Operator | Firebase account and active `users/{auth UID}` with `role: operator`; **`verificationStatus: approved` or `verified`** |

New operators start pending and cannot enter the operator portal or mutate
operator content. The administrator must approve the account before the demo.
Operator approval is separate from each package/campaign's publication review.

Enable Firebase Email/Password authentication and Firestore. The Flutter
options, Android `google-services.json`, portal Web API keys, and backend Admin
credential must all belong to the same project. Client Firebase identifiers
are public configuration; the Admin service account/private key is confidential.
Retain the supplied Firestore rules: approved shared content and validated
traveller reviews have limited direct access, while other data goes through
the trusted backend. Do not replace them with open demo rules.

For first-admin creation, the existing `backend_api/scripts/create_admin.py`
accepts email/password arguments. Supply your own private values, preferably
through temporary environment variables; do not copy example passwords into
the account. Run it only when intentionally provisioning your Firebase project.
The final automated suite never invokes this mutation script.

Live account existence, approval state, deployed rules/indexes, and physical
device login still require your manual preflight. They are not established by
mocked regression tests or by `/api/health`.

## Start the integrated product

From the repository root, use separate PowerShell terminals. The project
requires its root shared files as well as the backend/portal directories.
Create `.env` from `.env.example` only if absent; never overwrite a configured
file blindly. Keep local secret files ignored.

Backend setup (Python 3.11 or 3.12):

```powershell
cd backend_api
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe app.py
```

Configure `FIREBASE_SERVICE_ACCOUNT=serviceAccountKey.json`, or privately supply
`FIREBASE_SERVICE_ACCOUNT_JSON`/Application Default Credentials. Firestore/auth
still require working Firebase credentials when provider fallback is enabled.
`FALLBACK_MODE=true` keeps optional provider failures demonstrable. The public
health endpoint confirms process startup only, not Firebase/provider readiness.
`GET /api/config-status` requires an admin Firebase token and reports only safe
payment/hotel capability modes.

Operator and administrator setup:

```powershell
# Terminal 2
cd operator_website
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe app.py

# Terminal 3, starting from the repository root
cd admin_website
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe app.py
```

Their `.env` files require `FIREBASE_WEB_API_KEY`, a privately generated
`SECRET_KEY`, and `BACKEND_URL=http://127.0.0.1:5000` for local setup. Ports are
5001 (operator) and 5002 (admin). Install Flask-WTF through the portal
requirements. All state-changing forms, including login/logout, require CSRF
tokens. Missing/invalid tokens receive safe 400 reload guidance.

Keep `FLASK_DEBUG=false`. Local development may use `APP_ENV=development` and
`SESSION_COOKIE_SECURE=false`; deployments require a strong secret,
`APP_ENV=production`, secure cookies, and HTTPS. CORS, if needed for a browser
API client, uses an explicit `CORS_ALLOWED_ORIGINS` allowlist; native Flutter
and portal server-to-server requests do not need permissive CORS.

Traveller startup:

```powershell
cd traveller_mobile
flutter pub get
flutter run
```

Debug Android defaults to `http://10.0.2.2:5000`; Web/Desktop debug defaults to
`http://127.0.0.1:5000`. Debug Android alone allows clear-text HTTP. A physical
device needs an explicit reachable backend URL; set `TM_DEMO_API_URL` privately
for your local/deployed environment and run:

```powershell
flutter run --dart-define=API_BASE_URL=$env:TM_DEMO_API_URL
```

Cloud mode never silently switches to standalone when the backend is down.
Firebase login happens first, then profile/questionnaire, Home and other modules
depend on the selected backend. `STANDALONE_MODE=true` is an explicit alternative:
it uses local single-device planning/bookings/payments, still uses Firebase
Authentication, and accesses shared approved content/reviews through Firestore.
Standalone data is not the cloud portal's transaction store.

## Release commands and signing

From `traveller_mobile`, for a cloud APK set `TM_DEMO_API_URL` to your actual
reachable HTTPS backend (no embedded credentials, query token, or fragment):

```powershell
flutter build apk --release --dart-define=API_BASE_URL=$env:TM_DEMO_API_URL
```

The Android build rejects a cloud release with no explicit API URL. Before
Firebase/network initialization, the runtime also rejects non-HTTPS, localhost,
emulator-only, or credential-bearing cloud URLs. Debug local defaults remain.
Configuration validation is not a DNS/health check; verify backend reachability
on the demo device separately.

For an explicitly local FYP demonstration:

```powershell
flutter build apk --release --dart-define=STANDALONE_MODE=true
```

Both release variants currently use the existing **debug signing configuration**.
They are FYP artifacts, not production-signed/store-ready releases. No private
release keystore is created. Keep `key.properties`, passwords and keystores
out of Git. The placeholder-style application ID and production signing remain
distribution technical debt, not reasons to migrate the working demo now.

APK output is `build/app/outputs/flutter-apk/`. Export review/demo artifacts to
your fixed workspace; do not confuse a previously built APK with the current
configuration.

## Optional providers and honest fallback

| Service | Optional configuration | Behavior without usable provider |
| --- | --- | --- |
| Destination/flight | `SERPAPI_KEY` | Eligible cache/local samples with provenance when fallback is enabled; unresolved/out-of-scope places remain filtered |
| Hotel | `LITEAPI_KEY` | Matching Penang demo offers only; unsupported localities have no demo offers. Booking is labelled Demo booking/Simulated confirmation, not an external reservation |
| Payment | Stripe **test** `STRIPE_SECRET_KEY` only | `pi_sim_...` local simulation; standalone uses `TM-PAY-...`; UI labels simulation and no real money is charged |
| Chat | `GEMINI_API_KEY`, optional `GEMINI_MODEL` | Deterministic local assistant when fallback is enabled; failed live calls are labelled local, not Gemini |
| Weather | Open-Meteo, no key | Weather tool can report unavailable; itinerary dates without forecasts carry unavailable disclosure, not invented forecasts |

Bundled car rental is a local adapter. Set `FALLBACK_MODE=false` only when you
want provider errors/unavailable states instead of demo fallback. Use Penang
for the predictable bundled demo: the fallback catalog is finite and cannot
promise coverage for every requested destination. Reused recommendation
snapshots retain their original provenance and are not rewritten by outages,
feedback, or a newer generation.

Use stable `paymentAttemptId` and `hotelBookingAttemptId` values. After an
ambiguous outcome, reconcile the same logical operation through
`GET /api/fr9/payments/attempts/<id>` or
`GET /api/fr8/bookings/attempts/<id>`. Payment/hotel keys remain internal.
LiteAPI ambiguous booking outcomes can require manual provider verification;
do not blindly retry them. TravelMate payment cancellation is not a refund.

Request budgets remain process-local: auth 10/minute, chat 12, recommendation
generation 6, provider reads/searches 30, payment mutations 10, hotel mutations
10. 429 supplies safe guidance and `Retry-After`; wait before repeating the
same operation. Budgets reset per worker/restart. Proxy IP handling, direct
Firebase quotas, server-side sessions, distributed limiting, App Check and
background reconciliation remain production limitations.

## Safe automated checks

From the repository root:

```powershell
backend_api/.venv/Scripts/python.exe -m pip install -r backend_api/requirements-test.txt
backend_api/.venv/Scripts/python.exe -m pytest
cd traveller_mobile
flutter test
flutter analyze
flutter build apk --debug
```

The default Python suite blocks sockets and live Firebase, clears provider
credentials, mocks identity/persistence/provider boundaries, and enforces
20-second test timeouts. CSRF/rate limiting remain enabled. The integrated
journey exercises registration/profile and login contracts, preferences/Home,
scoped recommendations/details, actual itinerary generation/editing, feedback,
learned-version changes, explicit refresh, changed scores/ranking, immutable
historical snapshots, and portal-to-backend approval/publication workflows.
Firebase email/password exchange and persistence are simulated boundaries;
this is not a claim of live identity/provider validation.

Docker, when available, builds **from the repository root**:

```powershell
docker build -f backend_api/Dockerfile -t travelmate-backend .
```

The Python 3.11 image includes the shared limiter and excludes private files
through the root `.dockerignore`. Supply credentials at runtime, not in the
image. A Windows Python 3.11 regression run does not prove Linux/Gunicorn or
container-runtime behavior; report Docker verification separately.

## Manual FYP demonstration sequence

1. Confirm all three real account roles/statuses, Firebase project/rules, and
   backend reachability. Approve the demo operator before using its portal.
2. Register/login as traveller; complete the questionnaire and open Home.
3. Generate Penang recommendations; show provenance and destination details.
4. Plan with that exact generation ID, build itinerary, open its exact Trip
   Details, reorder/edit, and show recalculated schedule/budget/weather notes.
5. Give More like this/Not for me feedback; explicitly refresh recommendations.
   Show the new generation/learned version while the original trip/snapshot stays.
6. Show clearly simulated hotel/payment outcomes when using fallback. Avoid live
   financial/booking mutations during automated checks or an uncontrolled demo.
7. Operator creates/submits package; admin reviews it; traveller sees approved
   content. Repeat for a campaign with a current valid date range.
8. Show missing-CSRF rejection, unverified-operator denial, and safe 429 guidance
   with isolated tests rather than weakening protection on the live project.

Freeze only after the safe suite, analysis, debug build, release guard, integrated
journey/failure paths and secret audit pass. Physical-device/server preflight is
still required before presenting; production infrastructure is not an FYP
code-freeze prerequisite.
