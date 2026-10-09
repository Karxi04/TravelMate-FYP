# External API Setup

Only put secret provider keys in `backend_api/.env`.

## A. SerpApi — Destination Search + Flight Search

Used by:
- FR3 Destination Search and Information
- FR7 Flight Search
- FR4 recommendation data cache support

Create a SerpApi account and copy your API key.

```env
SERPAPI_KEY=YOUR_KEY
```

Backend adapters:
- Google Maps engine: `services/serpapi_service.py -> maps_search()`
- Google Flights engine: `services/serpapi_service.py -> flights_search()`

If `FALLBACK_MODE=true`, destination/flight endpoints can still show local sample results while you are setting up the key.

## B. Open-Meteo — Weather

Used by FR6.

No key is required for the normal non-commercial public API. The backend uses:
- Open-Meteo Geocoding API to convert a place name into coordinates
- Open-Meteo Forecast API for current + 7-day weather

No `.env` value is required.

## C. LiteAPI / Nuitee Sandbox — Hotels

Used by FR8.

Create a LiteAPI/Nuitee account and obtain a sandbox API key.

```env
LITEAPI_KEY=YOUR_SANDBOX_KEY
```

Implemented flow:
1. Place search
2. Hotel rates search
3. Prebook selected `offerId`
4. Book endpoint adapter
5. Store booking reference in Firestore

Car rental search/select is provided by the bundled local TravelMate adapter and does not require an external API key.

The mobile flow supports search, prebook and booking. Use a sandbox provider
configuration for optional manual provider testing. Missing provider access
with fallback enabled produces an explicitly simulated Demo booking; an
ambiguous provider timeout is pending for verification, never blindly rebooked.

## D. Stripe Sandbox — Payment Workflow

Used by FR9.

Create or open a Stripe sandbox/test environment and copy the sandbox secret key.

```env
STRIPE_SECRET_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
# Local desktop defaults; for a physical phone replace 127.0.0.1 with the
# computer's reachable LAN address and keep the /api/fr9/checkout/return path.
STRIPE_CHECKOUT_SUCCESS_URL=http://127.0.0.1:5000/api/fr9/checkout/return/success?session_id={CHECKOUT_SESSION_ID}
STRIPE_CHECKOUT_CANCEL_URL=http://127.0.0.1:5000/api/fr9/checkout/return/cancel?session_id={CHECKOUT_SESSION_ID}
```

The hosted mobile Checkout flow calls:

`POST /api/fr9/checkout/session`

The server accepts only an owned, complete hotel or flight quote and derives
the amount and currency from that stored quote. It claims a durable order
attempt before creating one Stripe test Checkout Session. The mobile app opens
the returned hosted URL and reconciles pending orders on the next launch.

The legacy payment workflow remains available at:

`POST /api/fr9/payments/process`

Use a stable `paymentAttemptId`. The backend uses Stripe test mode or explicit
local simulation, preserves one authoritative intent per operation, and stores
the normalized result. The screen labels simulated versus sandbox payments;
neither charges real money. Pending attempts are reconciled rather than
replaced after an ambiguous timeout. Cancellation is not a Stripe refund.

Do not use a live Stripe secret key for the FYP demonstration.

## E. Gemini API — Chatbot

Used by FR11.

Create a Gemini API key in Google AI Studio.

```env
GEMINI_API_KEY=YOUR_KEY
GEMINI_MODEL=gemini-3.6-flash
```

The backend uses the Google GenAI Python SDK and the Gemini Interactions API. The model name is configurable in `.env` so you can change it later without editing code.

Each Traveller message/reply is stored in `chat_messages` in Firestore.
If a configured provider fails and fallback is enabled, the reply is labelled
as the local TravelMate assistant rather than as a live Gemini response.

## Provider status check

After the backend starts, request the following endpoint with an Administrator Firebase token:

`http://127.0.0.1:5000/api/config-status`

It returns only the safe `paymentMode` and `hotelMode` capability states without exposing provider credentials or internal diagnostics.
