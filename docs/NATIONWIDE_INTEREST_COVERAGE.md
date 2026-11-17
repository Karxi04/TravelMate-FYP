# Nationwide and multi-interest audit

Baseline is merged PR74, commit 15835b5d660e975cd6bb1f3d55e1aba406069466.
No provider requests or production data changes are needed for this audit.

## Existing process and demonstrated defects

Verified scope and strict/explicit-nearby filters precede the existing cache,
interest discovery queries, content evidence, similar-traveller feedback and
popularity scoring. Final score remains **0.60 content + 0.30 collaborative +
0.10 popularity**. Negative feedback is owner-scoped and removed before ranking;
preference fingerprints invalidate old suitability, not immutable generations.
Pagination reads a frozen generation; Discover More retains its scope and budget.

The existing diversity penalty is capped at seven points. It cannot bridge a
ten-point category score gap, so an eight-Nature/eight-Shopping stress pool can
return six Nature entries even with strong Shopping evidence. This is a list
composition defect, not proof that every existing real-world profile is wrong.
The existing weak-interest discovery queries already consider all canonical
interests and retain the three-call generation/six-call lineage limits.

Generic Nature branding on a provider-labelled shopping mall also produced a
false Nature match. Structured provider categories now protect against generic
brand words; explicit tags, distinctive offerings and separately verified evidence
can still support mixed interests. Nearby/address wording is not an offering.
Geographic area records with populated-place/admin feature metadata are excluded
from attraction candidates. No hours, prices or facilities are invented.

## Opt-in selection policy

Only For You discovery opts into `strong_interest_coverage_v1`; other callers keep
the old bounded-diversity behavior. Strong coverage uses existing **primary
metadata** and the existing **80/100 interest-signal** threshold already used for
supported profile terms. It does not use a new hybrid-score threshold.

During the first max(6, 2 × canonical interests) selections, choose the strongest
diversity-adjusted candidate for an underserved supported interest, aiming for
two distinct candidates per interest where possible. Mixed venues can serve more
than one interest when their evidence supports it. After this prefix, retain the
existing bounded diversity. Missing or weak categories are never invented or
forced into the prefix; this is not a universal 50/50 allocation.

Hybrid scores/components stay unchanged. `rankNo` is the **selection order**, not
a promise of descending hybrid scores. Selection policy/reason are recorded, and
Flutter explains the distinction. Existing matching-interest chips remain tied
to the scoring evidence. Empty-interest coverage is counted and disclosed without
silently changing the geographic scope. Nearby multi-interest results preserve
this composition rather than sorting it away by pure score.

## Geographic assessment

The 57-area matrix covers all 16 states/territories, with major towns, smaller
localities, islands, highlands and coastal/border examples. 56 requested qualified
names resolve; **Cheras, Kuala Lumpur remains unsupported by this pinned dataset**.
The available Cheras alias belongs to the validated Selangor record; it is not
silently substituted. This is a real coverage limitation, not a passing location
acceptance result. Tests assert safe refusal and report the omission separately.

Nearby is checked only where a verified centre exists. Semporna's previously
withheld coastal point stays withheld; state-only/hint centres do not become
neighbourhood coordinates. No geographic record, point or stable ID was changed.
Existing complete-catalogue tests validate every one of the 22,219 source points.
Mocked route tests cover strict/nearby generations, separate saved scopes,
deduplication, original addresses, empty pages and provider failure for the matrix.
They do not prove live attraction coverage for these areas.

## Frozen evaluation

Run `backend_api/scripts/nationwide_interest_evaluation.py` offline. It uses exactly
the same pool, context and previously frozen engineering category judgements for
both versions. Profiles A–F vary interests only; prior learning is neutralized.
The output includes pool/owner-label hashes, actual IDs, scores, Precision@5/10,
nDCG@10, coverage at 5/6/10, eligible counts, experiences, duplicate/incorrect counts,
pairwise Jaccard overlap and common-ID rank displacement. Scores are not calibrated
probabilities, and fictional engineering venues are not genuine visitor evidence.

The unchanged owner-reviewed Photography/Food fixture is evaluated separately.
No labels are revised after observing metrics. Precision gains are not promised:
the varied engineering pool already represents Nature/Shopping adequately; the
stress case isolates the capped-penalty failure. Compare quality, score loss and
coverage together rather than claiming production statistical improvement.

## Acceptance and remaining limits

Automated account/feedback, old snapshots, PR74 scopes, provider budgets, chatbot,
notifications, payment, hotel and flight regressions remain required. No live
provider, Firebase, service reload or APK acceptance is implied by these tests.

After separate approval: verify runtime/app identity; use an authorized isolated
account and one frozen destination/pool with A–F profiles; compare actual IDs,
scores, matching chips and coverage notices. Confirm Nature/Shopping representation,
sparse-category explanations, strict/nearby labels and frozen Load More. Do not
edit the owner's interests or create production snapshots without exact approval.
Proposed minimal provider sample is one approved strict search each for a west
coast town, an east-coast town and an East Malaysian city (up to three calls per
generation), followed by cache-only profile comparisons. Obtain a concrete cap
before execution; do not run all 57 locations live.
