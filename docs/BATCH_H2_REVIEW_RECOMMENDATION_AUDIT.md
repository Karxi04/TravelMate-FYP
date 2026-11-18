# Batch H.2 — Unified reviews and recommendation quality audit

Base: 6371a4f3a269d8e3bc74f35865e22d65853b411a, including merged PR83–PR86.

## Review contract and preservation

Destination Details now requests one unified response and renders one Reviews list with the existing card design. There is no review switch or dataset selector. A single page-level private-environment notice appears outside the cards when the server authorizes local demonstration content.

The Backend requires the existing trusted-LAN local-demo configuration, authenticated Traveller role and review-context header before adding private examples. Ordinary responses remain genuine-only. A client marker alone cannot enable server access. Existing UID-only legacy preview access is not expanded. The old explicit test endpoint remains solely for backward compatibility; the new UI never requests it.

Genuine rating/count fields remain calculated only from approved genuine submissions. Private example aggregates remain separately tagged in sampleSummary. Every projected example row retains synthetic=true and source=fyp_private. The mixed list never enters the genuine rating cache as a combined average. The global notice explains this distinction without repeating labels inside cards.

All 12 original Penang manifest identities, including historical non-local IDs, are recognized without changing them. The immutable 36 base and 68 expansion fixture files, create-only plans and private moderation overlay logic are unchanged. Existing moderation determines visibility; pending/flagged/removed rows are not forced into the list. Private-example read failures preserve genuine results and report example unavailability without exposing exception details.

Regional fixtures are still code-resident, read-only synthetic examples screened by the real FR10 policy. Three new verified catalogue identities extend coverage to Selangor, Melaka and Sarawak. No records were seeded. These regional rows are not live editable customer records or newly provisioned Firestore moderation records.

Production Firestore was not queried. Preservation here is source/hash and controlled integration evidence, not a fresh live audit of the 104 private review documents or current moderation counts.

## State-by-state fixture coverage

| State / territory | Existing canonical example destinations | New regional fixture rows |
|---|---|---|
| Penang | demo_penang_street_art, entopia, local_batu_ferringhi, local_botanical_gardens, local_chew_jetty, local_kek_lok_si, local_penang_hill, local_peranakan_mansion, local_wonderfood, penang_armenian_street, penang_gurney_drive, tropical_spice_garden | 0; existing 104-review plan retained |
| Kuala Lumpur | local_klcc | 0 |
| Selangor | local_batu_caves | 3 |
| Johor | local_legoland_malaysia | 0 |
| Kedah | local_langkawi_skycab | 0 |
| Perak | No verified canonical attraction in the current local catalogue; no fabricated identity/review added | 0 |
| Sabah | local_tunku_abdul_rahman | 0 |
| Sarawak | local_sarawak_cultural_village | 3 |
| Melaka | local_a_famosa | 3 |
| Pahang | No verified canonical attraction in the current local catalogue; no fabricated identity/review added | 0 |
| Negeri Sembilan | No verified canonical attraction in the current local catalogue; no fabricated identity/review added | 0 |
| Terengganu | No verified canonical attraction in the current local catalogue; no fabricated identity/review added | 0 |
| Kelantan | No verified canonical attraction in the current local catalogue; no fabricated identity/review added | 0 |
| Perlis | No verified canonical attraction in the current local catalogue; no fabricated identity/review added | 0 |
| Putrajaya | No verified canonical attraction in the current local catalogue; no fabricated identity/review added | 0 |
| Labuan | No verified canonical attraction in the current local catalogue; no fabricated identity/review added | 0 |

The seven regional destinations contain 21 rows total (12 existing +9 added). Together with the original private Penang plan this is eight covered regions. Perak, Pahang, Negeri Sembilan, Terengganu, Kelantan, Perlis, Putrajaya and Labuan remain data-coverage gaps. Adding authoritative venue identities and licensed/genuine review content is separate from inventing testimonials.

Batu Caves had a real text/coordinate conflict: the existing pin was in Selangor but its catalogue state/address said Kuala Lumpur. Only address/state/city metadata was corrected; coordinates and canonical ID are unchanged. Official source: https://www.malaysia.travel/explore/batu-caves . The existing Esplanade unsupported-coordinate conflict remains flagged; no coordinate was guessed.

## End-to-end recommendation trace

1. FR2 stores the authenticated questionnaire fields: interests, travelPersonality, travelType, travelPace, sleepingType, travelPurpose and budgetRange. FR4 retrieves the owner preference, applies owner feedback/learned affinities and fingerprints preference versions; it does not write different interests during these tests.
2. destination_candidates and recommendation_discovery obtain candidates from the existing approved cache/provider/local catalogue paths. Query planning assesses coverage of every selected interest under the existing bounded provider budget. No provider request was made in this batch.
3. Tourism eligibility rejects residential/administrative/industrial and other non-visitor service functions. malaysian_locality validates exact locality/state/coordinates before ranking and again before delivery. Venue identity deduplication remains in the existing shared service.
4. recommendation_taxonomy derives concepts from supported provider IDs, category/name evidence and bounded descriptions; nearby amenities and unsupported marketing are not newly asserted as facts. domain_functions applies existing interest/style/pace/budget/purpose/personality signals. Missing evidence stays neutral rather than being invented.
5. The hybrid formula is unchanged: 60% content, 30% collaborative and 10% popularity. Collaborative evidence still respects peer similarity and self/duplicate boundaries. New provenance screening excludes explicit synthetic rows before they can affect confidence or suppress older genuine evidence.
6. Existing bounded diversity penalties and strong-interest coverage remain. Specific experiences are now recognized from factual names when type/category are only generic Nature/Culture/Shopping labels; explicit provider types continue to take precedence.
7. FR4 saves the owned generation with planning preferences and coverage diagnostics. The immutable snapshot storage/generation/pagination contracts are unchanged. The audit asserts the linked snapshot is unchanged by itinerary generation.
8. FR5 propagates the linked planning preferences and applies existing tourism/geographic filters, trip-wide identity rules, local-day/physical-effort constraints, opening hours, travel estimates, numerical group budget and daily capacity. Budget-aware selection, when enabled, retains its own existing limits and evidence requirements.
9. FR11 filter_constraint_candidates reuses the same tourism gate. Its structured planner calls the same content/collaborative/hybrid functions and itinerary services. Existing guided-planning/history/save APIs are unchanged.

## Proven defects and corrections

- Provider-only government categories were omitted by the Backend administrative-facility gate, although Flutter already inspected them. A generic Nature Service Centre with local_government_office could become an eligible Nature match. The Backend now evaluates provider IDs. Banks, car-repair services and real-estate agencies are also excluded by their explicit venue function, with Flutter parity. Museums, gardens, restaurants and actual shopping venues remain eligible. Provider vocabulary reference: https://developers.google.com/maps/documentation/places/web-service/legacy/supported_types .
- Broad repeated metadata (Nature as both type and category) lost hiking/garden/beach experience distinctions. The existing diversity penalty had insufficient experience evidence. Generic-category names now supply only concrete experience types, without changing relevance scores, weights or adding venue-specific exceptions.
- The shared collaborative scorer could accept an explicitly synthetic published feedback row if passed to it with peer evidence. It now uses the existing genuine_review predicate before deduplication. A newer fictional row cannot hide an older genuine contribution.
- Batu Caves geography correction described above removes a genuine source metadata conflict rather than bypassing the geographic guard.

## Frozen comparisons

The committed fixture contains synthetic evaluation metadata and independent relevance judgements, not a replacement production catalogue. Baseline code is extracted from the verified base revision for the eligibility/experience functions, while the unchanged scoring and scheduling code uses identical inputs. Labels were not retuned after observing metrics.

The initial MYR 180 two-day/two-person setup could not cover the existing subsistence estimates even with free attractions. Before running the paired comparison, the common budget was set to MYR 700 and the 180 case retained as an explicit boundary test. This corrects the evaluation setup without changing production prices, formulas or frozen relevance judgements.

Precision@k below uses denominator k. The JSON also records precision among the actually returned results; fewer than k good candidates are reported without irrelevant padding. Closed Museum remains a conservative negative in the frozen labels: it is culturally relevant but unavailable under its stated hours, and scheduling correctly defers it. This keeps culture metrics honest rather than relabelling the fixture to obtain 100%.

| Profile | P@5 before → after | P@10 before → after | Scheduled before → after | Missing interests after |
|---|---|---|---|---|
| Nature | 0.80 → 1.00 | 0.60 → 0.60 | 5 → 4 | None |
| Shopping | 0.40 → 0.40 | 0.20 → 0.20 | 2 → 2 | None |
| Nature + Shopping | 0.80 → 1.00 | 0.80 → 0.80 | 6 → 6 | None |
| Culture + Heritage | 0.60 → 0.60 | 0.30 → 0.30 | 3 → 3 | None |
| Food + Nature | 0.80 → 1.00 | 0.70 → 0.70 | 6 → 5 | None |
| Culture + Shopping | 0.80 → 0.80 | 0.50 → 0.50 | 5 → 5 | None |
| Three interests | 0.80 → 1.00 | 0.90 → 0.90 | 6 → 6 | None |
| Relaxed | 0.80 → 1.00 | 0.80 → 0.80 | 4 → 4 | None |
| Packed | 0.80 → 1.00 | 0.80 → 0.80 | 7 → 6 | None |
| Early riser | 0.80 → 1.00 | 0.80 → 0.80 | 6 → 6 | None |
| Night owl | 0.80 → 1.00 | 0.80 → 0.80 | 6 → 6 | None |
| Budget | 0.80 → 1.00 | 0.80 → 0.80 | 6 → 6 | None |
| Premium | 0.80 → 1.00 | 0.80 → 0.80 | 6 → 6 | None |

The companion JSON evidence records eligible IDs, independently relevant candidates by interest, the ranked candidates and unchanged score components, selected IDs, each scheduled activity/day/time/travel leg/cost, deferred reasons, group budget evidence and missing-interest coverage. The fixture file provides provider category IDs, coordinates, hours, costs and source meaning for each candidate.

All compared schedules have zero duplicate destination IDs, keep local travel legs below 10 km in this synthetic cluster, defer the closed museum and stay within the 700 numerical budget. The180 boundary correctly reports both interests unrepresented rather than pretending free admission eliminates transport/subsistence costs. Early riser starts at 08:00 and Night owl at 11:00 in this pool. The results establish bounded offline behavior, not nationwide live provider accuracy.

Live catalogue coverage is limited: the current 36-record local fallback catalogue spans eight regions. Its ratings/review counts are not treated as verified provider feedback by FR4. Many candidates lack defensible personality/purpose/budget metadata or full dated opening schedules. Those signals cannot safely guarantee different rankings or known final spending. Provider completeness and actual trip travel-time estimates remain runtime evidence limits.

## Acceptance and safety

Backend, Flutter, analysis, Administrator and Operator suite results and the PR/commit are recorded in the completion verification report. Existing review submission/edit/duplicate/screening/approval/removal/history/ownership tests remain part of the full suite. Real Firestore/emulator/physical-device results are stated separately; no simulated result is labelled Vivo PASS.

Protected reporting/export modules, interfaces, XlsxWriter requirement and reporting tests from PR83–PR86 are unchanged. Full suites include PDF/CSV/XLSX exports and Operator bookings/analytics regressions. The protected services, credentials, configuration and six original untracked paths are preserved.

### Focused Vivo checklist after an approved rollout

- Open Penang Hill and a historical-ID Penang destination: one Reviews section, no switch, approved examples visible automatically only in the authorized demo context.
- Repeat with the second account/new test registration. Verify a single page-level environment notice and no repeated labels inside cards.
- Open Johor LEGOLAND, Selangor Batu Caves, Melaka A Famosa and Sarawak Cultural Village, then reopen/refresh. Confirm correct venue/state and stable cards.
- With ordinary non-demo configuration/context, verify only genuine approved reviews and genuine rating aggregates.
- Use an approved disposable review to verify submission/editing, duplicate protection, flagging and admin moderation. Do not alter existing owner records.
- Compare Nature, Shopping and a mixed profile using authorized isolated data. Inspect varied experiences, coverage explanations, distances, opening hours and costs before confirming a save.
- Verify saved generation ownership and no duplicate or incomplete itinerary save. No payment, service restart or APK installation is authorized by this checklist.

## Executed verification

| Layer | Final result |
|---|---|
| Backend default regression suite | 3,602 passed, 2 pre-existing emulator-only skips, 30 integration tests deselected |
| Flutter full suite | 1,108 passed |
| Dart analysis | No issues found |
| Administrator website | 108 passed |
| Operator website | 213 passed |

The full Backend suite includes the PR83–PR86 PDF, legacy/readable/compact CSV,
XLSX, commerce reporting, authorization and Operator analytics tests. Reporting
modules, website templates, export routes and XlsxWriter requirement remain unchanged.
The two existing disposable-emulator cases were not executed; no emulator
integration or physical Vivo PASS is claimed.

The first broad Backend run found two assertions that still required identical
demo/public lists and repeated street-art retrieval. Their updates retain exact
genuine rows/aggregates, explicit private provenance and bounded provider calls.
The original independent relevance labels were not changed. Both focused cases
and the subsequent complete suite passed. Logs and detailed comparison JSON are
in the task's D-workspace verification directory.

Live Firebase existence/moderation state and normal Vivo acceptance remain
pending a separately authorized rollout/audit. The current environment was not
restarted and no APK was built or installed.
