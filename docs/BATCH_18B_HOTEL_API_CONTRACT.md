# Batch 18B Hotel API contract

This contract is the backend foundation for the next Flutter integration. It
does not enable real supplier booking.

## Search occupancy

`POST /api/fr8/hotels/search` accepts one occupancy object per room:

```json
{
  "destination": "Penang",
  "checkin": "2026-11-10",
  "checkout": "2026-11-12",
  "roomQuantity": 2,
  "adults": 4,
  "children": 2,
  "occupancies": [
    {"adults": 2, "children": [8]},
    {"adults": 2, "children": [12]}
  ]
}
```

`children` inside each room is the list of actual child ages, not a count.
The optional top-level `adults` and `children` totals must match the room
allocations. The backend never invents or distributes guests. A legacy
single-room adults-only request remains valid. A multi-room request without
`occupancies` returns HTTP 400 with `status: "invalid_occupancy"`.

Each returned offer includes a server-owned `quoteId` and `quoteExpiresAt`.
`HOTEL_QUOTE_TTL_SECONDS` controls the application safety window and is bounded
to 60–3600 seconds (default 900). This window is not a provider rate guarantee.
The accepted-prebook window uses the separately configurable, equally bounded
`HOTEL_PREBOOK_TTL_SECONDS` (default 900).

## Prebook and repricing

`POST /api/fr8/hotels/prebook` requires the owned `quoteId`, `offerId`, and a
stable `hotelBookingAttemptId`. Expired quotes return HTTP 409 with
`status: "quote_expired"`.

If provider price or terms change, the existing HTTP 409
`status: "reprice_required"` response includes `quoteVersion`. Re-submit the
same attempt with `acceptedQuoteVersion` only after the traveller explicitly
accepts the displayed change.

Successful acceptance returns:

```json
{
  "ok": true,
  "acceptedPrebook": {
    "id": "server-owned-reference",
    "status": "accepted",
    "expiresAt": "server timestamp",
    "amount": 425.0,
    "currency": "MYR",
    "transactionMode": "local_demo or provider_sandbox",
    "supplierBookingStatus": "not_created",
    "checkoutEligible": true
  }
}
```

The referenced server record preserves the accepted hotel, offer, dates,
room-by-room occupancy, total, currency, tax disclosure, cancellation terms,
and provider/prebook references. Flutter must not calculate the payable total.

## Stripe Hotel Checkout

`POST /api/fr9/checkout/session` now requires:

```json
{
  "orderAttemptId": "stable-client-attempt-id",
  "quoteType": "hotel",
  "quoteId": "search-quote-id",
  "offerId": "provider-offer-id",
  "acceptedPrebookSnapshotId": "server-owned-reference"
}
```

The backend uses only the owned, succeeded, unexpired accepted-prebook snapshot
for Stripe amount and currency. Client totals are ignored. Missing, legacy,
expired, foreign, currency-invalid, or internally mismatched snapshots fail
closed with HTTP 409. Reusing the same attempt with the same snapshot remains
idempotent; conflicting reuse is rejected.

The existing `/api/fr8/hotels/book` response remains an explicit local-demo or
guarded sandbox boundary. `supplierBookingStatus: "not_created"` means neither
prebook acceptance nor Stripe test payment proves a supplier reservation.
