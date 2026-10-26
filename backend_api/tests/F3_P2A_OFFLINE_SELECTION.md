# F3-P2A offline selection prototype

This is **not production Budget-Aware Optimization**. No route imports the selector.
It never fetches quotes, looks up prices, writes repositories or returns a save-ready
Trip. All benchmark prices and scores are synthetic test fixtures, not provider rates.

## Contract and heuristic

`select_budget_aware_activities(candidates, itinerary, forecast=None)` accepts normalized
activities with unique `activityId`, unchanged FR04 `score` (or `finalScore`), dates,
coordinates, opening-hour evidence and existing pricing fields. The supplied pool
replaces activities only in an offline copy. Previously selected activities are not
implicitly locked or retained. Dates and one total group budget must be explicit.

Candidates are tried in descending original-score order. Equal scores break ties by
usable group cost, then activity ID. No price/utility ratio, score floor or new weight
is introduced. For each candidate:

1. Require the existing Malaysian geographic guard and valid coordinates.
2. Resolve cost through `activity_pricing`; defer unknown, conditional, overlapping,
   unsupported-currency or unverified prices. A missing price is `None`, not RM0.
3. Require source/date evidence. Positive per-person prices also require explicitly
   applicable eligibility evidence. No age or residency is inferred from headcount.
4. Use `calculateBudget` for existing flights/hotels/rental/food/transport plus the
   trial activity set. No allowance is repurposed as attraction spending.
5. Ask the unchanged scheduler to fit **all** selected visits together. Reject the
   candidate if adding it makes any selected activity unschedulable.

This is a greedy feasibility heuristic, not a mathematically optimal solver. An
accepted costly high-score attraction can block several lower-score alternatives;
there is no backtracking, replacement engine or proof of globally maximal relevance.

## Honesty and limitations

- `budget.status` is `within_known_estimates`, `provisional` or `over_budget`, not a
  guarantee of actual affordability. Unpriced candidates are deferred and keep the
  pool-level selection provisional, even though they are not charged as selected.
- Existing non-activity pending/excluded categories remain explicit. Known allowances
  are planning estimates. Rental values can be simulated, not live reservations.
- Only existing budget categories are modelled. Separate mandatory fees not already
  included in supplied totals have no independent fee contract here. Fuel/tolls stay
  excluded where the shared budget contract excludes them.
- Applicable eligibility metadata is trusted input for this offline prototype, not
  independently verified against users, ticket products or live providers.
- Unknown/transient/stale hours retain the scheduler's provisional visit status.
  `fits_reported_constraints` means only that the existing engine fitted the set.
  Reported hours, holiday exceptions, estimated routing/duration and missing first/
  last daily transfers prevent a guarantee of real-world itinerary feasibility.
- No historical data, pricing registry, FR04 weights or production scheduler changed.

## Reproducible offline evidence

Run with the repository backend virtual environment:

```powershell
.\backend_api\.venv\Scripts\python.exe -m pytest backend_api/tests/test_budget_aware_selection.py -q --basetemp=D:\workspace\tmp\travelmate-f3-p2a-verification
```

The benchmark test prints `OFFLINE_SYNTHETIC_BENCHMARK` rows for ten required scenarios
and 20/35-candidate pools, using three repetitions per fixture and reporting median/
maximum elapsed milliseconds. Timings are environment-specific, not service latency
or a scalability guarantee. The comparison baseline retains the existing geographic
guard, scheduler and budget calculation, but does not budget-filter the activity pool.
Incomplete baseline costs must not be interpreted as genuine free visits.

Measured examples (all MYR amounts are synthetic group estimates):

| Scenario | Baseline total | Selected total | Original score sum, baseline → selected |
|---|---:|---:|---:|
| Two travellers, RM250 budget | 365 | 185 | 245 → 150 |
| Four travellers, RM400 budget | 380 | 380 | 150 → 150 |
| Flight/hotel-heavy, RM1250 budget | 1295 | 1195 | 170 → 80 |
| High RM2000 budget | 365 | 365 | 245 → 245 |

Lower totals come from excluding unaffordable activities, not invented discounts.
There is a real relevance/coverage trade-off; original scores are not rewritten.
Final medians: 20 candidates 158.289 ms; 35 candidates 500.371 ms (three repetitions).
All-unknown inputs returned no selected visits and a provisional cost result.

Before any production integration: decide UX for deferred candidates and relevance
trade-offs, validate real ticket eligibility and fees, establish reliable operating
hours/routing, and separately authorize preview/persistence integration and acceptance.
