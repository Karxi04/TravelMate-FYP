# Small-locality discovery: strict and nearby

Alma, Machang Bubok, Bukit Mertajam, Kulim and George Town all resolve through the
existing validated catalogue. A recognised locality and a verified attraction
are different facts. Catalogue membership does not guarantee a provider result
or a match to a Traveller's preferences.

## Strict locality evidence

The shared validator keeps the existing country/state/coordinate conflict guards
and locality identity checks. Exact named locality evidence continues to work.
An attraction can also match a selected locality through an unambiguous,
explicit provider neighbourhood/suburb or a complete comma-separated address
component, checked against the same sourced locality ID and state. This path
requires valid coordinates as well. For example, an Alma neighbourhood/address
can coexist with a Bukit Mertajam postal city; the original city/address remain
unchanged. A street named Jalan Alma is not locality membership evidence.

A point near Alma, without explicit Alma locality evidence, stays out of strict
results. There are no asserted neighbourhood polygons or inferred boundaries.
These are recorded locality matches, not independent cadastral verification of
every provider address. Do not relabel a venue's city to make it pass.

## Explicit nearby search

The user must select **Explore nearby places (10 km)**. This performs a separate
search and clears the visible strict page. It is not an automatic fallback.

- Fixed radius: **10 km**, inclusive, from the selected locality's verified
  catalogue point; no client-supplied centre or arbitrary radius is trusted.
- Great-circle distance uses a 6,371 km sphere and verified Malaysian coordinates.
  Returned distance is rounded to two decimals; cards show one decimal and say
  **straight-line**. It is not road distance, travel duration or an area boundary.
- Missing/invalid coordinates, foreign records and conflicting state/coordinate
  evidence are excluded. Crossing a Malaysian state border is permitted within
  the distance bound, with the actual place's state/city/address retained.
- Nearby For You uses the unchanged 60/30/10 scores as its primary order and
  proximity for equal scores. Explore's default sort uses keyword relevance first and proximity
  within its relevance tier. Its ranking is separate from personal recommendations.
- No provider call is made just by typing, changing a location selection or
  viewing the nearby action. Existing per-search/page request limits remain:
  FR4 up to three requests per initiated generation, six per expansion lineage;
  FR3 one page request per initiated search/load-more action. All provider-backed
  tests use mocks. This batch made zero live attraction-provider requests.

## Scope and persistence

The existing locality ID and strict scope key are unchanged. Nearby search adds
`geographicMode: nearby`, `nearbyRadiusKm: 10`, `originScopeKey` and a separate
derived search key ending `:nearby:10km`. This is a new search scope, not a
migration of the underlying locality. Existing immutable snapshots are not edited.

Pinned nearby generations reopen under their stored nearby scope. A deliberately
conflicting strict-mode read is rejected. Default Home/For You reads skip nearby
generations so they do not replace the latest strict results. Scope-key values
reuse the existing indexes; no new Firestore index, Rules or schema deployment
is needed. Existing owner filters, bounded snapshot lookups, pagination, feedback
and expansion receipts remain in force.

Cached search remains bounded by the existing cache lookups; it does not promise
exhaustive nearby coverage, particularly across state borders. A provider may
return fewer matching places than exist in reality. Invalid or incomplete
metadata is not permission to fill results with invented attractions.

## Explore query meaning

- A complete recognised locality typed as the keyword while the search area is
  Malaysia, such as `Alma`, is interpreted as an attraction search scoped to Alma.
  The response reports `queryInterpretation: locality`, the canonical area and
  `queryUsed: tourist attractions`.
- With an explicitly selected area, the existing keyword semantics are retained.
  `Alma` in the Alma search area becomes `places to visit Alma` under that scope.
- `tourist attractions` with Alma as area is a normal attraction keyword search
  in that exact locality. The existing normalizer singularises it to
  `tourist attraction`; this does not broaden the scope.
- The adapter retains the existing MY/English Maps settings, source locality
  coordinates and map bias (11z). Nearby queries explicitly say
  `<keyword> near Alma, Penang, Malaysia`; the adapter does not add another
  `in ...` clause when that canonical area is already present. Strict queries
  retain `<keyword> in Alma, Penang, Malaysia`. Neither the map bias nor the provider's postal city
  establishes neighbourhood membership by itself.

## Diagnostics and empty/error states

FR4 snapshots/responses report provider requests/errors and these safe counters:

1. `rawProviderCount`: dictionary candidates returned across provider pages.
2. `geographicallyValidCount`: those records accepted by strict/nearby validation.
3. `geographicRejections`: counts by validation reason.
4. `tourismCandidateCount`: geographically accepted visitor-facing candidates.
5. `uniqueEligiblePoolCount`: deduplicated eligible provider/cache/previous pool.
6. `preferenceMatchCount`: candidates satisfying the selected discovery/threshold
   contract; `displayedCount` is the current page count.

Provider page counts precede merging/deduplication and may repeat the same venue
across queries. The unique pool may also contain cache/previous records; provider
counts are not the total cached inventory. FR3 additionally reports
`rawCandidateCount` including admin/fallback records and its final keyword/display
counts. Diagnostics contain counts/reasons, not tokens, user records or provider
URLs. Existing public source/provenance fields remain unchanged.

Empty provider responses, rejected exact-locality metadata and valid attractions
without preference matches have different status/messages. Provider failures use
a sanitized unavailable error. In particular, failure plus an out-of-area-only
fallback must not return an empty HTTP 200 success. A verified local fallback
can still be returned with its existing fallback provenance.

## Catalogue presentation compatibility

All 22,219 GeoNames-backed source records and stable IDs remain in the pinned
dataset. Raw `[GeoNames ...]` strings are removed from new suggestion labels.
Names/district/state distinguish entries where possible; indistinguishable
human labels are withheld from selectors rather than guessed or displayed as
duplicate choices. Legacy saved labels containing source IDs are validated
against that same ID and continue to resolve. Source attribution is retained.

## Test and acceptance boundaries

The deterministic fixtures use the actual catalogue points and explicitly fake
attraction names. They cover the five requested localities, postal/neighbourhood
evidence, strict rejection of proximity-only results, nearby distance/border
rules, empty/error/preference outcomes, stage counts, separate saved snapshots,
keyword semantics, deduplication and real widget taps. They do not establish
whether today's live provider returns any Alma attraction.

After separately authorised Backend and normal-app activation, retest Alma and
Machang Bubok strict search in For You and Explore. Inspect the response counts
before attributing an empty page to a specific stage. Initiate nearby search
explicitly and inspect the actual place address/city and straight-line distance.
Reopen the original strict snapshot to verify separation. Search/Refresh may
use provider credits and write caches/snapshots: obtain the separate live-test
approval before doing this in the owner's account. No new payment, trip save,
notification reconciliation, screenshot or APK reinstall is needed for source
verification.
