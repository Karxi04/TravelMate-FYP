# TravelMate V3.2 — Shared Operator Content and TravelMate Reviews

## What changed

This revision links FR12 Tourism Operator content and FR13 Administrator review decisions to the Traveller application through the shared Firebase Firestore database.

### Tourism package flow

1. Tourism Operator creates a tourism package.
2. Package starts as `draft`.
3. Tourism Operator submits the package.
4. Package becomes `pending`.
5. Administrator reviews the package.
6. If approved, `approvalStatus = approved`.
7. Approved and available packages are shown on the Traveller Home page.
8. Traveller can open package details and add the package to a trip.

### Promotional campaign flow

1. Tourism Operator creates a promotional campaign for an approved package.
2. Tourism Operator submits the campaign.
3. `reviewStatus = pending`.
4. Administrator approves or rejects the campaign.
5. Approved campaigns are shown to Travellers only during their valid date period.

### Traveller review flow

1. Traveller selects a destination/place and submits a rating and comment.
2. The record is written to the shared Firestore `feedback` collection.
3. Destination Details reads TravelMate Traveller reviews from Firestore.
4. Administrator can review each record and choose **Keep Visible** or **Remove**.
5. Removed reviews no longer appear in Destination Details.
6. Removed reviews cannot be republished by editing the same record.
7. Visible database reviews are also used as collaborative-rating signals by the standalone Hybrid Recommendation Engine.

No Google/SerpApi review text is used as the TravelMate review list in this revision. Destination provider data may still supply place information, but FR10 review cards come from the TravelMate database.

## Traveller Home additions

- Featured tourism packages
- Current promotions
- Tourism package details
- Promotion details
- Add approved package to trip

## Operator additions

Tourism packages now support:
- title
- destination
- price
- duration
- maximum travellers
- validity period
- meeting point
- image URL
- description
- highlights
- inclusions
- exclusions
- availability

Promotional campaigns now support:
- campaign title
- approved related package
- start/end dates
- percentage or fixed discount
- discount value
- promo code
- banner image URL
- description
- terms and conditions

## Administrator additions

Package review shows fuller package information before approval.
Campaign review shows offer and terms information.
Traveller Review moderation shows destination, Traveller, rating, comment, submission time, visibility status and moderation status.

## One-time Firebase requirement

V3.2 adds the Flutter Cloud Firestore plugin and changes `firebase/firestore.rules` so an authenticated Traveller can:
- read approved tourism packages;
- read approved promotional campaigns;
- read visible TravelMate reviews;
- create/update/delete their own review.

Operator and Administrator writes remain backend-controlled through Firebase Admin SDK.

Deploy the rules once from the project root after Firebase CLI setup. Select your existing TravelMate Firebase project when `firebase use --add` asks:

```powershell
firebase use --add
firebase deploy --only firestore:rules
```

## Running Traveller without local Flask

The Traveller app can still use standalone mode. It reads the cross-role shared content directly from Firebase Firestore, so the tablet does not need `adb reverse` or a locally running Flask backend for packages, promotions and reviews.

The Operator and Administrator websites still use the Flask backend. For final use without manually starting the backend on the development computer, deploy the backend to a public HTTPS host and set each website's `BACKEND_URL` to that hosted URL.
