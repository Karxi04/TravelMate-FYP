# How to Test the Real MVP

## Before testing

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
8. Flight/Hotel -> local fallback can localnstrate UI before keys.
9. Feedback -> confirm `feedback`.
10. Operator creates package -> confirm `tourism_packages`.
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

Check `GET /api/config-status` after every change.

## When you are ready for final live-provider testing

Set:

```env
FALLBACK_MODE=false
```

Then an external-provider failure is shown as an error instead of local fallback data.
