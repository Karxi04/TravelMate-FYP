# F3-P2D sparse-trip repair — NOT activated

Baseline: ca339ea5fa00c8a104cb5a4d7e452e596d0159c0,
branch batch-18-flight-hotel-integration. The server flag remains false by default.
No environment file or running service was changed. F3-P2C's density quotas and
assumed adult tariff ceilings were deliberately not adopted: neither establishes
schedule feasibility or traveller-applicable admission prices.

## Root cause and minimal repair

The selector's `if not selected` gate skipped every unresolved-price candidate once
a free or known-priced visit had been accepted. Provisional completion now follows
known-cost selection and the existing one-for-two repair whether or not the set is
empty, provided known non-activity costs do not already exceed the group budget.

Each deferred, geographically eligible candidate is tried once in unchanged score
order. The existing scheduler must fit the entire proposed set; no accepted visit
can disappear. No minimum daily density, score reweighting, invented price or new
scheduling engine is introduced. The bound is one initial scheduling call, at most
N greedy/completion calls combined, and at most 64 repair trials (only qualifying
repair trials call the scheduler). Production mapping retains its 20-candidate cap;
the standalone selector's 35-candidate test is not an expansion of that cap.

Mixed results report `budget_checked_with_provisional_completion`; all-unknown
results retain `provisional_unpriced_fallback`. `provisionalAdditionTrials` records
completion attempts, including rejected attempts. Known-only results remain
`budget_checked`. Rejections retain geography, joint-feasibility or budget reasons.

Only unresolved visits lose derived `effectiveCost` and gain nullable
`selectionGroupCost`/unresolved status. Known visits retain prices, evidence and
effective group costs. Only days containing unresolved visits have nullable
applicable admission totals. The existing adapter keeps legacy numeric estimates
readable but qualifies them as incomplete; conditional eligibility/source fields
survive. `knownCategoryTotals` and known subtotals are preserved separately from
nullable complete activity totals. Unknown is never a verified RM0 charge.
Known overruns remain over-budget; unknown additions do not prove affordability.

## Reproduced quality evidence

The deterministic fixture mirrors the audit's 12 venue names/scores, one or two
free attractions, and otherwise unresolved/conditional tariffs: Penang, 3 days,
2 travellers, RM2000 group budget. Coordinates, durations (100 minutes), timetable
and ticket evidence are explicitly synthetic, not newly verified venue facts.
No live snapshot or provider was read. Expected selection comes from actual engine
feasibility, not a hardcoded count of 12.

| Free candidates | Before, visits/day | Repaired, visits/day | Legacy, visits/day |
|---|---|---|---|
| 0 | 4 / 4 / 4 | 4 / 4 / 4 | 4 / 4 / 4 |
| 1 | 1 / 0 / 0 | 4 / 4 / 4 | 4 / 4 / 4 |
| 2 | 2 / 0 / 0 | 4 / 4 / 4 | 4 / 4 / 4 |

One-free score sum increases from72.34 to803.10; all selected original scores
remain unchanged. This is recovered personalized coverage, not a satisfaction
percentage or proved cost optimum. Known fixed subtotal is RM465; admission total
remains unknown and budget provisional. Conditional fixture tariffs remain
conditional. A 20/35-candidate extension still schedules only 4/4/4 visits; remaining
8/23 candidates cannot jointly fit hours/duration/travel/lunch constraints. A separate
closed-weekday case correctly keeps Day2/3 empty; completion is never forced.

## Offline performance trade-off

Python3.12.14, Windows11 build26200 AMD64, 10 repetitions per mixed fixture.
P95 uses nearest rank (with 10 samples, the maximum); mock call-count instrumentation
is included consistently. Results are synthetic CPU timings, not production latency.

| Candidates | Before median/P95 ms | Repaired median/P95 ms | Legacy median/P95 ms | Scheduler calls | Repair trials | Completion trials |
|---|---|---|---|---|---|---|
| 12 | 8.376 / 12.381 | 48.481 / 72.654 | 7.985 / 9.253 | 13 | 0 | 11 |
| 20 | 13.367 / 13.697 | 128.570 / 130.308 | 19.183 / 21.384 | 21 | 0 | 19 |
| 35 | 23.257 / 27.916 | 283.701 / 287.728 | 39.533 / 40.879 | 36 | 0 | 34 |

Before timings measured the broken one-visit result, not equivalent useful work.
Full-set scheduling/deep-copying dominates added work; the cost is material and
must be reviewed before activation. Retained known-price benchmark medians:
20 candidates157.219ms, 35 candidates512.222ms; a tight-budget pool exercises64 repair
trials (median14.728ms). Those older tests use three repetitions, not P95 estimates.
No scheduler bypass or unsafe caching was added to disguise the overhead.

## Verification and remaining activation blockers

Focused tests cover free+unknown, all-unknown, mixed paid/free/conditional, price and
score retention, tight/high/overrun budgets, closed/out-of-scope/missing-coordinate/
split-hours/duration/travel rejection, uncertainty/weather/pace, legitimate empty
days, duplicate IDs, repair preservation, repeatability and affected-day totals.
Existing Flask tests verify client isolation, disabled legacy parity, response shape,
mock-only persistence and incomplete budget recovery. Verification completed:
18 new cases; 328 focused cases passed; full backend1200 passed,16 opt-in emulator
cases deselected (exit0). Four changed/new Python files compiled; diff integrity
and credential-pattern scan passed with zero findings. Initial reproduction had
two expected sparse-trip failures (one/two free visits). A new relevance test initially
forgot the scheduler's8-minute transfer: extending its synthetic one-visit window
to11:30 fixed the fixture without weakening scheduling. Final suites passed.

Flutter remains unchanged: selection rationale, per-visit unresolved-price badges
and exclusion explanations still need presentation/physical acceptance. Reliable
real opening hours, price eligibility, routing and generation/edit lifecycle checks
remain necessary. The heuristic is not globally optimal. No live APIs, Firebase
writes, trips/orders/payments, runtime restarts or APK/device operations are authorized
or performed by this batch. Do not enable the feature without separate approval.
