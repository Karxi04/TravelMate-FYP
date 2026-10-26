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
3. Require source/date evidence for budget-checked selection. Positive per-person prices also require explicitly
   applicable eligibility evidence. No age or residency is inferred from headcount.
4. Use `calculateBudget` for existing flights/hotels/rental/food/transport plus the
   trial activity set. No allowance is repurposed as attraction spending.
5. Ask the unchanged scheduler to fit **all** selected visits together. Reject the
   candidate if adding it makes any selected activity unschedulable.

After the greedy pass, try at most 64 deterministic one-for-two combinations of an
accepted activity and two known-price, budget-rejected activities. Accept the best
strict aggregate-score increase found that preserves the full budget and joint
schedule. Only one replacement is applied; ties retain the earlier deterministic
choice. Geography/time-rejected candidates are never smuggled into this repair.
This bounded local improvement has no proof of globally maximal relevance.

If no budget-checked activity is selected and known mandatory costs are not already
over budget, try unpriced candidates in personality-score order with the same joint
scheduler. This is a **provisional unpriced fallback**, not an affordable plan.
Mixed pools that already have a budget-checked plan continue to defer unknown-price
visits instead of silently adding unbudgeted costs. Closed/out-of-scope visits still
cannot enter the fallback; unschedulable visits retain explanations.

## Honesty and limitations

- `budget.status` is `within_known_estimates`, `provisional` or `over_budget`, not a
  guarantee of actual affordability. Unpriced candidates keep the pool-level selection
  provisional, whether deferred or scheduled through the fallback.
- Fallback selections have `selectionGroupCost=null`; affected daily `estimatedCost`
  and `categoryTotals.activities` are null, not zero. `knownActivitySubtotal` and
  `knownCategoryTotals` report only the known lower-bound costs. Historical untyped
  `estimatedCost` inputs are preserved but never counted as applicable known charges.
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

The benchmark test prints environment metadata and `OFFLINE_SYNTHETIC_BENCHMARK` rows
for the original scenarios, the greedy trap, 20/35-candidate pools and a budget-tight
20-candidate repair pool, using three repetitions per fixture and reporting median/
maximum elapsed milliseconds. Timings are environment-specific, not service latency
or a scalability guarantee. The comparison baseline retains the existing geographic
guard, scheduler and budget calculation, but does not budget-filter the activity pool.
Incomplete baseline costs must not be interpreted as genuine free visits.

Original F3-P2A examples (all MYR amounts are synthetic group estimates; these four
outcomes remain unchanged after hardening):

| Scenario | Baseline total | Selected total | Original score sum, baseline → selected |
|---|---:|---:|---:|
| Two travellers, RM250 budget | 365 | 185 | 245 → 150 |
| Four travellers, RM400 budget | 380 | 380 | 150 → 150 |
| Flight/hotel-heavy, RM1250 budget | 1295 | 1195 | 170 → 80 |
| High RM2000 budget | 365 | 365 | 245 → 245 |

Lower totals come from excluding unaffordable activities, not invented discounts.
There is a real relevance/coverage trade-off; original scores are not rewritten.
Original medians: 20 candidates 158.289 ms; 35 candidates 500.371 ms (three repetitions).
Original all-unknown inputs returned no selected visits despite available time.

## F3-P2A-R quality and fallback evidence

Two failing deterministic tests first reproduced the empty unknown-price result and
the A-versus-B+C greedy trap. Both were intentional restrictions of the first
prototype, not production failures. No production/shared logic was changed.

| Case | Original greedy | Refined result | Cost truth and feasibility |
|---|---|---|---|
| A=90/RM100, B=65/RM50, C=64/RM50; RM100 activity budget | A: 1 visit, sum/average 90/90 | B+C: 2 visits, sum/average 129/64.5 | Both RM100; complete known costs; both schedules fit reported hours |
| Two unknown-price visits, score 80 each | 0 visits, sum 0 | 2 provisional visits, sum/average 160/80 | Admission unknown, known fixed subtotal RM155 only; incomplete; both visits fit reported hours |
| Known paid visit plus unknown-price visit | Known visit selected | Same budget-checked visit; unknown remains deferred | Provisional pool-level cost completeness remains explicit |

Score sum is a coverage/utility objective, not a satisfaction percentage. A higher
sum with more visits can have a lower average; neither statistic alone proves better
personalization. Strong expensive preferences are retained when cheaper combinations
do not strictly improve aggregate score or cannot fit time/geography/budget.

Runtime environment: Python 3.12.14, Windows 11 build 26200, AMD64; three repetitions
per fixture. Final regression-run refined median/max: 20 candidates 156.062/156.557 ms;
35 candidates 506.913/508.579 ms. A budget-tight 20-candidate fixture exercised the
64-trial bound at median/max 14.335/14.363 ms and improved sum 90 to 129.
These differences from the original are timing variation, not a claimed speed
improvement. Bounded repair has at most 64 candidate-combination evaluations,
not a global search. Closed/provisional hours, missing coordinates, inter-visit travel,
four-person scaling, mandatory fixed overruns, conditional tariffs, incomplete mandatory
expenses, repeatability and the 64-trial bound have dedicated deterministic checks.

Verification: 70 selector cases pass; the combined relevant backend regression
command passed 338 tests. Final review also reproduced and fixed a floating-point
score tie that could falsely report a strict improvement; comparisons now use the
same two-decimal precision as reported score sums. Shared production logic was untouched, so an unrelated
full backend run and live/runtime acceptance were not repeated.

Before any production integration: decide UX for deferred candidates and relevance
trade-offs, validate real ticket eligibility and fees, establish reliable operating
hours/routing, and separately authorize preview/persistence integration and acceptance.
