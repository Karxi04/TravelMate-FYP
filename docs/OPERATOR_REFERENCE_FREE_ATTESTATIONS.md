# Operator arrangement attestations

All three services accept reference-free operator attestations. The normal forms
require the actual Accommodation provider/hotel, Transport provider/fleet or
Guide/attraction authority and an unchecked confirmation that the arrangement is
in place. Optional notes and existing Save actions remain. Purchased brochure
specifications and Administrator-reviewed entitlements remain read-only and
separate from the actual Accommodation provider field. A brochure placeholder
such as "To Be Confirmed – Teluk Bahang / Batu Ferringhi Area" is never prefilled
as the actual hotel and cannot satisfy Backend readiness. Obvious placeholders,
empty/generic names and non-meaningful names are rejected; this does not verify
that a property or supplier reservation exists.

The same existing FR12 POST accepts `attestation: "confirmed"` for all three
services. The Backend requires it even if an external reference is
supplied, validates actual arrangement details, and sets `confirmedBy`,
`confirmedAt` and `provenance: "operator_attested"` itself. Client overrides of
audit/financial fields remain rejected. Historical references are retained when
omitted or blank for all services; edits keep the prior attestation in `attestationHistory`.
Identical confirmed requests remain idempotent. No historical records are
migrated and no booking/reference/reservation is invented.

Readiness uses the same evaluated service components as the action gate.
Accommodation requires a meaningful actual provider/hotel; Transport its actual fleet/provider;
Guide / Activities requires its actual authority. Required arrangements also
need confirmed status, operator provenance, actor and confirmation time.
Uncertain purchased requirements or integrity errors require review. Payment,
linked owned Traveller Trip, terminal-state and package protection stay intact.
A historical `trip_ready` flag cannot make incomplete arrangements display Ready.
The actual Mark Arrangements Ready transition remains explicit.

List and Details use the authoritative `statusOverview`: Ready and Arrangements
Recorded use the existing green status style; Awaiting Arrangements, partial
records and Needs Review use orange. Individual service badges use the evaluated
components rather than a raw `confirmed` flag. Saved Arrangements includes
reference-free attestations, actual provider/authority, status, confirmation time,
provenance, optional notes and any historical reference. Operator attestation
never claims independent supplier verification.

## Persistent confirmation display

Each complete service card shows a green **✓ Arrangement Confirmed** indicator
from its authoritative readiness component, together with the saved provider,
confirmation time, notes and operator-attested disclosure. The editable required
checkbox remains separate and unchecked after reopening. Changing provider, notes
or other form details clears a checked editable confirmation, so the updated
arrangement requires an explicit fresh attestation. The input handler never
submits or performs requests, and refreshing the page is a GET only.

Accommodation notes can retain room allocation such as two rooms for three
travellers; no room or supplier reservation is invented or automatically assigned.
Historical Accommodation references remain visible when present; there is no
reference input and no artificial reference is generated. Final Ready still
requires the original explicit action and all payment/ownership/entitlement,
protected-order and linked-Trip safeguards.

## Isolated demonstration data

`backend_api/tests/fixtures/operator_fulfillment_demo.json` contains ten explicitly
synthetic bookings: eight calculated Ready, one Awaiting Arrangements and one
Needs Review. All identifiers and providers are fictional. This file is loaded
only by isolated tests, never by production routes, analytics or notification
workers. It is not a live import plan. It preserves the normal readiness formula
rather than assigning badge colours randomly.

The verification workspace contains labelled static pages rendered through the
actual Operator templates with mocked API responses. Those are read-only previews,
not a deployed portal or accepted customer fulfilment history. A staging/live
import, service reload and authenticated browser acceptance require separate
authorization. No production records need changing to demonstrate the fixture.

## Acceptance after an authorized rollout

On a disposable authorized booking, verify all reference inputs are absent.
Try missing/placeholder Accommodation provider and unchecked
confirmation; save valid reference-free attestations, reopen and inspect history.
Confirm unpaid/foreign/uncertain/incomplete orders stay blocked. Mark a complete
paid booking ready and compare list/detail badges, filters and counts. Verify a
historical reference remains visible after editing its provider or notes. Confirm
one saved green indicator per service, while every editable confirmation remains
unchecked and is cleared again after changing details.
Do not use existing customer records solely to obtain the demonstration ratio.
