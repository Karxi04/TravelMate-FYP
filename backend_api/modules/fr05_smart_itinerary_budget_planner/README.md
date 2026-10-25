# FR5 Smart Itinerary and Budget Planner

`routes.py` contains the Flask REST endpoints for this functional module.

The backend verifies Firebase ID tokens before protected operations and uses the Firebase Admin SDK for Firestore access.

## Optional activity pricing (MYR group planning estimates)

New activities may supply `pricingUnit` (`per_person`, `per_group`,
`already_aggregated`, `unknown`), `unitPrice`, `costCategory`, and
`costProvenance` (`verified_ticket`, `catalog_estimate`, `user_entered`,
`unverified`). Optional evidence fields are `priceSourceUrl`, `priceVerifiedAt`,
and `overlapsAllowance`. Metadata is an input assertion, not independent provider
verification or payment authority.

- Per-person: multiply `unitPrice` (or the original `estimatedCost` if omitted)
  by the positive integer traveller count; round the result to MYR cents.
- Per-group: use the same price once. Already-aggregated: use `estimatedCost`
  once, ignoring `unitPrice` and any previously derived `effectiveCost`.
- Missing/invalid units: preserve the raw amount without scaling. Unknown units,
  invalid prices, and unverified provenance keep affordability incomplete.
- A zero price alone is not proof of free admission. Source URL and verification
  date plus verified provenance are required to treat it as accounted-for free cost.
- Unit validity and price reliability are separate. Catalog/user estimates remain
  disclosed estimates, even with explicit units. Invalid traveller counts use one
  for safe arithmetic and keep per-person pricing incomplete.

Scheduling and `calculateBudget()` share effective group-cost calculation. Raw
activity prices are never overwritten with multiplied amounts; repeated generation
or recalculation cannot multiply a group total again. The existing scheduler checks
time/opening-hour feasibility, not budget feasibility. Budget comparison evaluates
the scheduled set using the same group costs and reports over-budget without
claiming that the scheduling algorithm optimized affordability.

Food/transport/spending-allowance categories and explicit `overlapsAllowance=true`
flag possible overlap. All amounts are retained; nothing is automatically deducted
from the RM60/person/day food or RM35/day group transport allowance. Unresolved
overlap keeps completeness conservative. Category alone cannot establish identical
expenditure. Shopping remains additional spending unless overlap is indicated.

The 35 existing catalog entries have no authoritative unit evidence in the local
audit ledger. All remain unchanged and unknown; no attraction is labelled verified
free or per-person based on its name. Historical raw snapshots are not migrated.
FR05 activity mapping, scheduled copies and FR11 plan conversion preserve these
optional fields. For newly priced Chat-to-Trip payloads only, `numberOfTravellers`
is also forwarded as FR05 `travellerCount`; legacy unpriced payloads retain their
existing numeric behavior. Existing B1B1 group-budget applicability rules continue
to apply.
