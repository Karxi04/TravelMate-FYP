# API Provider Setup for the Functional MVP

Keep all secret provider credentials in `backend_api/.env`.

```env
PORT=5000
FIREBASE_SERVICE_ACCOUNT=serviceAccountKey.json
FALLBACK_MODE=true
SERPAPI_KEY=
LITEAPI_KEY=
STRIPE_SECRET_KEY=
GEMINI_API_KEY=
GEMINI_MODEL=gemini-3.7-flash
```

## Data-provider behavior

### SerpApi
Used for Google Maps destination data and Google Flights. The same `SERPAPI_KEY` is used for both.

### Open-Meteo
No key is required by this project. It is used for geocoding and weather forecasts.

### LiteAPI / Nuitée
`LITEAPI_KEY` enables live hotel rate, prebook and booking sandbox calls.
Hotel mutation calls are bounded below the Traveller app's 90-second mutation
window. The current LiteAPI integration does not expose a guaranteed booking
idempotency/status lookup, so an ambiguous timeout is retained as pending for
verification rather than automatically resubmitted. Fallback records are
labelled Demo booking and Simulated confirmation.

### Gemini
`GEMINI_API_KEY` enables live TravelMate assistant responses. Without it, `FALLBACK_MODE=true` keeps the assistant usable through a deterministic local fallback.

Stripe test mutations use a 75-second SDK timeout, disable blind SDK network
retries, and pass a stable opaque idempotency key. The mobile client allows 90
seconds for payment/hotel mutations, 70 seconds for long provider reads, 35
seconds for ordinary writes, and 25 seconds for ordinary reads.

### Stripe
The existing FR9 sandbox integration is preserved. Use only a Stripe test secret key.

## Recommended test sequence

1. Keep `FALLBACK_MODE=true`.
2. Sign in as an Administrator and confirm `/api/config-status` reports only the expected payment/hotel capability modes.
3. Test Open-Meteo.
4. Add SerpApi and confirm Explore + Flights show `LIVE` source badges.
5. Add Gemini and confirm Assistant messages show `Gemini live response`.
6. Add LiteAPI and confirm Hotels show `LIVE LITEAPI / NUITÉE OFFERS`.
7. Test Stripe sandbox.
8. Only set `FALLBACK_MODE=false` when you intentionally want provider failures to surface instead of falling back.
