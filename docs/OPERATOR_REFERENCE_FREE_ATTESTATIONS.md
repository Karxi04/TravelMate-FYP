# Operator arrangement attestations

Transportation and Guide / Activities no longer require an external booking,
licence or voucher reference. The normal Operator forms require the actual
provider/fleet or guide/attraction authority and an unchecked confirmation that
the arrangement is in place. Optional notes and existing Save actions remain.
Accommodation still requires its existing reference; its validation is unchanged.

The same existing FR12 POST accepts `attestation: "confirmed"` for Transport and
Guide / Activities. The Backend requires it even if an external reference is
supplied, validates actual arrangement details, and sets `confirmedBy`,
`confirmedAt` and `provenance: "operator_attested"` itself. Client overrides of
audit/financial fields remain rejected. Historical references are retained when
omitted or blank; edits keep the prior attestation in `attestationHistory`.
Identical confirmed requests remain idempotent. No historical records are
migrated and no booking/reference/reservation is invented.

Readiness uses the same evaluated service components as the action gate. Only
Accommodation requires a reference. Transport requires its actual fleet/provider;
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

On a disposable authorized booking, verify both removed inputs are absent and
Accommodation still has its reference. Try missing provider and unchecked
confirmation; save valid reference-free attestations, reopen and inspect history.
Confirm unpaid/foreign/uncertain/incomplete orders stay blocked. Mark a complete
paid booking ready and compare list/detail badges, filters and counts. Verify a
historical reference remains visible after editing its provider or notes.
Do not use existing customer records solely to obtain the demonstration ratio.
