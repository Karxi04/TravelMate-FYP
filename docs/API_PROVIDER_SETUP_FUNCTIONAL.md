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

### Gemini
`GEMINI_API_KEY` enables live TravelMate assistant responses. Without it, `FALLBACK_MODE=true` keeps the assistant usable through a deterministic local fallback.

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
