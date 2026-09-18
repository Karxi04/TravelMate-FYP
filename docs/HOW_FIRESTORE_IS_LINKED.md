# How TravelMate Is Linked to Firestore

The project deliberately uses one database path for all three frontends:

```text
Traveller Flutter app -----\
Operator website ----------- > Firebase ID token -> Flask REST backend -> Firebase Admin SDK -> Firestore
Admin website -------------/
```

The mobile app does **not** write directly to Firestore. The websites also do **not** write directly to Firestore. This keeps role checks in one backend.

## 1. Firebase Authentication creates the user identity

Traveller:
- `traveller_mobile/lib/services/auth_service.dart`
- Firebase Flutter SDK creates/signs in the account.

Operator/Admin websites:
- `firebase_auth_rest.py`
- Firebase Identity Toolkit REST endpoints return an ID token.

## 2. The frontend sends the Firebase ID token to Flask

Traveller:
- `traveller_mobile/lib/services/api_service.dart`
- `_headers()` obtains `currentUser.getIdToken()` and sends:

```http
Authorization: Bearer <firebase-id-token>
```

Websites:
- `api_client.py` reads the ID token from the Flask session and sends the same Authorization header to the backend.

## 3. Flask verifies the token and role

File:
- `backend_api/auth_utils.py`

`auth.verify_id_token()` verifies the Firebase ID token. The backend then reads `users/{uid}` and checks the role/status before allowing a protected function.

Examples:
- Traveller-only: `@auth_required(["traveller"])`
- Operator-only: `@auth_required(["operator"])`
- Admin-only: `@auth_required(["admin"])`

## 4. Flask uses Firebase Admin SDK to read/write Firestore

File:
- `backend_api/firebase_service.py`

The Admin SDK reads your service-account JSON and creates the Firestore client.

Example pattern:

```python
db = get_db()
ref = db.collection("travel_preferences").document(g.uid)
ref.set(data, merge=True)
```

## 5. How to verify it manually

After setup:

1. Start `backend_api`.
2. Register a Traveller.
3. Open Firebase Console -> Firestore Database.
4. You should see `users/{uid}`.
5. Save Travel Preferences.
6. You should see `travel_preferences/{uid}`.
7. Save a favourite destination.
8. You should see a document under `favourites`.

If Authentication works but Firestore does not update, check:
- `backend_api/serviceAccountKey.json` exists
- `FIREBASE_SERVICE_ACCOUNT=serviceAccountKey.json`
- backend terminal has no permission/credential error
- Firestore Database has been created in the Firebase project
