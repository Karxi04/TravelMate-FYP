# Flexible personal itinerary planning

Based on `travelmate-full-repair` at `51919834f0c2f97461b50aabed1c16b9e62df5d8`
(merged PR #92). This extends FR5 and FR7; it does not introduce another planner,
provider, checkout flow, or database collection. Source verification is separate
from rollout and physical Vivo acceptance.

## Existing components reused

- FR5 `createItinerary`, `addActivity`, `recalculateItinerary`, `_constraint_plan`
  and `calculateBudget` remain responsible for personal itinerary scheduling and costs.
- The existing flight-adjustment preview registry and apply route now also accept
  personal planning settings and scoped schedule proposals. Existing flight-only
  callers continue to use the same contract.
- Owned saved FR4 recommendation snapshots supply regeneration candidates. An
  improvement or regeneration request does not search providers or generate a
  recommendation snapshot. The 60/30/10 recommendation formula is unchanged.
- Existing editable itinerary history, compare-and-set persistence, flight quote
  validation, ownership checks and package-trip restrictions remain in use.

## Before and after

| Area | Previous behavior | New behavior |
|---|---|---|
| Creation | Recommendation-led creation | Smart remains; Manual and Assisted can create empty editable trips |
| Timing | Planner windows and flight adjustment | Saved arrival/departure choices, daily overrides and rest days |
| Personal plans | Generated breaks in daily schedules | Editable rest, meal, luggage, free-time, transfer and custom blocks |
| Visits | Add, move and remove | Also edit time, duration, notes, user estimate and fixed/flexible status |
| Assistance | Flight-affected preview | Improve a day/remaining days; regenerate flexible day/full trip |
| Saving | Existing owner/CAS safeguards | Same safeguards; previews require an explicit Apply |

## Data contract

All fields below belong to personal `itineraries` records. There is no migration
or batch rewrite of existing records. New controls support trips of 1–14 days;
older longer records remain readable through existing paths.

| Field | Meaning and validation |
|---|---|
| `planningMode` | `smart`, `manual`, or `assisted`; missing means legacy behavior |
| `travelDayPreferences.arrival` | `choice`: `practical`, `rest`, `custom`, or `none`; rest/custom require `startTime` |
| `travelDayPreferences.departure` | `choice`: `keep`, `light`, `custom`, or `none`; custom requires `endTime` |
| `travelDayPreferences.transport` | Optional non-flight arrival/departure date/time pairs, inside trip dates; user-estimated buffer 0–720 minutes |
| `travelDayPreferences.days` | Unique `dayNo` overrides with `startTime`, `endTime`, or `restDay: true` |
| `travelDayPreferences.confirmedFor` | Server-only boundary fingerprint; not accepted from clients |
| `planningBlocks` | At most 56 personal blocks, unique 8–128 character safe IDs and valid trip days |

Times are strict `HH:mm`, interpreted in the existing Malaysia-local planning
contract. Personal block types are `rest`, `meal`, `hotel_luggage`, `free_time`,
`transfer` and `custom`. Blocks support a title, location, notes, optional paired
start/end times, optional untimed duration, fixed status and optional additional
group cost estimate in MYR. Overlapping timed personal blocks are rejected.

`boundary: destination` makes a timed block respect hard arrival/departure bounds.
`boundary: personal` records an unverified personal/origin/travel note; it does
not extend the sightseeing window or certify transport feasibility. Untimed
blocks remain unscheduled notes, not reserved intervals. Timed personal blocks
are retained as reservations during assistance, including flexible blocks; this
release does not automatically relocate the owner's personal block times.

The top-level `planningBlocks` list is authoritative; daily copies are derived
display projections. Existing personal blocks found only in `dailySchedule`
are exposed in read-only planning metadata and retained on an explicit planning
apply. Generated `meal_rest` and `intercity_transfer` rows are not imported as
user blocks. There is no silent migration on GET. Legacy blocks that cannot pass
the new validation must be reviewed rather than silently discarded.

## Practical travel windows

- Selected, owned flight evidence remains authoritative over user transport estimates.
- Opted-in arrival planning allows 90 minutes for airport clearance plus a
  90-minute local transfer estimate. These are visible planning assumptions,
  not live verified journey times.
- Departure retains the existing 90-minute transfer and 120-minute check-in
  assumptions. Buffers can affect the previous evening or next day.
- A custom sightseeing start/end can narrow a safe window, never override it.
  An infeasible choice remains visible with the earliest/latest feasible bound.
- No flight is required. Non-flight dates/times are explicitly user estimates;
  undecided transport stays provisional.
- Flight selection/replacement preserves saved choices but invalidates their
  boundary confirmation when relevant times change. Flutter offers Not now or
  a new planning preview; it does not silently reschedule the trip.
- Existing non-opted-in flight planning retains its original behavior.

## Routes and confirmation

`POST /api/fr5/itineraries` supports empty Manual/Assisted creation. New-mode
creation can carry a `generationRequestId`: a replay returns the same owned trip;
reuse for a different payload is rejected. Flutter retains the exact pending
payload after an ambiguous response and retries only on user action.

Smart creation continues through `POST /api/fr5/personalised-trips/generate` and
the existing owned recommendation-generation contract.

`GET /api/fr5/itineraries/<id>` retains the raw `itinerary` and adds read-only
`planning` metadata: `availability`, `assumptions`, and `personalBlocks`.
The list response adds derived `travelDayStatus` for applicable personal trips.

Use the existing preview route for personal planning:

```json
{
  "planningChanges": {
    "planningMode": "assisted",
    "travelDayPreferences": {
      "arrival": {"choice": "rest", "startTime": "15:00"},
      "departure": {"choice": "light"}
    }
  },
  "action": "settings",
  "scope": "full",
  "expectedItineraryRevision": 1
}
```

- `POST .../<id>/flight-adjustment/preview`: no itinerary write. Actions are
  `settings`, `improve`, `regenerate`; scopes are `day`, `remaining`, `full`.
  Scoped assistance also takes `dayNo`. Global settings require full scope.
- `POST .../<id>/flight-adjustment/apply` with `previewId`: explicit owner/CAS
  apply, existing receipt protection and editable history. A repeated completed
  apply is idempotent. Stale trips, changed flights or foreign previews fail.
- Closing a preview causes no write. Fixed/paid/required visit conflicts block
  automatic apply; other visits that cannot fit remain visible suggestions.
- Regeneration replaces only eligible flexible generated visits. User-selected,
  fixed and commercially protected visits and personal blocks are retained.
  Unselected days are copied unchanged. Missing candidates produce a useful
  error; they do not trigger an implicit provider request.
- Mode-only switches to Manual or the current mode preserve activities exactly.
- Existing activity endpoints perform validated direct edits with revision/CAS
  safeguards. A change that displaces another saved visit is rejected and asks
  for a reviewed schedule proposal.

The preview registry remains process-local, as before. Restarting
the Backend invalidates unapplied previews; reopen/repreview rather than retrying
an old preview ID. Multi-worker shared preview storage is outside this change.

## Budget and historical compatibility

Personal estimates are an optional `personalPlans` category. They are summed once
from the top-level list, never again from daily display copies. The UI warns
against repeating an existing hotel/flight amount. Blank cost means unknown;
explicit zero is a user estimate, not supplier verification. Known subtotals and
unpriced activity/personal-block counts are exposed separately per day.
Existing selected/paid flight and hotel amounts are not edited by scheduling.

Planning settings, personal blocks, activity locks/notes and linked recommendation
generation are included in the existing bounded editable version history. Full
restore retains the existing prohibition for trips with protected commercial
arrangements. This change does not relax restoration or supplier protections.

Purchased package trips cannot use these editing/preview operations. Payment,
booking, supplier fulfilment, notification, review and reporting schemas are
unchanged. Existing SQLite/standalone planning paths remain; the new preview and
personal scheduling controls use the Flask service and are hidden in standalone
Trip Details.

## Rollout and rollback

No service reload, APK build/install, live provider request or Firebase access is
part of source delivery. A matching new normal-app build is required to expose
the new UI. Obtain separate approval before a Backend reload or Vivo upgrade.

1. Review the PR and current environment without printing credentials.
2. Back up local environment settings; do not change provider/payment configuration.
3. With approval, reload only the intended Backend and verify revision/health.
4. Build with the established LAN settings and matching signer; verify hashes.
5. Obtain approval for an in-place upgrade preserving app data and permissions.
6. Use a separately authorized disposable trip/account for the checklist below.

Rollback needs no data deletion: restore the approved prior Backend/app release
using the established controlled procedure. Do not uninstall or clear the app.
New optional fields may remain in records and are ignored by legacy readers.
Avoid editing newly opted-in trips with an older release: it cannot enforce the
new timing preferences. Keep those trips read-only until re-upgraded. Never
rewrite owner history or commercial records as a rollback step.

## Physical Vivo acceptance — pending

No physical-device result is inferred from automated tests. After an approved
rollout, use one authorized disposable trip and no real provider purchase:

1. Create Manual Penang 12–16 December of a valid future year; no flight/hotel.
2. Add Street Art on Day 1, Kek Lok Si on Day 2, Penang Hill on Day 3.
3. Select an authorized valid flight reference arriving 10:00. Choose rest/luggage
   first, 15:00 sightseeing; inspect preview and apply explicitly.
4. Confirm a 20:00 return leaves sightseeing before the safe transfer cutoff.
5. Add rest/meal/custom plans, edit notes/cost/time, move a visit and fix one time.
6. Improve one day/remaining days. Cancel once and verify no change; then apply
   another proposal, retaining the fixed visit, other days and personal blocks.
7. Regenerate flexible Day 2/full trip from owned saved recommendations; inspect
   removals, additions and unscheduled suggestions before applying.
8. Replace with a later authorized flight reference; review changed bounds and
   preserved choices. Do not change a paid/protected arrangement.
9. Force-close/reopen; verify styles, preferences, blocks, locks, budget and history.
10. Check 5/10-day trips, 320/360/390dp and large text, picker cancellation,
    Not now, empty days, unknown costs, offline/ambiguous response recovery.
11. Read existing package, flight/hotel, payment, recommendation and checklist
    screens; do not create payments/bookings or alter owner data for this check.

## Executed source verification — 21 November 2026

| Suite | Final result |
|---|---|
| Complete default Backend | 3,989 passed; 2 existing emulator-only skips; 30 integration tests deselected; 8 warnings |
| Complete Flutter | 1,300 passed |
| Dart/Flutter analysis | No issues |
| Administrator website | 112 passed; 1 deselected |
| Operator website | 213 passed |
| Operator room configuration JavaScript | 5 passed |
| Final focused Backend scheduling/supplier regressions | 111 passed; overlaps the complete suite |

The isolated five-day route scenario covers creation, selected days, mocked owned
flight quotes, arrival/departure choices, rest/meal blocks, fixed visit editing,
scoped preview cancellation/apply and rereading persisted in-memory records.
The Smart test uses the real generation pipeline with owned saved fixture evidence.
Widget tests cover 5/10-day plans, 320/360/390dp with enlarged text, real picker
cancellation, local draft/preview/apply and optional post-flight review failure.
Existing viewport tests scroll to the original activity/image before retaining
their original assertions; no financial or authorization assertion was removed.

The default Backend suite blocks network sockets and live Firebase access.
No new emulator was started. SDK deprecation/future-support and blocked-socket
warnings are retained in the evidence logs. In-memory route tests verify
persistence contracts; they do not establish live Firestore durability or
physical device restart acceptance. Those checks remain pending an authorized
rollout and disposable-trip procedure.
