# TravelMate Shared Flask REST API

All three frontends use this backend:

- Traveller Flutter mobile app
- Tourism Operator website
- Administrator website

The backend verifies Firebase ID tokens and uses the Firebase Admin SDK to read/write Firestore.

For current account prerequisites, portal/mobile startup, safe release builds,
and the integrated FYP demonstration, use `../docs/FINAL_DEMO_READINESS.md`.
Docker builds require the repository-root context:
`docker build -f backend_api/Dockerfile -t travelmate-backend .`.
The root `.dockerignore` excludes private credentials and environment files;
provide Firebase/provider credentials at runtime. Health confirms process
startup, not live Firebase/provider readiness.

## Run

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python app.py
```

The deployment image currently uses Python 3.11. The backend and its bounded
dependencies also support newer compatible Python 3.x environments used for
local regression testing.

## Test

Create a dedicated virtual environment and install the test dependency set:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-test.txt
.venv\Scripts\python.exe -m pytest
```

`requirements.txt` remains the production/runtime dependency set.
`requirements-test.txt` adds pytest, per-test timeout protection, socket
blocking, and Flask-WTF for portal security regression tests. The default suite clears provider credentials, mocks Firebase
initialization, blocks direct Firestore access, and disables network sockets.
Tests that intentionally need a live service must be marked `integration` and
are excluded from normal runs; they must never be run with production data.

Health checks:

- `GET /api/health`
- `GET /api/config-status` (Administrator Firebase token required; returns only payment/hotel capability modes)

Browser CORS is disabled unless `CORS_ALLOWED_ORIGINS` contains a
comma-separated list of explicit origins. Native Flutter requests are not
affected by browser CORS. Wildcard origins are rejected.

## Portal CSRF and request budgets (Batch 6C2)

Install each portal's own `requirements.txt` when deploying it. Both portals
use Flask-WTF `CSRFProtect`, initialized in `portal_security_config.py`.
CSRF is enabled globally for POST/PUT/PATCH/DELETE, uses the portal's existing
`SECRET_KEY`, and expires after one hour. HTTPS same-origin referrer checks
remain enabled. Every POST form renders a signed `csrf_token` hidden field.
Missing, invalid, expired, or session-mismatched tokens return a generic 400
with reload guidance and `Cache-Control: no-store`; no validation internals
are returned. Logout now requires POST with a token.

Protected administrator operations: login/logout, role/status/operator
verification updates, package/campaign review, destination/activity
create/update/delete, and feedback moderation/removal. There is no public
administrator registration/reset/profile form. Protected operator operations:
login/register/password-reset/profile/logout and all package/campaign
create/edit/submit/delete routes, including alternate edit/submission pages.
There are no portal mutation exemptions. Read-only report filters remain GET.

The separate backend API does not install browser CSRF middleware: Firebase
bearer-token JSON APIs, including portal-to-backend calls, remain accessible
without form tokens. A JSON content type or bearer header does **not** bypass
CSRF on a browser portal route.

`request_rate_limit.py` supplies one reusable process-local sliding-window
limiter. Each Flask application owns its instance in
`app.extensions['request_rate_limiter']`. A lock makes checks/increments atomic
across threads; a monotonic clock measures a rolling 60-second window. Expired
identity buckets are pruned on subsequent traffic, at most once per minute.
Related endpoints share a category budget, so changing resource/attempt IDs
does not evade a limit.

| Category | Requests per rolling minute | Operations |
| --- | ---: | --- |
| Authentication | 10 | Portal login/register/reset POSTs; API profile creation/update (`POST /api/fr1/profile`); failed/missing bearer authentication |
| Chat | 12 | `POST /api/fr11/chat` |
| Recommendation generation | 6 | `POST /api/fr4/recommendations/generate` |
| Provider search/read | 30 | FR3 destination search/details; FR6 location search/weather; FR7 flight search; FR8 place and hotel search |
| Payment mutation | 10 | Create intent, process, retry, cancel |
| Hotel mutation | 10 | Prebook and book |

API budgets are checked after Firebase token/profile/role validation and before
the handler's persistence/provider work. Keys use the verified UID, independent
of token rotation, remote IP, and request payload. Portal authentication uses
the signed-session UID when present; anonymous portal authentication and failed
API authentication use `request.remote_addr`. Caller-supplied `X-Forwarded-For`
is not trusted. Deployment behind a proxy needs correctly configured trusted
proxy handling to avoid sharing one anonymous IP budget across visitors.

Exhausted budgets return 429 with only `ok: false`, a generic wait message, and
`retryAfterSeconds`. `Retry-After` contains the rounded-up seconds until the
oldest accepted request expires; `Cache-Control: no-store` prevents caching.
Rejected requests do not extend the window. Ordinary profile/list/snapshot
reads, local compare/details operations, and transaction reconciliation routes
are not rate limited. Payment/hotel idempotency remains unchanged: wait as
directed, reconcile ambiguous operations, and retain the same logical attempt
identity rather than starting another payment/booking.

Tests keep CSRF and rate limiting enabled. Fresh application fixtures isolate
limiter state, `reset()` clears it explicitly, and an injectable clock supports
deterministic expiry/concurrency checks without sleeps. Portal authentication
and backend calls are mocked; socket blocking, cleared provider credentials,
and Firebase fail-fast boundaries remain active.

Limits apply separately in each process and reset on restart. The current
two-worker deployment can therefore allow more than one process's budget.
This is a modest application guard, not a distributed quota or DDoS defense.
Direct client-to-Firebase Authentication calls are governed by Firebase rather
than this limiter. Bearer verification/profile lookup still occurs before API
limiting. Existing Flask cookie sessions remain in use; session migration,
distributed storage, App Check, and background reconciliation are outside this
batch.

## Main API routes

- FR1 `/api/fr1/...`
- FR2 `/api/fr2/preferences`
- FR3 `/api/fr3/destinations/...`, `/api/fr3/favourites`
- FR4 `/api/fr4/recommendations/...`
- FR5 `/api/fr5/itineraries/...`
- FR6 `/api/fr6/locations/search`, `/api/fr6/weather`
- FR7 `/api/fr7/flights/search`
- FR8 `/api/fr8/places/search`, `/api/fr8/hotels/search`, `/api/fr8/hotels/prebook`, `/api/fr8/hotels/book`
- FR9 `/api/fr9/payments/...`, `/api/fr9/checkout/session`, `/api/fr9/orders`, `/api/fr9/webhooks/stripe`

### Transaction reliability

Payment mutations accept a client-retained `paymentAttemptId`. Hotel prebook
and booking mutations accept one parent `hotelBookingAttemptId`; TravelMate
derives separate opaque provider-stage identities for prebook and book.
Firestore atomically claims deterministic operation documents before provider
calls. Repeating an attempt converges on that record instead of creating a new
logical payment/booking. Pending outcomes can be checked through:

- `GET /api/fr9/payments/attempts/<paymentAttemptId>`
- `GET /api/fr8/bookings/attempts/<hotelBookingAttemptId>`

Stripe test-mode calls use the same opaque Stripe idempotency key for an
ambiguous retry. A terminal failed payment requires a new attempt ID. LiteAPI
booking has no guaranteed reconciliation lookup in the current integration;
an ambiguous booking remains pending/verification-required and is not blindly
submitted again. Local hotel confirmations are explicitly marked simulation.

Hosted Checkout orders use server-owned hotel or flight quote records. The
server derives the payable MYR amount, claims an owned order attempt before
calling Stripe, and sends the traveller to Stripe test Checkout. Signed
`checkout.session.*` webhooks update the order; travellers can also reconcile
an open order after closing and reopening the app. Set `STRIPE_WEBHOOK_SECRET`
from Stripe CLI or the Dashboard before treating webhook delivery as verified.
- FR10 `/api/fr10/feedback/...`
- FR11 `/api/fr11/chat`, `/api/fr11/history`
- FR12 `/api/fr12/...`
- FR13 `/api/fr13/...`

## Provider adapters

External API code is under `services/`. Keep API keys only in `backend_api/.env`, never in Flutter/HTML/JavaScript source.
