# TravelMate Shared Flask REST API

All three frontends use this backend:

- Traveller Flutter mobile app
- Tourism Operator website
- Administrator website

The backend verifies Firebase ID tokens and uses the Firebase Admin SDK to read/write Firestore.

## Run

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python app.py
```

Health checks:

- `GET /api/health`
- `GET /api/config-status`

## Main API routes

- FR1 `/api/fr1/...`
- FR2 `/api/fr2/preferences`
- FR3 `/api/fr3/destinations/...`, `/api/fr3/favourites`
- FR4 `/api/fr4/recommendations/...`
- FR5 `/api/fr5/itineraries/...`
- FR6 `/api/fr6/locations/search`, `/api/fr6/weather`
- FR7 `/api/fr7/flights/search`
- FR8 `/api/fr8/places/search`, `/api/fr8/hotels/search`, `/api/fr8/hotels/prebook`, `/api/fr8/hotels/book`
- FR9 `/api/fr9/payments/...`
- FR10 `/api/fr10/feedback/...`
- FR11 `/api/fr11/chat`, `/api/fr11/history`
- FR12 `/api/fr12/...`
- FR13 `/api/fr13/...`

## Provider adapters

External API code is under `services/`. Keep API keys only in `backend_api/.env`, never in Flutter/HTML/JavaScript source.
