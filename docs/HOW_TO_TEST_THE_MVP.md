# How to Test the Real MVP

## Before the manual demonstration

For isolated automated checks, use `backend_api/requirements-test.txt` and
`python -m pytest`; no live Firebase/provider setup is required. See
`FINAL_DEMO_READINESS.md` for the current integrated journey and build matrix.

1. Complete Firebase setup.
2. Put the service account JSON in `backend_api/`.
3. Create `.env` files from each `.env.example`.
4. Start backend, Operator website and Admin website.
5. Configure FlutterFire and run the Traveller app.

## First test with FALLBACK_MODE=true

You can test the application flow before every external provider key is ready.

Recommended order:

1. Register Traveller -> confirm `users` document.
2. Save preference -> confirm `travel_preferences`.
3. Destination Search -> local fallback works if SerpApi not configured.
4. Save Favourite -> confirm `favourites`.
5. Generate Recommendation -> verify recommendation screen.
6. Create Itinerary -> confirm `itineraries`.
7. Weather -> Open-Meteo is live.
8. Flight/Hotel -> labelled local fallback can demonstrate the flow before keys; hotel/payment confirmations are simulated.
9. Feedback -> confirm `feedback`.
10. Administrator approves the operator account (`verificationStatus: approved` or `verified`), then operator creates package -> confirm `tourism_packages`.
11. Operator submits package -> status becomes `pending`.
12. Admin approves it -> status becomes `approved`.
13. Operator creates/submits campaign.
14. Admin reviews campaign.
15. Admin filters reports by criteria and exports CSV/PDF.

## Then enable each real provider

Add one key at a time and restart backend:

- `SERPAPI_KEY` -> test destination + flight screens
- `LITEAPI_KEY` -> test hotel search + prebook
- Car rental search uses the bundled local adapter and can be attached to an itinerary without external keys.
- `STRIPE_SECRET_KEY` -> test sandbox payment
- `GEMINI_API_KEY` -> test chatbot

With an Administrator Firebase token, check `GET /api/config-status` after every provider-configuration change.

## When you are ready for final live-provider testing

Set:

```env
FALLBACK_MODE=false
```

Then an external-provider failure is shown as an error instead of local fallback data.
