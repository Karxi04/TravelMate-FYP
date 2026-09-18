# TravelMate Firestore Data Model

The backend creates collections automatically when the first record is written.

## Collections

### `users/{uid}`
Shared account profile for Traveller, Tourism Operator and Administrator.

Typical fields:
- `uid`
- `email`
- `name`
- `phoneNo`
- `role`: `traveller`, `operator`, `admin`
- `status`: `active`, `deactivated`
- Operator-only: `companyName`, `businessContact`, `registrationNo`, `verificationStatus`
- `createdAt`, `updatedAt`

### `travel_preferences/{uid}`
One preference profile per Traveller.

Fields:
- `travellerId`
- `travelPersonality`
- `travelType`
- `interests[]`
- `budgetRange`
- `travelPace`
- `travelPurpose`
- `updatedAt`

### `destination_cache/{destinationId}`
Destination data returned by SerpApi and cached so the simple recommendation engine has data to rank.

### `favourites/{uid_destinationId}`
Saved destinations.

### `recommendations/{uid}`
Latest generated recommendation list for a Traveller.

### `itineraries/{itineraryId}`
Fields include:
- `travellerId`
- `title`
- `destinationArea`
- `budgetLimit`
- `activities[]`
- optional `flightCost`, `hotelCost`, `transportCost`
- `status`
- timestamps

### `hotel_bookings/{bookingDocId}`
Stores hotel sandbox booking references and provider results.

### `payment_records/{stripePaymentIntentId}`
Stripe sandbox payment records.

### `feedback/{feedbackId}`
Traveller destination feedback and moderation status.

### `chat_messages/{messageId}`
Traveller question, Gemini reply and timestamp.

### `tourism_packages/{packageId}`
Operator package records and approval status.

### `promotional_campaigns/{campaignId}`
Operator campaign records and administrator review status.

## Why clients do not access Firestore directly

The supplied `firebase/firestore.rules` denies direct client reads/writes. The Flutter app and two websites authenticate with Firebase Authentication, then send the Firebase ID token to the Flask backend. The backend verifies the token and uses the Firebase Admin SDK to access Firestore.

This gives one place to enforce role checks and keeps privileged service credentials out of the app and websites.
