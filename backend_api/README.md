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

`request_rate_limit.py` applies Firestore-backed fixed-window budgets to the
backend. Each decision runs in a Firestore transaction, so Gunicorn workers and
Cloud Run instances share the same counter. A document ID is a SHA-256 digest
of the category and verified UID or connection-peer identity; no raw UID or IP
is stored. Related endpoints share a category budget, so changing resource or
attempt IDs does not evade a limit.

| Category | Default requests per 60-second window | Operations |
| --- | ---: | --- |
| Authentication | 10 | Portal login/register/reset POSTs; API profile creation/update (`POST /api/fr1/profile`); failed/missing bearer authentication |
| Chat | 12 | `POST /api/fr11/chat` |
| Recommendation generation | 6 | `POST /api/fr4/recommendations/generate` |
| Provider search/read | 30 | FR3 destination provider reads; FR6 weather; FR7 search/compare/details; FR8 place/hotel search/compare |
| Payment mutation | 10 | Stripe Checkout, create intent, process, retry, cancel; reconciliation remains available for recovery |
| Hotel mutation | 10 | Prebook and book |

API budgets are checked after Firebase token/profile/role validation and before
the handler's persistence/provider work. Authenticated keys use the verified
UID, independent of token rotation, remote IP, and request payload. Failed or
missing bearer authentication uses `request.remote_addr`; caller-supplied
`X-Forwarded-For` is deliberately ignored. Stripe's signed webhook, checkout
return page, and health check are exempt so rate-limit storage cannot interrupt
payment delivery, order recovery, or Cloud Run probing.

Exhausted budgets return 429 with only `ok: false`, a generic wait message, and
`retryAfterSeconds`. `Retry-After` contains seconds until the current fixed
window ends; `Cache-Control: no-store` prevents caching. Rejected requests do
not extend the window. When Firestore is unavailable, protected routes fail
closed with 503, `Retry-After: 60`, and no handler/provider side effect.
Payment/hotel idempotency remains unchanged: wait as directed, reconcile
ambiguous operations, and retain the same logical attempt identity rather than
starting another payment/booking.

Set `RATE_LIMIT_*_PER_WINDOW`, `RATE_LIMIT_WINDOW_SECONDS`, and
`RATE_LIMIT_RETENTION_SECONDS` in Cloud Run. Configure a Firestore TTL policy
for collection group `rate_limit_windows`, field `expiresAt`; TTL cleanup is
asynchronous, so the one-day default is a retention target rather than an exact
deletion deadline. An allowed request normally costs one Firestore transaction
read and one write; a rejected request normally costs one read, with transaction
retries adding operations during contention.

Portal login/register/reset and Flutter login are direct Firebase Authentication
requests, so Flask cannot rate-limit them. Keep Firebase abuse protection and
quotas configured separately. The portal's existing local limiter remains a
best-effort browser guard only. This API limiter is not a DDoS/WAF substitute;
consider Cloud Armor or an equivalent edge control if public traffic grows.

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

## Explicit lower-cost travel comparisons

Budget discovery retains its explicit confirmation, owner/revision checks, hourly
quota and two-provider-call flight / one-call hotel limits. Opening the screen
only reads saved quotes; it does not purchase a provider search.

Flight comparison defaults to `cabinComparison=same_cabin`. With
`cabinComparison=include_lower`, the user chooses a `comparisonCabin` (1 Economy,
2 Premium Economy, 3 Business, 4 First). The server establishes the original
cabin from saved evidence and permits only that cabin or a lower one. Missing
or conflicting cabin evidence does not imply Economy. A search compares one
chosen cabin at a time, preserving the two-call limit for a complete return fare;
the user can separately choose another eligible cabin. Search-cache/intent
identity includes the comparison so changing mode cannot reuse an incompatible
search. Quote ownership, route, dates, passengers, complete MYR price and expiry
are revalidated at preview and apply; client prices are never authoritative.

Feasible flight schedule adjustments are grouped separately and shown in the
replacement preview. Infeasible quotes remain read-only with their flight times,
affected days/visits and conflict reason. A replacement never silently drops
activities or modifies protected arrangements. The existing itinerary CAS/history
write updates flight selection, schedule and budget together.

Hotel eligibility reports sanitized reason codes before the provider boundary:
missing/expired original quote, inconsistent stay total/currency/charges, dates or
location, occupancy, protected arrangement and unavailable storage. Consistent
validated evidence on an owned details-only selection remains supported. Rates
return candidate/valid/rejected counts and rejection categories; a completed
search with no cheaper comparable rates is different from a blocked search or
provider failure. Recovery opens Hotels with the same trip, dates and known room
occupancy. Quote selection is still neither payment nor supplier reservation.

Home/For You additions reuse the existing destination/day picker. Only personal
editable trips qualify; package/ownership/day checks also run on the Backend.
An addition that cannot remain on the requested day is rejected without a write.
Trips search filters the already-owned in-memory list, preserving status/sorting
and making no new Firestore query. Recommendation methodology and retained
GeoNames/Open-Meteo attribution are accessible under Profile's About area;
recommendation score details and review provenance remain intact.

## Local FYP recommendation evidence

`RECOMMENDATION_EVIDENCE_MODE=genuine` is the default and retains genuine-only
peer evidence and genuine recommendation snapshots. An owner-approved local
Viva rollout can explicitly select `fyp_evaluation`. Startup rejects that value
unless the existing restricted `LOCAL_LAN_DEMO` / `TRUSTED_LAN_CIDR` configuration
is active. Authenticated Traveller requests must also carry the existing
`X-TravelMate-Review-Context: fyp-v1` header. Query/body parameters cannot switch
the configured evidence mode. Do not change a running service without approval.

Evaluation uses the normal Home/For You routes, the signed-in Traveller's saved
questionnaire, existing canonical destination records and the existing approved
Penang sample reviews with their effective moderation decisions. Simulated
reviewer profiles remain explicitly simulated. The existing 60/30/10 formula,
similarity threshold and confidence calculation are unchanged. Approved local
evaluation-review aggregates are the only evaluation popularity source. Missing
local evidence uses the neutral 50 prior and a Not rated yet badge; provider
ratings never fill an evaluation rating or review count. Collaborative uses
similarity-weighted peer ratings and confidence, while popularity uses the
unweighted approved destination mean/count. Provider reviews never become peers.

The original 104 Penang definitions remain unchanged. A source-controlled,
explicitly synthetic coverage supplement adds six contributions per canonical
Penang attraction (72 total) and six associated simulated preference profiles.
Each new contribution passes the existing FR10 rating/sentiment screening; no
pending row is forced approved. Existing local staging overlays and Administrator
moderation apply, and the authorized Local Reviews list/summary includes both
sources. No Firebase import or genuine projection is created by this supplement.

The nationwide refinement adds 688 contributions in six regional JSON files under
`services/data/evaluation_reviews`, with eight explicitly simulated profile groups.
The curated combined set covers 100 attractions across all 16 states/territories;
it does not bulk-promote the 400 identity records. New candidate records must have
an existing canonical name, coordinates and pass the existing geographic/tourism
checks. Unknown hours/admission remain unknown. The offline source still has five
original Penang and two older regional identities without exact coordinates;
these remain unchanged and are not newly promoted to pinned Trip stops.
The new rows initially screen as 661 approved and 27 pending (seven or eight
approved per newly covered attraction). Pending/hidden/removed rows do not score.
Existing 104 Penang, 72 Penang supplement and 45 regional definitions are unchanged.
The combined initial source totals are 909 contributions, 874 approved, before
any effective Administrator overlay. These are evaluation fixtures, not customers.

Normal evaluation generation now loads the resolved requested state/city/country
scope instead of always loading Penang. It filters candidate identities and review
contributions to the same scope, deduplicates review IDs, and only accesses the
original private Penang dataset for Penang or Malaysia-wide requests. No live
provider search, genuine snapshot write or profile mutation is introduced.
Valid localities without curated evidence can use the normal verified cache
fallback or return no results; they do not borrow another state's reviews.
The bounded moderation-source cache covers the curated set and excludes empty
lookups, preserving existing review revisions while browsing the larger dataset.

Evaluation generations and More like this / Not for me learning are owner-scoped
in process memory: up to 64 generations and 64 learning profiles, each expiring
after one hour or process restart. They never write genuine feedback, preferences,
public projections or recommendation snapshots. This local mode expects the
existing single Backend worker; it is not a distributed production history store.
GET reads an existing evaluation generation; the normal explicit regeneration
action recalculates using current preferences and approvals. Missing data fails
closed instead of falling back to genuine results or unmoderated definitions.
Evaluation discovery uses existing catalogue and saved cache data, without live
provider searches. It can therefore have limited destination coverage.

The normal destination View and confirmed Add to Trip actions remain available;
only destination/activity facts enter the existing itinerary write contract,
not evaluation scores or review identities. Questionnaire and Trip changes still
require their normal user actions. The separate simulation engine and its tests
remain internal, without a science-icon navigation entry in the ordinary UI.
The Recommendation data sources action and score explanation disclose sample
community evidence. Ordinary evaluation badges use `3.5 · 16 Reviews` with the
approved local mean/count only; provenance remains available in the details.

### Persistent local Administrator moderation

Regional/nationwide source definitions are immutable. Without a configured,
initialized local overlay they remain read-only. The owner-controlled Windows
setup script defaults to a plan without changing files or runtime configuration:

```powershell
./scripts/prepare_review_staging.ps1
# Only after separate owner approval:
./scripts/prepare_review_staging.ps1 -Apply
```

Its default dedicated database is
`D:\workspace\TravelMate\local_review_moderation\review-overlay.sqlite3`.
The script rejects unrelated files/databases and reparse points, and verifies
protected directory/file ACLs granting only the current Windows user and SYSTEM.
The Backend must run under that same user. A different service identity requires
a separately reviewed permission change. Do not move this file into tracked source.

After separate rollout approval, set `FYP_REVIEW_STAGING_PATH` to that absolute
path in the existing local Backend environment and reload only the verified
Backend. The script itself does not edit `.env` or restart anything. Updating the
Administrator portal and Traveller APK requires their own approved rollout.
GETs and moderation requests never create or repair the database. A missing,
corrupt or inaccessible configured overlay fails closed: affected review data is
withheld, generation returns 503, and no source defaults are silently republished.

The overlay accepts only moderation fields on existing synthetic records. It
cannot change ratings, comments, author/provenance or genuine Firebase feedback.
Original private Penang reviews retain their existing private Firestore moderation
adapter; genuine reviews retain their owner/public-projection protections. This
local database covers the source-controlled Penang supplement and regional and
nationwide contributions, with no Firebase import.

Pending reviews allow Approve/Reject/Hide. Approved reviews allow Hide or explicit
Revoke approval. Hidden/rejected reviews allow Restore and approve. Revoke and
restore require a note and current revision; every mutation retains its actor,
timestamp and decision history. SQLite immediate transactions and existing
Firebase compare-and-set adapters reject stale or concurrent decisions. The
Administrator list has source/status filters and 50-row pagination; unavailable
local storage is reported rather than represented as an empty successful source.

New generations use the effective approved rows for both the independent peer
calculation and the unweighted popularity aggregate. Older evaluation generations
are immutable and request explicit regeneration when the local overlay hash or an
in-process private moderation revision changes. The local single-worker scope
still applies: external changes to private Firestore moderation are read on the
next explicit generation, not polled on every saved-generation GET.

For rollback, preserve the database and its ACLs. Revert code/config only through
an approved service reload; never delete decisions to roll back presentation.
Removing the overlay setting restores immutable fixture defaults and therefore
must not be used as a routine moderation reset. Genuine mode and genuine records
are independent of this local evaluation overlay.

For an approved rollout, retain the existing genuine configuration as rollback,
select `fyp_evaluation`, then use the controlled Backend reload procedure. No
database migration or data rewrite is needed. To restore genuine mode, restore
`genuine` and reload only with approval; original genuine histories are retained.

### Lower-cost supplier search evidence

Explicit `/api/fr5/itineraries/<id>/lower-cost-alternatives/discover` keeps its
existing confirmation, revision, quota and provider limits (two flight calls or
one hotel rates call). Its `search` result includes the durable `searchId`,
`status`, `reused`, `providerReached`, `requestsAttempted`, returned
`candidateCount`, complete `validQuoteCount`, and provider rejection counts.
Flight counts describe the final comparison stage; `outboundCandidateCount` and
`returnCandidateCount` distinguish outbound options from the one bounded return
branch. Uncompleted/uncompared fares are identified, never priced as completed
round trips. Quote expiry is preserved.

The existing alternatives POST accepts optional `searchIds: {flight: id,
hotel: id}`. It reads these exact saved searches and resolves their owned quote
references before the capped historical scan. Each search must match the owner,
trip, current revision, category and selected cabin comparison. No price from
the client is accepted. The response's `searches` map retains provider evidence
and adds `searchStatus`, `cheaperCandidateCount`, `timingConflictCount`,
`comparisonRejectionCounts` and `reasonCode`. Counts distinguish provider quote
rejections from later comparison failures. A cheaper timing-conflicted candidate
is counted separately from an applicable replacement.

`not_started` means this view has no confirmed submitted search; it does not
claim the account has never searched. Completed searches distinguish no offers,
rejected quotes, expired quotes, non-cheaper comparable offers, impossible
timing and previewable savings. Reused search evidence is labelled. A new
explicit intent can refresh expired cached evidence, while replaying the old
intent never repeats its provider requests. Normal expiry and quota protections
still apply. Preview, Cancel and confirmed CAS/history persistence use the
existing contracts; no schema migration or owner-record rewrite is required.
