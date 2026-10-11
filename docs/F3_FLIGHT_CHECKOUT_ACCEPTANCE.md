# F3 flight quote eligibility and shared test Checkout

Baseline: `batch-p1-shared-stripe-test-checkout`, `1cd9a96`. Implementation branch: `batch-f3-flight-checkout-acceptance`. Hotel acceptance is preserved; it is not rerun.

## Price evidence checked on 2026-10-10

- [SerpApi Google Flights API](https://serpapi.com/google-flights-api): `type=2` is one-way; `type=1` is round trip. `adults` defaults to one and children/infants default to zero. The result-level `price` is the ticket price in the selected currency. The segment array describes that ticket's flights. `departure_token` selects an outbound and retrieves compatible return candidates; it is not a reservation.
- [Provider-authored scraper examples](https://github.com/serpapi/google-flights-scraper): preserve the original route, dates and passenger context when requesting returns. One-way requests omit `return_date`; optional fields may be absent. Neither this example nor the result schema proves a multi-adult price is a party total.
- [Google Flights official guidance](https://support.google.com/travel/answer/2475306?hl=en): the displayed price covers the flights on the ticket; air transport prices include VAT/GST and airport taxes. Baggage, card and other airline/agency charges may be additional. F3 discloses these unverified extras; it does not promise an all-in airline purchase price.
- [SerpApi booking-options schema](https://serpapi.com/google-flights-booking-options): `together`, `departing`, `returning` and `separate_tickets` describe different booking arrangements. The current return-candidate flow has no separately established, bound combined fare. F3 does not call a booking action or infer such a fare from a return date/token.
- [SerpApi Account API](https://serpapi.com/account-api): the allowance check is free and consumes no search quota. Initial allowance was 244 searches; F3 permits at most one genuine single-adult one-way query.

Single-adult equality is a mathematical inference: a per-adult amount equals a whole-party amount when that party contains exactly one adult and nobody else. It does not prove currency, freshness, route, taxes, ticket validity or airline availability. Those properties have separate checks and disclosures.

## Eligibility matrix

| Search/selection | Adults | Demo Checkout | Budget |
|---|---:|---|---|
| Complete one-way, genuine MYR provider ticket, future departure, evidence and original time valid, owned and reconfirmed | 1, no children/infants | Supported | Ticket reference counted once |
| One-way, party price scope ambiguous | 2+ | Blocked | Indicative price excluded |
| Outbound round-trip candidate, return missing | Any | Blocked | Excluded; return selection remains available |
| Complete compatible round-trip selection, combined fare scope unresolved | Any | Blocked | Both legs retained; no outbound/return addition |
| Missing/contradictory price evidence, foreign quote, altered amount/route/date/passengers | Any | Blocked | No definitive unsupported total |
| Non-MYR, expired quote, unavailable original provider time, same-day timezone unresolved | Any | Blocked | Planning information remains available |
| Sample/standalone fixture | Any | Blocked in shared Checkout | Existing explicitly labelled local planning only |

Unresolved questions: does `best_flights[].price` for multiple adults mean one adult's ticket or the whole party, and does the selected return-candidate price include the selected outbound (including separate-ticket cases)? F3 makes no multiplication/addition assumption and does not contact the provider.

## Backend contract

The adapter derives `priceEvidence` only from matching provider response parameters, the documented one-way result type/ticket-price field, a single adult/no other passengers, currency and original provider search metadata. Generic normalization no longer declares requested-adult prices verified. The durable quote retains the original provider retrieval time and expires one hour from it, including cached responses.

`POST /api/fr9/checkout/flight-review` loads the owned durable quote and returns the allowlisted review snapshot and fingerprint. Shared `POST /api/fr9/checkout/session` requires explicit confirmation of that current fingerprint. A material change requires another review; an existing attempt cannot be rebound to a different snapshot. Client amounts/segments/currency/passengers cannot override the server quote.

Flight orders remain in `checkout_orders`. Their snapshots include every segment, dates, one-adult party, MYR ticket amount/basis, original retrieval/expiry, evidence and demo-only/no-ticket flags. No PNR, airline reservation, hold, ticket or supplier-payment operation is implemented or invoked. Signed webhook receipts are bound to the saved Checkout Session and recorded for flight verification; paid status cannot be downgraded by failure/expiry. Reconciliation retains the same shared architecture.

Flight selection only changes flight fields and its single budget component. Unknown party/round-trip prices remain planning references, excluded from definitive totals. Hotel selections/costs, manual activities and PU-3B preview/apply safeguards remain intact. Removing/replacing a trip selection never deletes or rewrites Checkout order history.

## Flutter

Existing flight search/details and itinerary attachment remain. Trip essentials adds a separate Flight demo Checkout entry so hotel selection does not hide flight review. The shared payment screen shows the server review, every outbound/return segment, adults, price/basis, original time/expiry and fee qualification, then requires Confirm this quote. Unsupported cases show the backend reason and cannot launch payment. Orders uses the immutable flight snapshot and has no Pay action on paid details.

Required disclosures are visible in review and order details:

- Stripe test payment.
- TravelMate demo order.
- No flight has been booked or ticketed.

## Verification

Focused backend tests cover singleton and multi-segment counting, ambiguous party/round-trip scope, compatible returns, stale/original times, ownership/tampering, reconfirmation, immutable snapshots, preserved hotel/manual activities/history, signed webhook binding and incomplete Stripe evidence. Flutter tests cover review/explicit confirmation, unsupported reasons, material changes, paid no-Pay and screen recreation. These fixtures do not establish genuine provider/payment acceptance.

Real acceptance evidence and protected task access are retained outside Git under `D:\workspace\TravelMate\f3-acceptance` and `p1-secure-access`; final executed status, counts, screenshots and Stripe result are reported separately. The runtime has hard one-query and one-Checkout caps and blocks unrelated provider requests. Its protected cached response retains the provider's original timestamp and genuine price; it never manufactures offers or changes prices.

## Executed acceptance status

**IMPLEMENTED / ACCEPTANCE BLOCKED.** The public runtime counter confirms exactly one real F3 provider request and zero Checkout creations. The existing normalized, owner-bound Firestore quote confirms completion: KUL to PEN, 2026-11-09, one adult, MYR, 22 results, including AirAsia MYR 109. Original retrieval was 2026-10-10 03:43:28 UTC; expiry was 04:43:28 UTC. All retained quotes are now stale. A normal authenticated flight-review request returned HTTP 409: “This flight quote is stale. Search again and reconfirm the new quote.” No payment or flight order exists.

The rejected protected-response probe was not repeated. Evidence comes from independently permitted public counters, sanitized normalized durable quote summaries, and the ordinary authenticated review API. The protected raw provider response was not accessed during recovery. The one-search cap was not reset.

Completed automated evidence: 77 focused backend tests, 15 focused Flutter tests, clean Flutter analysis, successful debug x86_64 APK build. The APK was installed on the existing isolated API 35 emulator after the original emulator rejected installation for insufficient storage. Normal owner login reached Home/Profile and the correct one-way search was submitted once. Actual flight-details/review disclosures, paid-flight Orders, no-Pay and paid-flight reopen recovery have not been accepted on the emulator. Fixture tests are reported separately and do not prove those runtime checks.

Read-back confirmed the original paid MYR 163.89 hotel record and owner profile identity unchanged. No hotel payment/provider checks were repeated. Both emulator data directories and protected account access remain intact.

Next action requires authorization for one fresh single-adult one-way provider query in a new bounded acceptance run. Then review and explicitly reconfirm that fresh server-owned quote before using the still-unused single Stripe test Checkout allowance; verify signed webhook, persisted owned order, no-Pay and actual Flutter reopen recovery. Do not extend the old quote timestamp or fabricate a replacement.

Final continuation: search/comparison captions now distinguish ticket references from indicative amounts. Seven relevant Flutter tests were rerun successfully and Flutter analysis remained clean. This final caption-only change was not rebuilt or installed; the previously installed APK contains the core F3 review/disclosure implementation. No full suite or provider/payment operation was repeated.

## F3A existing-session recovery — 2026-10-11

This section records the later F3A recovery and supersedes the earlier statement above that Checkout creation was still unused. It does not change the original F3 search or acceptance result.

The two bounded F3/F3A provider searches remain the only searches: one original F3 query and one F3A query. F3A used KUL to PEN, 2026-11-09, one adult, one-way, MYR. The owner selected the actual Malaysia Airlines MH 1138 quote for MYR 401, retrieved at 2026-10-10 09:34:48 UTC and originally expiring at 10:34:48 UTC. The quote was fresh when the single Checkout Session was created at 09:47:59 UTC. No additional provider query was made.

The one existing F3A Session was retrieved read-only at 2026-10-11 10:25:49 MYT. Stripe reported open, unpaid, livemode false, MYR 401, no PaymentIntent, and a matching owner/order binding. The linked internal order remained checkout_open/unpaid; no signed completion event or payment verification was present. Stripe's Session expiration is 2026-10-11 17:47:59 MYT. The order snapshot and amount are unchanged. A later refresh attempt could not reach Firebase because DNS/network access failed; the saved read-only retrieval is the latest successful status evidence, and no payment or new Checkout was attempted.

The application requires original quote freshness during review and Session creation. This Session was created while its one-hour quote was still fresh. The app uses Stripe's own Session expiry afterward and retains an immutable fixed-price demo-order snapshot; the app does not book or ticket a flight. The quote is now expired, but that does not change the already-confirmed MYR 401 demo order or imply current airline availability. The explicit disclosures remain: Stripe test payment; TravelMate demo order; no flight has been booked or ticketed. This supports completing only this already-created test Session before its Stripe expiry, without representing it as a reservation.

The browser interaction tools were unavailable in this run, so no card form was submitted. The Session remains unpaid and mobile paid-order acceptance is pending. To finish manually, use the already-open Checkout tab on isolated emulator 5556, confirm the hosted page is in test mode and shows MYR 401, and use Stripe's official Visa test number 4242 4242 4242 4242, any future expiry date, and any three-digit CVC. Submit before 2026-10-11 17:47:59 MYT. Stripe documents these interactive test values at https://docs.stripe.com/testing. Then return to TravelMate Profile > Orders and inspect the same flight demo order. Do not proceed if the Session has expired; a replacement query or Session requires new authorization.

Preserved implementation fixes: invalid webhook signatures return HTTP 400 and remain rejected; normal flight itinerary creation supplies its required destination area. The focused backend tests (40 passed), focused itinerary widget regression, Flutter analysis, debug APK build, and emulator install were already completed in the interrupted run. The APK showed the flight review's test-payment, demo-order, and no-booking disclosures. No paid-flight Orders, no-Pay-after-payment, or paid-order restart recovery has been verified. Existing P1 hotel acceptance and its MYR 163.89 paid order were not modified or rechecked.
