# Flexible personal itinerary planning

Based on `travelmate-full-repair` at `51919834f0c2f97461b50aabed1c16b9e62df5d8`
(merged PR #92). This extends FR5 and FR7; it does not introduce another planner,
provider, checkout flow, or database collection. Source verification is separate
from rollout and physical Vivo acceptance.

## Current Schedule Assistance and relaxed scheduling — 22 November 2026

The normal Traveller menu now contains only **Improve this day** and **Improve
remaining days** in Smart, Assisted and Manual trips. Both use the existing
preview, Keep current plan (cancel), explicit Apply and revision checks. The
regeneration API and its recovery contract below remain for compatibility; the
two regeneration menu commands and their scope dialog are removed. Initial
Smart trip generation, recommendation refresh, recalculate and editing remain.

Relaxed pace still defaults to 10:00–20:00 and two automatically selected visits
for profiled/local-day generation. It does not imply a 17:00 cutoff. Previously,
early-closing-first ordering could use both slots before a higher-ranked evening
venue was considered. The planner now compares feasible two-visit sequences in
the existing 20-candidate Smart pool, retaining recommendation/context priority,
travel limits, budget checks, visit duration, lunch and personal reservations.
It stops at the first best-ranked feasible pair and compares both visit orders;
it neither creates a night-attraction category nor forces an evening visit.
Explicit Improve operations retain their existing capacity/scope behavior.

Saved Travel Preferences supply `travelDayPreferences.days`; daily overrides
replace pace defaults and remain bounded by arrival/departure buffers. The
standalone constraint planner uses these windows, existing travel-boundary and
opening-hours utilities, personal blocks and fixed visit times too. Shared
Backend/Dart fixtures cover the same controlled schedules. Reported weekly,
split and overnight periods are timetable evidence, not live opening or holiday
verification. Unknown/stale hours remain provisional; closing time does not
establish last admission. No genuine attraction timetable is added by this change.

Automated fixtures and in-memory route lifecycle tests are separate from the
remaining approved-rollout Vivo checks. No owner Trip is used for these tests.

## Regeneration recovery and Travel Preferences — 22 November 2026

### Reproduced causes

Regeneration re-used a Trip's linked evaluation generation after its session had
expired/restarted or its profile/review revision changed. FR5 correctly rejected
unusable evidence, but it also rejected a newly owned generation because its ID
was different from the Trip association. Flutter interpreted most 409s as stale
itineraries and offered to repeat the same deterministic request. A missing preview
also showed an unrelated incomplete-flight fallback. These are controlled source
reproductions; the exact owner's HTTP body and persisted block context were not
captured and no production records were inspected.

### Recovery contract

The existing preview route now returns `code`, `stage`, and `nextAction` for evidence,
Trip revision, time and protected-activity failures. No new API is introduced.
Regeneration first validates the existing linked generation. After an explicit
Refresh suggestions confirmation, Flutter generates through the existing FR4 route,
reloads the current Trip and submits `refreshSuggestions: true`, the previous
`expectedLinkedGenerationId`, new `recommendationGenerationId`, and current
`expectedItineraryRevision`. A different association is allowed only inside this
explicit regeneration preview, with owner/source/canonical-destination and current
snapshot checks. Existing genuine snapshots retain compatibility; any supplied
expiry, profile fingerprint/version and candidate-generation metadata are verified.
Evaluation TTL, local review revision and learned-profile checks stay unchanged.

The original Trip stays unchanged until Apply. The preview carries the new
association, and the existing full fingerprint/atomic history update controls the
save. Cancel does not replace the Trip ID or generation; stale/duplicate Apply
protection remains. Generation recovery does not copy evaluation reviews or
snapshots into genuine Firestore. An explicit FR4 refresh may create its normal
owned recommendation evidence; it never saves a Trip automatically.

| Code | User action |
|---|---|
| `RECOMMENDATION_EXPIRED` / `RECOMMENDATION_REFRESH_REQUIRED` | Refresh suggestions, with confirmation |
| `RECOMMENDATION_NOT_FOUND` | Generate suggestions through the same explicit recovery |
| `RECOMMENDATION_CONTEXT_MISMATCH` | Refresh for the matching destination/mode; authorization still required |
| `STALE_ITINERARY` / `STALE_PREVIEW` | Reload Trip before making a new preview |
| `FLIGHT_TIMING_INCOMPLETE` | Review selected flight |
| `PLANNING_TIME_CONFLICT` | Edit travel preferences |
| `PROTECTED_ACTIVITY_CONFLICT` | Review the fixed activity |
| `NO_REGENERATION_CANDIDATES` | Keep current itinerary |
| Temporary connection / service failure | Explicit Retry connection, never automatic Apply replay |

Day regeneration remains scoped; full regeneration replaces only eligible generated
flexible visits. Fixed/manual-time/paid rows, personal blocks, notes and expenses
remain protected. Empty/rest-day/no-fit replacement proposals return no-change
feedback instead of deleting visits. Improve day/remaining behavior is preserved.
Manual/Assisted trips do not need a flight when date-aware planning is sufficient;
Manual user-added visits remain preserved and no mode change is implied.

### Travel Preferences and time feedback

Planning Settings is now Travel Preferences. The creation-only style selector is
removed, its unchanged `planningMode` is not sent, and legacy records gain no
implicit planning mode. Travel schedule, individual/bulk hours and personal-block
editing remain. Spacing separates independent fields, important travel bounds are
emphasized, and optional assumptions remain in details.

A shared client draft validator checks same-day ranges, paired times, daily hours,
arrival/departure buffers, block overlaps and fixed-visit intersections before
Preview/Save. Changing times immediately rechecks the interval; invalid controls
are disabled without discarding values. The Backend remains authoritative. Timed
personal/travel notes may be outside destination sightseeing hours, while blocks
marked at destination must respect travel bounds. Unscheduled blocks reserve no
slot; unknown cost remains unknown. End before start is never an implicit overnight
interval. Existing airport buffers and selected flight references are unchanged.

Controlled 25–27 November 2026 tests use arrival 14:50 and departure 10:55, producing
17:50 earliest destination sightseeing and 07:25 latest departure-day finish with
the existing configured assumptions. A Day 1 noon lunch explicitly marked
personal/travel is preserved through both Improve actions and both Regenerate
actions. Day-only operations intentionally leave other days unchanged; they do not
certify or repair pre-existing conflicts outside their scope.

Physical Vivo acceptance remains pending a separately approved matching Backend/APK
rollout and disposable-trip procedure. No service restart, APK operation, provider
call, production Firebase access, payment or owner Trip edit is part of this task.

### Regeneration follow-up verification

| Suite | Final result |
|---|---|
| Complete default Backend | 4,071 passed; 2 existing emulator-only skipped; 30 live integration deselected; 10 warnings |
| Complete Flutter | 1,357 passed |
| Dart analysis | No issues |
| Administrator | 112 passed; 1 integration deselected |
| Operator | 213 Python and 5 JavaScript passed |

Focused planning Backend (76), lifecycle/recovery Flutter (44) and final time
widget/unit cases (24) overlap the complete totals. No live Firebase emulator or
supplier test is inferred. The original missing-generation test now asserts its
explicit409/code/action contract; the removed style-switch widget test asserts
absence of incidental mode writes. Lifecycle tests retain stale/restart recovery
and no-write checks using the current structured response. Initial failed logs
are retained; no test was skipped or removed to hide a defect.

## Mobile and supplier comparison follow-up — 22 November 2026

- Travel schedule now groups optional arrival/departure date and time controls,
  with associated Clear actions and responsive stacking. Extra travel time has
  a short explanation. Attached flight times remain read-only and authoritative;
  airport planning allowances are available in collapsed details. Keyboard space
  is reserved so the preview action remains reachable.
- Why this suggestion shows the actual overall hybrid score and three independent
  60/30/10 components first. Detailed peer count/confidence, local/provider rating
  provenance, illustrative-data limitations and attribution remain accessible
  under How recommendations work. No scoring or review data changed.
- A reproduced cross-module defect tied supplier search receipts to the entire
  Trip fingerprint. Saving daily hours, personal blocks or derived budget metadata
  made exact saved searches unavailable, even when supplier criteria were intact.
  Flutter also discarded the references before the Backend could recheck them.
- Newly submitted searches carry `searchContextVersion` in the existing search
  receipt, covering owner/Trip, dates, destination, passengers, selected supplier
  evidence and protected arrangement fields. Saved references can be re-read
  after unrelated planning changes; every quote, price, expiry, cabin, occupancy
  and timing constraint is revalidated against the current Trip. A new offer uses
  the current **full** state version; old previews still cannot apply. No old
  receipt or Trip is migrated. Legacy receipts retain strict full-version checks.
- Same-cabin and explicitly chosen lower-cabin searches keep their original
  two-request cap; hotel searches keep the one-request cap. Read-only rechecking
  never calls providers. Expired, unrelated and paid/pending arrangements remain
  blocked. A mismatched old receipt now explains the need to refresh rather than
  claiming that no cheaper inventory exists.

The regression baseline reproduced 12 failures with isolated saved supplier
receipts; these are source-level findings, not proof of the owner's precise live
supplier failure. Runtime health reports no source SHA, and installed version
metadata does not establish an APK commit. Real supplier availability and matching
Backend/APK Vivo replacement acceptance remain pending separate authorization.

After an approved matching rollout, use an authorized disposable Trip: check
arrival/departure controls and keyboard, expand recommendation provenance, search
Same Cabin/explicit Lower Cabin, review valid hotel revalidation, then inspect
supplier counts/expiry and Preview → Cancel or Confirm → Reopen. Confirm no
duplicate budget amount and retention of fixed visits, personal breaks and paid
records. Live supplier searches and mutations require their separate approvals.

### Follow-up verification

| Suite | Final follow-up result |
|---|---|
| Complete default Backend | 4,035 passed; 2 existing emulator-only skips; 30 integration tests deselected; 6 warnings |
| Complete Flutter | 1,333 passed |
| Dart analysis | No issues |
| Administrator | 112 passed; 1 integration deselected |
| Operator | 213 Python and 5 JavaScript passed |
| New targeted supplier integration | 23 passed; included in the complete Backend count |

The initial complete Flutter run had five assertions expecting provenance text
before expanding details. Tests now open the requested detail control and retain
the original source/count/confidence and no-side-effect assertions. The final
complete run passed. Mobile layout evidence is automated; it does not establish
physical Vivo success or current real supplier availability.

## PR #93 continuation — 22 November 2026

The follow-up addresses the owner's Smart Planning, Budget/Expenses and form
acceptance findings. The 21 November results below are retained as historical
evidence; they did not prove the previously missing FR4 evaluation integration.

### Confirmed causes and corrections

- **Smart Planning:** FR4 stores authorized evaluation generations in its
  owner-scoped `EvaluationSession`, while FR5 previously looked only in genuine
  Firestore snapshots. A shared `recommendation_snapshot_resolver` now resolves
  the server-selected source. FR4 and FR5 share mode/context authorization,
  preference versions/fingerprints and review revisions without Blueprint imports.
  Evaluation resolution checks exact generation, owner, canonical geographic
  scope, existing one-hour expiry, preferences/learning, local review revision and
  candidate generation identity. A local evidence outage is retryable 503, not
  falsely classified as an expired generation. Genuine snapshots retain their
  existing owner/destination contract; evaluation records cannot enter that path.
- **Client integration:** Flutter previously attached `fyp-v1` context only to
  review/FR4 requests. The shared request-header contract now also covers the
  specific FR5 snapshot-consuming POST operations. Firebase authentication,
  financial request handling and trusted-LAN selection are unchanged. A header
  cannot enable evaluation mode or authorize a foreign generation.
- **Budget delay:** Trip Details previously awaited Budget GET before navigation,
  and GET rewrote `budgetEstimate`. Budget now opens immediately with its existing
  cached estimate and a refresh indicator. Duplicate navigation/reads are guarded;
  stale/disposed responses are ignored and failures retain the prior view with
  Retry. GET calculates the same authoritative response without writing a Trip or
  revision. Returning from a read-only view does not reload all saved Trips.
- **Expenses:** GET previously used the mutation transaction wrapper. It now
  performs bounded linked-document reads, retaining the exact owned hotel/order
  verification. PATCH still uses the original atomic revision/amount checks.
  Cached rows survive temporary failures; refresh has explicit progress/Retry,
  version guards and no simultaneous duplicate GETs. A lost PATCH result blocks
  further edits until a read confirms current records; PATCH is never automatically
  replayed. New diagnostics contain method, status, elapsed time, random request
  ID and exception class, without account IDs, tokens or record contents.
  **The exact cause of the owner's physical disconnect remains unverified**:
  no production request, live Firestore diagnostic or device operation was used.
- **Daily hours:** the repeated "Apply to middle days" controls are replaced by
  one "Set hours for multiple days" action. Selection, hours and affected days are
  reviewed before applying to the local draft. Unselected overrides remain intact;
  arrival/departure days are not implicitly selected. Dates and labels follow
  available flight/transport dates, including overnight arrival. Rest days retain
  personal plans and expose conflicting visits in the existing server preview.
- **Personal blocks:** a full-screen local editor replaces the tall dialog.
  Basics/time remain visible; optional details are collapsed. Keyboard-aware
  scrolling and a stable action area retain data through picker/dropdown use.
  Costs remain optional estimates and boundary semantics are unchanged. Add/Edit
  only returns a draft to the existing Preview/Apply flow.

### Controlled before/after evidence

The exact committed handlers from `4c3120716aa32ae61d6a865bb9a5e122c4b480d7`
were compared with the corrected routes using synthetic in-memory records and
the real FR4 evaluation generation pipeline. The baseline Smart request returned
409; the corrected request returned 200 and persisted/reopened one five-day Trip.
No genuine Firestore recommendation document was fabricated for this test.

| Controlled HTTP measurement | Before median | After median | Removed work |
|---|---:|---:|---|
| Budget GET | 46.82 ms | 5.88 ms | 5 writes across 5 baseline requests; 0 after |
| Expenses GET | 47.74 ms | 7.22 ms | 5 transactions across 5 baseline requests; 0 after |

Each variant ran five times with injected 5 ms document-read latency and 40 ms
write/transaction overhead. Response JSON remained equal. These are reproducible
controlled measurements, **not production Firestore or physical Wi-Fi timings**.
No global timeout was increased. Fixture data is not genuine customer evidence.

### Compatibility and pending acceptance

No new persistent fields, collections, indexes, dependencies, environment settings
or migrations are required by this repair. Evaluation snapshots remain ephemeral
and never become genuine snapshots/reviews. Previously saved Trips and successful
generation-request recovery remain usable after an evaluation session expires.
Creating a new plan from refreshed evidence remains an explicit operation; it
does not overwrite an existing saved itinerary.

After a separately authorized matching Backend/app rollout, use only an approved
disposable Trip/account for writes:

1. Smart: explicitly refresh Penang suggestions, Build once, open/reopen the new
   Trip; test a deliberate expired session separately without altering owner Trips.
2. Manual: edit arrival/departure days individually; select Days 2–4 for bulk hours,
   exclude Day 3, toggle rest, add/edit personal plans, cancel then apply/reopen.
3. Budget/Expenses: observe immediate loading and cached values; test a temporary
   connection failure and Retry. Add/edit/delete expenses only on that disposable
   Trip with approval; verify revisions and no repeated save after unknown delivery.
4. Flight: use an authorized existing owned reference, retain fixed visits and
   verify airport bounds through cancel/re-preview/apply/reopen. No new provider
   search, reservation or payment is implied by these source tests.

Physical Vivo acceptance, real Firestore durability and the owner's original
intermittent connection failure remain **PENDING**. No rollout is part of this PR
follow-up. Preserve existing app data and permissions when preparing any later
approved in-place upgrade.

### Final continuation verification

| Suite | 22 November result |
|---|---|
| Complete default Backend | 4,012 passed; 2 existing emulator-only skips; 30 integration tests deselected; 8 warnings |
| Complete Flutter | 1,319 passed |
| Dart/Flutter analysis | No issues |
| Administrator | 112 passed; 1 deselected |
| Operator | 213 Python tests and 5 JavaScript tests passed |
| Exact baseline/controlled HTTP comparison | 1 passed; separate from the complete Backend suite |

Genuine snapshots with absent, null or explicit genuine evidence-mode metadata
are covered. Evaluation isolation, review revision/outage handling, preference
fingerprints, expiry, request recovery and concurrent Build protection use the
real FR4/FR5 routes with isolated persistence. Widget tests cover immediate/cached
Budget reads, error/retry, lost expense-save response, selected-day apply/reopen,
overnight labels, picker cancellation, invalid duration/range/cost and keyboard
layouts at 320/360/390dp. No financial or ownership assertion was weakened.

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
| Assistance | Flight-affected preview | Improve a day/remaining days; regeneration API retained for compatibility only |
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
7. Confirm both Regenerate commands are absent from Schedule Assistance; initial
   Smart generation and normal recommendation refresh remain available.
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
