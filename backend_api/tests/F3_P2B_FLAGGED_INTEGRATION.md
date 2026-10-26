# F3-P2B controlled FR05 integration — disabled by default

`TRAVELMATE_BUDGET_AWARE_SELECTION_ENABLED=false` is the default. The code reads
only the server process environment, using the existing environment-flag convention.
No application `.env`, running Flask process, Cloud deployment or mobile configuration
was changed. Request bodies, query parameters and headers cannot enable this flag.
The test suite sets it false before app import; isolated tests explicitly override it.
Do not activate it without separate approval.

## Insertion and safety boundaries

The integration sits in `_generate_itinerary_data`, after new candidate mapping and
before the existing generation state machine's budget/save steps. Only a linked,
owned recommendation snapshot with original FR04 scores can use the selector.
Existing activities are not reselected; missing linked scores take the legacy path
with an explicit `applied=false` reason rather than invented scores. No extra lookup
or provider query was added. The original 20-candidate safety limit remains.

The enabled-only projection preserves scores and travel evidence. It enriches copies
using the existing registry, never overwriting recommendation snapshots. The selector
returns its existing scheduled plan, avoiding another scheduling pass or duplicated
scheduling logic. Forecast, opening-hour uncertainty, durations and pace remain under
the same engine. The existing generating/planned/failed persistence boundaries remain.
Planned personalised retries and GET reads do not invoke selection or rewrite budgets.

The server returns optional `budgetAwareSelection` diagnostics: candidate counts,
known/unknown cost exposure, original score sums/averages, exclusions, repair and
fallback explanations. No numeric savings or satisfaction claims are generated.

## Compatibility and cost truth

Top-level FR05 response keys (including `smartFeatures`) and numeric legacy budget
fields remain. Authoritative numeric estimates still come from `calculateBudget`.
The adapter adds uncertainty, not new prices or discounts. Unknown fallback visits
retain `selectionGroupCost=null`; optional metadata distinguishes applicable unknown
totals from known lower bounds. Legacy numeric daily estimates remain readable, with
`applicableActivityCost=null` and incomplete status alongside them. A numeric legacy
zero is not evidence of verified free admission.

Persisted unresolved activities retain unverified/conditional pricing evidence, so
ordinary shared budget calculation cannot promote them to verified costs later.
Generation-level deferred unknown choices also keep the generated budget pending,
even when all selected activities have known prices. Non-generation editing and
explicit recalculation workflows otherwise retain their existing contracts; full
frontend/lifecycle acceptance is required before activation. No Atomic Apply code,
payment, booking or historical snapshot migration was changed.

## Isolated evidence and activation blockers

Tests exercise actual Flask HTTP generation with mocked auth, persistence, weather
and provider boundaries, plus an exact disabled-versus-legacy generation comparison.
Full backend regressions are required because FR05 route logic changed. No real
Firestore or provider acceptance is claimed.

Verification executed: 22 new integration cases, all 70 existing selector cases,
310 focused cases, and the complete backend directory: 1182 passed / 16 opt-in
emulator cases deselected. Compilation, diff checks and changed-file credential scan
passed. AST comparison confirmed the Atomic Apply/flight-hotel reference validation
functions were unchanged. The initial new response-key assertion omitted the
existing `smartFeatures` field; the fixture assertion was corrected, not the API.

Three-repetition isolated benchmark examples (Python 3.12.14, Windows 11 AMD64):

| Fixture | Disabled median | Enabled median | Quality/cost observation |
|---|---:|---:|---|
| Three-ticket repair pool | 0.879 ms | 3.745 ms | 3 over-budget visits → 2 budgeted visits; sum 219 → 129, average 73 → 64.5, category variety 3 → 2; travel 16 → 8 min |
| Two unknown visits | 0.525 ms | 2.794 ms | Same count 2, sum 160, average 80 and travel 8 min; both costs remain incomplete |
| Twenty known candidates | 19.079 ms | 161.094 ms | Same 20 visits, sum 1620, average 81, variety 1 and travel 136 min |

These are synthetic fixture results, not production latency or provider quotes.
The 20-candidate overhead is material (about 8x in this run), even though absolute
time remains below one second. Do not force activation: profile request capacity and
agree on a latency budget first. Real pricing/eligibility, routing/hours reliability,
uncertainty presentation, quality/coverage trade-offs, and generation-to-edit lifecycle
acceptance remain prerequisites. The bounded heuristic is not globally optimal.
