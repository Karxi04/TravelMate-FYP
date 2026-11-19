# Batch I — Review trust, destination identity and planning reliability
Date: 19 November 2026 (Malaysia)

## Baseline and scope
Base: dccd76b706d7a0ebac4047bdf8e644dfb2c92d83, the verified merged PR87 integration HEAD.
Branch: batch-i-reviews-planning-reliability, based on the latest origin/travelmate-full-repair.
Read the actual merged source, workspace guidance and prior verification before editing.
PR83–86 reporting work is preserved. No service reload, APK build/install, production Firebase access, paid-provider request, payment, booking or live account/trip/review modification was performed.
Public official tourism pages were researched; this is different from a billed Maps/flight/hotel API request.
All generated test logs, the isolated Flutter runner, research receipts and comparison JSON are under D:/workspace/TravelMate/verification/batch-i-20261119.
The six original untracked paths remain outside the commit.

## Source causes and corrections
| Issue | Confirmed source behavior before | Correction and evidence boundary |
|---|---|---|
| A — review presentation | Destination Details explicitly rendered the large private-demonstration card. | Removed it. One Reviews list and normal cards remain. Authorized example content has one restrained application-level non-production indicator. A review-load failure remains visible as ordinary retry text. Automated PASS; Vivo pending. |
| B — ratings | Common badges existed but disappeared without a genuine average; the Details header had no badge. Provider IDs could obscure the canonical review key. | Shared star badge uses genuine approved average and count, in the header and Reviews, plus common Explore/recommendation/favourite cards. It renders Not rated yet instead of inventing a provider/local average. Review identity metadata resolves aliases. |
| C — national coverage | The planning-ready local catalogue had 36 records in eight regions. No authorized external review feed is configured. | Research inventory contains 400 sourced identities, 25 per region; 172 corroborated source-target pins. Complete-name lookup and details/review identity use the existing FR3 routes. Missing operational, pricing and scheduling metadata is disclosed. These records are NOT silently appended to the planning-ready catalogue. No genuine reviews or fictional customers are invented. |
| D — moderation | Crowds was negative even in avoid-crowds advice; no evaluative vocabulary made informational prose uncertain, and neutral content aligned only with 3 stars. | Advice context is distinguished from a negative experience. Explainable informational evidence permits a nonsuspicious neutral 4-star submission. Mixed, conflicting, abusive, repetitive and unsafe-link cases remain held. Policy version updated, without changing old moderation decisions. |
| E — edits | CAS protected stale writes but there was no lifetime edit counter. | Initial count zero; two meaningful edits; no-op free; third edit rejected; counter included in revision and transactional guard. UI displays remaining edits in both entry points. Legacy missing counters start at zero from this policy, without invented history. |
| F — duplicate places | The two reported address strings already match in the Backend helper. Flutter pagination checked only the primary ID. Alias-only saved records could appear unsaved after merging. | Merge supported identity aliases and same-name/consistent-geography records, retaining details and original references. Pagination and favourite matching recognize those aliases. Different temples/parking, different states and distant pins remain distinct. The phone's original exact payload was not recovered. |
| G — repeated experiences | Existing small repetition penalties could keep a run of high-scoring similar experiences at the top. Generic hill names had no concrete experience subtype. | After two repeated evidenced experiences, prefer available variety within ten hybrid points, within the existing selected-interest coverage pool. Do not infer strenuous hiking from hill/Bukit. Explicit specialized requests retain their intent. Original hybrid components and weights are unchanged. |
| H — generation recovery | HTTP202 became a failure; the recovery ID existed only in memory; initial creation used set rather than an atomic claim. Snapshot validation preceded reuse of completed results. | Atomic creation and CAS retry transition; pure owner-scoped GET status; durable owner-scoped request/input; bounded read recovery after timeout/202/contention. Successful recovery opens the same saved ID without reissuing generation. Expired/deleted old snapshots do not prevent reading a completed request. |
| I — budget actions | A protected visit suppressed every optional unpaid visit. Provider lookups could obscure independent planning actions. | Offer eligible unpaid visits independently; preserve protected costs/time references and reject changes that would move them. Budget adjustments stay reachable while replacement pricing loads; late lookups cannot replace the active preview. Paid orders/bookings/receipts remain outside the patch. |
| J — regenerate | Same deterministic catalogue/constraints returned the same plan; saved-plan regeneration could reuse the saved draft directly. | Deliberate regeneration excludes the previous attractions and aliases, retains constraints and uses the existing verified scheduler. Complete alternatives get a new draft version. Unavailable alternatives return an honest unchanged-draft explanation. Network retries retain existing receipt idempotency. |
| K — fulfilment alignment | Space-between flex rows put badges at different start positions. | Stable two-column CSS grid with a bounded proportional label column, wrapping labels and consistent gaps. Booking markup/status semantics are unchanged. Operator tests PASS; manual visual acceptance pending. |

## Ratings and provenance
Average = sum of approved genuine ratings / number of those same eligible contributions, rounded to one decimal.
The newest contribution per owner is considered before approval filtering, preventing an older duplicate approval from overriding a newer pending/removed record.
Only visible reviewed/approved finite ratings in 1–5 contribute. Pending, rejected, removed and synthetic rows do not.
Public TravelMate ratings do not silently combine provider scores or private examples.
Examples remain synthetic internally and authorized by the existing local demonstration contract.
The original 36+68 Penang fixture/import definitions are byte-for-byte unchanged. Current production record counts and decisions were NOT queried.
Local review mutations invalidate card caches; a Details reload remembers fresh genuine totals. Existing page batching and bounded caching remain.
No fixture rating is reclassified as a public visitor score to make an unrated destination look popular.

## Moderation and edit safety
The supplied Kek Lok Si text at 4/5 now classifies as neutral informational advice, with compatible rating and low nonsuspicious risk.
Avoiding crowds/heat does not erase separately expressed negative experience. Mixed experiences remain mixed.
Spam/unsafe links, abusive wording, repetition and genuine rating mismatches still prevent automatic approval.
Administrator approval/rejection remains authoritative and does not consume an edit.
Counters persist in the feedback source, not device settings. Owner checks and compare-and-set protect concurrent writes.
Both Backend revision and optional expected timestamp reject stale meaningful changes; an identical replay consumes no extra edit.
The standalone Firestore transaction and source Rules also enforce the counter.
Rules were NOT deployed and were NOT run against an emulator in this batch. Coordinated approval is required before deploying the Rules; older direct-Firestore clients must be upgraded for editing. Connected Backend clients remain compatible with optional precondition fields.
No old record is rewritten just to add editCount, rescreen text or change approval.

## State-by-state coverage
Counts below are research/source definitions, not assertions about live approved Firebase records.
Authentic counts are not audited rather than assumed to be zero.
Private counts are fixture definitions/import plans; they are not new seeded data or a count of current visible approvals.
| State / territory | Sourced identities | Corroborated pins | Authentic reviews | Private fixture definitions |
|---|---:|---:|---|---|
| Penang | 25 | 8 | Not audited | 104 in original plans |
| Kedah | 25 | 13 | Not audited | 3 code fixtures |
| Perlis | 25 | 7 | Not audited | 0 defined |
| Perak | 25 | 10 | Not audited | 0 defined |
| Selangor | 25 | 13 | Not audited | 3 code fixtures |
| Kuala Lumpur | 25 | 23 | Not audited | 3 code fixtures |
| Putrajaya | 25 | 9 | Not audited | 0 defined |
| Negeri Sembilan | 25 | 7 | Not audited | 0 defined |
| Melaka | 25 | 11 | Not audited | 3 code fixtures |
| Johor | 25 | 10 | Not audited | 3 code fixtures |
| Pahang | 25 | 10 | Not audited | 0 defined |
| Terengganu | 25 | 12 | Not audited | 0 defined |
| Kelantan | 25 | 8 | Not audited | 0 defined |
| Sabah | 25 | 13 | Not audited | 3 code fixtures |
| Sarawak | 25 | 10 | Not audited | 3 code fixtures |
| Labuan | 25 | 8 | Not audited | 0 defined |

Every identity carries an official primary source URL, explicit state/locality, category and canonical review identity. No provider ID, opening hours, available booking, price or review score is fabricated.
Coordinates come only from explicit source map targets that corroborate the declared state. Ten uncorroborated link/coordinate claims were withheld, including an official Labuan pin; their states/pins were not guessed.
Exact street addresses, current operations and complete planning metadata still require further evidence.
Original planning-ready records remain separate, so missing metadata cannot displace verified itinerary stops.
Sources are linked in backend_api/services/data/malaysia_attraction_identities.json: Tourism Malaysia state guides, Putrajaya authority, official Labuan tourism, and Tourism Perak's TT5 booklet. The booklet corrects a guide's printed DREGDE typo to the proper Tin Dredge No.5 identity.
No third-party review text was copied. New authentic reviews must come from real Traveller submissions or a separately authorized, attributed source.

## Recommendation evaluation
The scoring function, budget arithmetic and scheduler functions are AST-identical to the merged baseline; only diversification changed within domain_functions.py.
The formula remains 60% content + 30% collaborative + 10% popularity.
The 17-candidate frozen H.2 pool, labels and scores are unchanged; the same profile/constraints are used before and after.
P@k divides by k, so a small returned set is not falsely reported as perfect P@10.
| Frozen profile | Before P@5 | After P@5 | Before P@10 | After P@10 |
|---|---:|---:|---:|---:|
| Nature | 1.00 | 1.00 | 0.60 | 0.60 |
| Shopping | 0.40 | 0.40 | 0.20 | 0.20 |
| Nature + Shopping | 1.00 | 1.00 | 0.80 | 0.80 |
| Culture + Heritage | 0.60 | 0.60 | 0.30 | 0.30 |
| Food + Nature | 1.00 | 1.00 | 0.70 | 0.70 |
| Culture + Shopping | 0.80 | 0.80 | 0.50 | 0.50 |
| Three interests | 1.00 | 1.00 | 0.90 | 0.90 |
| Relaxed | 1.00 | 1.00 | 0.80 | 0.80 |
| Packed | 1.00 | 1.00 | 0.80 | 0.80 |
| Early riser | 1.00 | 1.00 | 0.80 | 0.80 |
| Night owl | 1.00 | 1.00 | 0.80 | 0.80 |
| Budget | 1.00 | 1.00 | 0.80 | 0.80 |
| Premium | 1.00 | 1.00 | 0.80 | 0.80 |

No label or score was adjusted to manufacture metric improvement. The frozen pool does not contain the reported dense run of hills, so its scores do not prove that phone failure fixed.
A separate hill-heavy ranking regression verifies no more than two hill visits in the first five when near-score beach/garden/waterfall alternatives exist.
Shopping coverage remains limited to its evidenced candidates. Closed attractions remain excluded by the scheduler; culture metadata limits are not relabelled away.

### Existing catalogue IDs and ranked results
Offline Penang comparison uses the existing 11 geographically accepted local records, with no provider/cache/account query.
Listed values are unchanged hybrid scores. Full category, experience, component, adjusted-score, scheduling, budget and coverage evidence is in recommendation-and-timing-comparisons.json on D:.

**Nature**

- Before: local_batu_ferringhi (62.8), local_botanical_gardens (62.8), local_penang_hill (62.8), local_chew_jetty (62.11), local_esc (62.11)
- After: local_batu_ferringhi (62.8), local_botanical_gardens (62.8), local_penang_hill (62.8), local_chew_jetty (62.11), local_esc (62.11)

**Nature + Shopping**

- Before: local_batu_ferringhi (62.8), local_gurney_plaza (62.8), local_penang_hill (62.8), local_botanical_gardens (62.8), local_chew_jetty (62.11)
- After: local_batu_ferringhi (62.8), local_gurney_plaza (62.8), local_penang_hill (62.8), local_botanical_gardens (62.8), local_chew_jetty (62.11)

**Culture + Heritage**

- Before: local_peranakan_mansion (68.3), local_kek_lok_si (64.18), local_food_tour (62.8), local_wonderfood (62.8), local_george_town (62.8)
- After: local_peranakan_mansion (68.3), local_kek_lok_si (64.18), local_wonderfood (62.8), local_food_tour (62.8), local_george_town (62.8)

**Food + Nature**

- Before: local_chew_jetty (64.18), local_gurney_plaza (62.8), local_batu_ferringhi (62.8), local_penang_hill (62.8), local_botanical_gardens (62.8)
- After: local_chew_jetty (64.18), local_gurney_plaza (62.8), local_batu_ferringhi (62.8), local_penang_hill (62.8), local_botanical_gardens (62.8)

**Shopping + Culture**

- Before: local_peranakan_mansion (68.3), local_gurney_plaza (62.8), local_kek_lok_si (64.18), local_food_tour (62.8), local_wonderfood (62.8)
- After: local_peranakan_mansion (68.3), local_gurney_plaza (62.8), local_kek_lok_si (64.18), local_wonderfood (62.8), local_food_tour (62.8)

**Photography + Nature**

- Before: local_botanical_gardens (65.55), local_penang_hill (65.55), local_chew_jetty (64.18), local_kek_lok_si (64.18), local_batu_ferringhi (62.8)
- After: local_botanical_gardens (65.55), local_penang_hill (65.55), local_chew_jetty (64.18), local_kek_lok_si (64.18), local_batu_ferringhi (62.8)

**Three interests**

- Before: local_peranakan_mansion (68.3), local_batu_ferringhi (62.8), local_gurney_plaza (62.8), local_kek_lok_si (64.18), local_botanical_gardens (62.8)
- After: local_peranakan_mansion (68.3), local_batu_ferringhi (62.8), local_gurney_plaza (62.8), local_kek_lok_si (64.18), local_botanical_gardens (62.8)

## Planning timing, timeout and recovery evidence
The existing client generation timeout remains 65 seconds. A client timeout is not evidence that the Backend failed.
Recovery uses at most five status reads, a 20-second overall recovery budget and an eight-second per-read await bound. Unknown delivery does not automatically replay POST.
Pending request identity and original input survive app restart in owner-scoped local storage; corrupted local state never initiates automatic creation.
A failed request can be explicitly retried with the same identity. An in-flight/completed request is read instead. Owned completed recovery bypasses obsolete snapshot validation.
An indefinitely generating record is not blindly restarted; the UI offers bounded status checking. Process-crash takeover still requires an authorized recovery decision.
Privacy-safe timings log candidates, location metadata, forecast, scheduling, budget and persistence; no tokens, owner IDs or conversation/review text.
For trips beyond a seven-day forecast horizon, FR5 no longer performs unusable geocode/forecast work.

Three warmed paired controlled runs: baseline median 777.08 ms; updated median 757.05 ms.
These use two injected 25ms mock provider waits in the baseline, not live provider latency. All runs schedule the same six fixture visits.
Updated future-trip runs make zero mocked weather provider calls. The original phone timeout and actual Firestore stage times are unverified.
The server logs, not timing fields on saved trips, carry diagnostics; existing generated-trip payload/pricing parity remains intact.

A delayed real Flask route with isolated persistence verifies one generation execution/one trip under concurrent POST, status reads and a repeat request after completion.
The widget test for a lost response verifies one POST plus one status GET, then opens that saved Trip.
A transition-conflict widget test verifies recovery without refreshing recommendations.
Partial/failed results are not accepted as a successful saved result solely because an HTTP request ended; the client requires the server's planned status and saved trip identity. Existing coverage/budget warnings remain intact.

## Budget alternatives and chatbot evidence
Synthetic RM200, RM900 and RM800 analogues preview a MYR40 allowance reduction without changing their input trip.
They are not the owner's original trip records. No new disposable live trip was created.
Existing preview/cancel/confirm, state-version checks, owner isolation, persistence/reopen tests and unavailable-price handling are retained.
The delayed-provider widget test opens Budget replanning, retains MYR200 food allowance after the late response, and performs no apply.
Removal cannot change retained paid arrangement cost or timing fields. Trip-level ambiguous payments remain conservatively protected.
Actual owner-trip eligibility/UI results remain pending an authorized runtime audit and explicit disposable-record acceptance.

Three sequential real-route chat regenerations use a 30-place verified-metadata fixture, produce distinct complete drafts, retain dates/group/budget/interests, and preserve previous messages/drafts.
An exhausted pool returns the prior draft unchanged with an explanation. No trip is saved automatically.
Existing receipt replay, stale-save, duplicate-save, owner and confirmation tests remain passing. This is mocked-provider Backend evidence, not Gemini or Vivo evidence.

## Verification
| Suite | Actual result |
|---|---|
| Full Backend | 3,627 passed; 2 existing emulator-only skipped; 30 integration deselected; 8 warnings |
| Full Flutter | 1,118 passed |
| Dart analysis | No issues found |
| Administrator | 108 passed |
| Operator | 213 passed |
| Post-review catalogue/regeneration focus | 10 passed after the sourced TT5 spelling correction and redundant-import cleanup |
| Real Firebase/emulator Rules execution | Not executed |
| Paid/live AI, Maps, flight, hotel providers | Not executed; official public website research only |
| Physical Vivo and manual browser visual checks | Not executed |

Focused counts overlap broad results and must not be summed.
Early failures remain in D: logs: incomplete runner fixture copies, source tests mocking set rather than the new atomic claim/CAS signature, the edit-counter contract, stale visual-label assertions, process-inherited push rollout settings, and one independently unconfirmed official pin.
The ranking rule initially applied before any repetition; tests caught it and the source now activates after two repeats.
No test was skipped, weakened or removed to hide an application defect. Exact monetary, ownership, moderation and frozen-score assertions remain.
The test-only conftest neutralizes inherited worker rollout/enabled flags; production config and notification source are unchanged.
Warnings include SDK/Python deprecations and socket attempts blocked by the isolated test harness.

## PR83–86 preservation and compatibility
Thirteen protected source/configuration hashes match the baseline. Reporting/export APIs, report modules, requirements including XlsxWriter, Administrator templates and Operator analytics are unchanged.
The Operator Bookings template outside its CSS style block is exactly unchanged.
PDF, compact/advanced CSV, Excel, bookings, analytics and moderation regressions are included in the passing suites.
No report source/aggregation/financial calculation or historical payment/order snapshot was changed.
Original Penang fixture bytes, all six untracked paths, credentials and local configuration remain preserved.
No database migration, seeding, Rules deployment, APK build/install, screenshot, recording, service restart or automatic merge was performed.

## Remaining acceptance and approvals
Automated source verification is PASS. Overall physical-device acceptance remains PENDING.
A protected Backend reload and a reviewed normal APK upgrade require separate authorization. Neither was performed.
The Rules source change needs separate reviewed deployment approval and emulator/direct-client acceptance before claiming standalone enforcement live.
Authentic state-by-state Firebase counts, current Penang moderation state, the phone's original failure and owner-budget-trip scenarios were not read or modified.
No external authentic review feed is configured; coverage research is not a substitute for real visitor submissions.
Current catalogue geographic conflicts, including the pre-existing Esplanade issue, remain flagged rather than silently reassigned.

### Focused owner-approved Vivo checklist
1. Verify the reviewed Backend/APK revisions after authorized rollout; preserve login/data.
2. Check one Reviews section, no destination demonstration box, and the restrained application-level indicator only in an authorized non-production context.
3. Compare genuine rating/count on Explore, Details, recommendations and favourites; verify unrated places. Refresh after moderation and confirm counts from the same approved set.
4. Use an approved disposable review: neutral-positive 4-star advice, mixed/spam negative controls, approve/reject, two edits, no-op, third edit rejection, reopen and second-account ownership.
5. Search Batu Caves across pages and source aliases; verify the main attraction appears once and distinct nearby temples remain distinct. Confirm an old saved alias still appears saved.
6. Search sourced attractions in several regions, including a pinless one; verify attribution and unavailable hours/prices remain explicit.
7. Generate approved Nature/Nature+Shopping profiles; inspect actual source metadata, balanced experience mix, geography and immutable saved generation.
8. With one separately approved disposable trip, test delayed-response recovery, app restart and concurrent Retry. Verify one saved trip and captured stage logs.
9. Audit the owner's RM200/RM900/RM800 eligibility read-only when authorized; preview/cancel/apply only a separately approved disposable case. Verify protected paid costs/unknown prices.
10. Regenerate a rich verified chat draft three times, inspect meaningful alternatives and unchanged constraints, and stop before Save unless separately approved.
11. Inspect fulfilment badges at desktop and narrow width; smoke-check PDF/CSV/XLSX and existing bookings without new transactions.

## Changed files
- backend_api/modules/fr03_destination_search_information/routes.py
- backend_api/modules/fr05_smart_itinerary_budget_planner/routes.py
- backend_api/modules/fr10_feedback_rating/routes.py
- backend_api/modules/fr11_chatbot_travel_assistant/routes.py
- backend_api/sequence_contract/domain_functions.py
- backend_api/services/data/malaysia_attraction_identities.json
- backend_api/services/destination_candidates.py
- backend_api/services/destination_research.py
- backend_api/services/recommendation_taxonomy.py
- backend_api/services/review_sentiment.py
- backend_api/services/review_service.py
- backend_api/services/trip_budget_replan.py
- backend_api/tests/conftest.py
- backend_api/tests/test_batch_i_discovery_budget.py
- backend_api/tests/test_batch_i_planning_recovery.py
- backend_api/tests/test_batch_i_reviews.py
- backend_api/tests/test_fr05_activity_pricing.py
- backend_api/tests/test_fr05_budget_aware_integration.py
- backend_api/tests/test_fr05_itinerary.py
- backend_api/tests/test_fr10_feedback_update_authorization.py
- backend_api/tests/test_security_hardening.py
- docs/BATCH_I_REVIEW_PLANNING_AUDIT.md
- firebase/firestore.rules
- operator_website/modules/fr12_tourism_operator_management/templates/fr12_tourism_operator_management/bookings.html
- traveller_mobile/lib/core/utils/destination_utils.dart
- traveller_mobile/lib/core/utils/recommendation_taxonomy.dart
- traveller_mobile/lib/main.dart
- traveller_mobile/lib/modules/fr03_destination_search_information/destination_details_screen.dart
- traveller_mobile/lib/modules/fr03_destination_search_information/explore_tab.dart
- traveller_mobile/lib/modules/fr03_destination_search_information/favourites_controller.dart
- traveller_mobile/lib/modules/fr05_smart_itinerary_budget_planner/alternative_screen.dart
- traveller_mobile/lib/modules/fr05_smart_itinerary_budget_planner/personalized_planning_screen.dart
- traveller_mobile/lib/modules/fr10_feedback_rating/feedback_screen.dart
- traveller_mobile/lib/services/review_contract.dart
- traveller_mobile/lib/services/shared_firestore_service.dart
- traveller_mobile/lib/services/transaction_request.dart
- traveller_mobile/lib/widgets/local_place_rating.dart
- traveller_mobile/test/alternative_screen_advice_test.dart
- traveller_mobile/test/batch_i_reviews_identity_test.dart
- traveller_mobile/test/destination_details_opening_hours_ux_test.dart
- traveller_mobile/test/explore_destination_experience_test.dart
- traveller_mobile/test/local_ratings_weekly_hours_test.dart
- traveller_mobile/test/local_reviews_test.dart
- traveller_mobile/test/package_chat_redesign_test.dart
- traveller_mobile/test/personalized_planning_flow_test.dart
- traveller_mobile/test/recommendation_scoring_truthfulness_test.dart
- traveller_mobile/test/traveller_batch1_regressions_test.dart
