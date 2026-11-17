# Malaysian location catalogue

## Scope and provenance

The former 46-name locality table produced 60 selectable areas, including the
country and all 16 state/territory areas. It remains as a compatibility map for
existing snapshots and aliases. It was never a national gazetteer; Kulim was
absent from both that table and its selectable list.

The pinned GeoNames Malaysian country extract supplies 22,219 validated records:
populated places, administrative districts/subdistricts and named islands.
3,894 source records qualify for the fast list. After legacy identity merging,
the catalogue produces 3,910 fast candidates, including states and Malaysia.
The selector now presents 3,792: 118 entries whose remaining human-readable
labels cannot distinguish them are withheld from selection, without deleting
any geographic record or stable ID. The explicit extended lookup searches all
22,219 records locally first and applies the same presentation rule.
This measures included geographic records, not verified tourist attractions or
proof that every settlement in Malaysia is covered.

| State / federal territory | Records |
|---|---:|
| Johor | 1,858 |
| Kedah | 2,521 |
| Kelantan | 1,964 |
| Kuala Lumpur | 85 |
| Labuan | 45 |
| Melaka | 639 |
| Negeri Sembilan | 1,268 |
| Pahang | 2,206 |
| Penang | 739 |
| Perak | 1,701 |
| Perlis | 327 |
| Putrajaya | 2 |
| Sabah | 2,686 |
| Sarawak | 3,413 |
| Selangor | 1,094 |
| Terengganu | 1,671 |

Sources and licences:

- [GeoNames country extract and format](https://download.geonames.org/export/dump/readme.txt),
  [attribution and CC BY 4.0](https://www.geonames.org/about.html).
  The JSON records the download URLs, archive/admin-reference SHA-256 and counts.
- Existing pinned DOSM state polygons:
  `services/data/malaysia_states.source.json` records the exact source revision.
  [DOSM data licence](https://github.com/dosm-malaysia/data-open/blob/main/LICENSE.md).
  No polygon or coordinate was changed for this feature.
- Missing local entries can use the existing
  [Open-Meteo geocoding API](https://open-meteo.com/en/docs/geocoding-api),
  whose hosted geocoding data is **CC BY-NC 4.0**. It is separate from the raw
  GeoNames extract's CC BY 4.0 licence. Noncommercial FYP use is intended;
  review the hosted service's terms before commercial use. The Flutter selector
  links to both sources and shows the remote attribution when applicable.

## Validation and ambiguity

Country MY, source administrative state and the pinned state polygon must agree.
861 candidate records with conflicting/outside geometry and 39 without a usable
state/country were withheld. Historical/abandoned settlements are excluded by
feature code. Missing or conflicting coastal/island points remain unresolved;
for example, the old Semporna locality point is not replaced with a different
district centre to make it pass.

The single explicit source correction is Ampang (GeoNames 1735168). Its unchanged
point falls in Selangor while the source administrative code says Kuala Lumpur.
[MPAJ](https://www.mpaj.gov.my/en/contact-us) and the official
[KPKT local-authority directory](https://jkt.kpkt.gov.my/wp-content/d/sites/default/files/2021-12/Direktori_Portal_PBT_Mengikut_Negeri_Mei2021.pdf)
support Ampang Jaya's Selangor jurisdiction. The review file records this evidence,
removes the conflicting Ampang Hilir alias, and leaves district unknown.
No other conflicting record is silently reassigned using its point alone.

Exact legacy names keep their previous scope keys. New locations use
`my:geonames:<id>` and `geonames:<id>`. Same-named places require state/district
qualification; remaining identical labels are withheld instead of displaying
raw source IDs as separate choices. Existing source-ID-bearing saved labels
remain readable without rewriting records. A generic
prefix such as Bukit or Tanjung provides suggestions, not an automatic area.
District/region queries may use verified parent-district evidence; selecting a
town does not silently broaden to its district or state. Recognizing a locality
does not establish attraction availability, current opening hours or prices.

## Runtime contracts

- `/api/fr4/locations`: authenticated fast list; no geographic provider call.
  Existing authentication may read the profile as before.
- `/api/fr4/locations/search?q=...`: explicit extended lookup, up to 30 results.
  With `remote=true`, one existing Open-Meteo search is permitted only when the
  full local index returns no matches (MY filter, ten provider results, eight
  seconds). There is no per-keystroke call or automatic recommendation POST.
- A selected ID is checked against its label/scope. If a remote ID has left the
  bounded one-hour/128-entry public-data cache, generation may make one
  eight-second Open-Meteo ID lookup. It revalidates country, feature, state and
  coordinates. There is no retry loop or paid provider addition.
- Saved recommendations use their owned, validated snapshot scope; reopening
  does not require geocoding. Geographic candidate validation, cached scope
  separation, feedback and 60/30/10 ranking remain in their existing services.
- Explore explicit searches and FR11 attraction browsing share this resolver.
  Explore ranking stays separate. FR11 preserves browsing interests through
  clarification and view-first replies without asking itinerary questions.
  Expanded aliases require geographic language, protecting ordinary words,
  foreign intent and existing itinerary conversations.

No business-record migration, new Firestore index or Rules change is required.
Existing snapshots are not rewritten. A catalogue update may add/remove entries;
review compatibility and retain purchased/saved historical evidence separately.

## Updating

1. Download the public `MY.zip` and `admin1CodesASCII.txt` explicitly into an
   approved workspace folder. Keep the raw inputs out of Git.
2. Run `backend_api/scripts/build_malaysia_locations.py --geonames <MY.zip>
   --admin1 <admin1CodesASCII.txt> --output <candidate.json>`. The script uses only
   these local inputs, the pinned polygons and the versioned review file.
3. Compare counts, identities, raw-input hashes and withheld records. The Ampang
   guard fails if its upstream identity/name/admin code changes; recheck the
   official evidence before editing the review. Never approve all conflicts.
4. Review the candidate JSON, run `tests/test_malaysia_location_coverage.py`, the
   Malaysia/FR3/NLP/FR4 regressions and Flutter location tests, then replace the
   tracked JSON deliberately. Do not silently refresh it on app startup.

The initial inputs contained 71,710 features. Included rows retain GeoNames
modification dates; download hashes identify the exact build. State-level point
validation does not establish precise municipal/town boundary coverage.

## Acceptance boundaries

Sourced-data and mocked real-route tests verify resolution, strict Kulim
generation, snapshot separation, lookup errors and the exact T07 three-turn
conversation. They do not prove current provider attraction coverage or Vivo
behaviour. No live geocoding/SerpApi/Gemini request, production data change,
Backend restart, APK build/install or repeat T01-T06/T08 acceptance is needed
to run these tests. Activation and physical T07/autocomplete acceptance require
separate approval.
