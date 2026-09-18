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

The mobile MVP currently exposes search and prebook directly. The `/api/fr8/hotels/book` backend endpoint is ready for a sandbox booking payload once you add the guest/payment fields required by your LiteAPI account/test flow.

## D. Stripe Sandbox — Payment Workflow

Used by FR9.

Create or open a Stripe sandbox/test environment and copy the sandbox secret key.

```env
STRIPE_SECRET_KEY=sk_test_...
```

For a simple FYP localnstration the mobile screen calls:

`POST /api/fr9/payments/process-success`

The backend uses Stripe's sandbox/test PaymentMethod and writes the resulting PaymentIntent status/reference into Firestore.

Do not use a live Stripe secret key for this assignment local.

## E. Gemini API — Chatbot

Used by FR11.

Create a Gemini API key in Google AI Studio.

```env
GEMINI_API_KEY=YOUR_KEY
GEMINI_MODEL=gemini-3.6-flash
```

The backend uses the Google GenAI Python SDK and the Gemini Interactions API. The model name is configurable in `.env` so you can change it later without editing code.

Each Traveller message/reply is stored in `chat_messages` in Firestore.

## Provider status check

After the backend starts, visit:

`http://127.0.0.1:5000/api/config-status`

It shows `true/false` for each configured provider without exposing your secret keys.
