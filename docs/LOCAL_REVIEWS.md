# TravelMate Local Reviews — F-R1

Existing `feedback` remains the source. New backend reviews use a SHA-256 identity
of authenticated UID + NUL + destination ID; existing source IDs are reused, never
migrated/deleted automatically. Exact POST retries return the persisted record;
different content requires explicit PUT. New creates use Firestore atomic create,
not read-then-set. Contention permits one read-back, never an unverified success.

Rating is integer1–5; comment5–2000 characters. Only rating/comment are editable.
Owner/name and timestamps are server-derived in API mode. Standalone direct writes
remain owner-scoped, pending-only and bounded by Rules; display name must match the
Auth token and no email fallback is used. A modified raw client can still create
alternate source IDs under existing standalone permissions; first-party clients
share the deterministic ID and API aggregates deduplicate historical owner records.
No automatic repair of historical duplicates or moderation decisions occurs.

`screening` is private metadata for abuse, URLs and unsafe content, repetition,
and rating/comment consistency. The lexical check handles common English and
Malay expressions and negation. It flags clear disagreement between 4–5 stars and
negative text, or 1–2 stars and positive text. Mixed comments and matching
negative reviews can have low risk. Weak disagreement and unrecognized wording
are marked uncertain. The evidence counts describe recognized expressions rather
than model confidence.

Every new or edited review awaits Administrator approval, including low-risk
content. The backend screens the effective rating and comment together, even
when only one field changes. Standalone writes still enter the pending queue
without server screening at submission. The Admin queue computes current triage
for these and other reviews and saves it with the Administrator's decision.

The synthetic Penang cases in
`backend_api/tests/fixtures/penang_synthetic_reviews.json` run through the FR10
route with in-memory storage. The George Town Street Art samples use its existing
demo fixture ID. Keep all samples in isolated development tests.

Existing enums remain: `feedbackStatus:visible` plus `moderationStatus:pending_review`
is private; `reviewed` (also readable legacy `approved`) is public; `removed` is
rejected/hidden. Only Admin keep/remove transitions publish/hide. Source and public
projection updates are transactional with a source-version/content comparison;
stale moderation cannot approve newer text. Rebuild publication uses the same CAS.

Public `public_destination_reviews` documents are allowlisted, carry
`publicationStatus:approved` and an opaque owner/destination contribution key, and
contain no UID/email/tokens/private screening or moderator notes. Public queries
must constrain the approval marker. Owners may never create/update projections;
the only client projection write is deletion paired with an owner source edit or
deletion. Rules require the projection absent after source mutation. This narrowly
scoped revocation preserves the existing ability to edit/delete one's own review
without granting publishing authority. SDK edits/deletes use the required batch.

The API computes averages/counts from approved valid feedback only and deduplicates
owner contributions; standalone pages approved projections in batches of10 and
deduplicates contribution keys. Unknown/empty local rating is null, never a provider
fallback. F-U1 uses only approved TravelMate ratings in destination presentation;
provider ratings remain metadata/internal ranking inputs, never a display fallback.
`GET /api/fr3/local-ratings` batches the same approved-source aggregation for all
cards. Standalone mode batches existing approved projections instead. The shared
Flutter lookup coalesces requests for 30 seconds; review edits/deletes/submissions
invalidate it and freshly loaded Details seed the same canonical destination ID.
Administrator changes are visible on Details refresh, or on the next card lookup
after the cache expires. Failed/unrated card lookups omit stars rather than imply0.
Existing legacy projections without contribution keys need explicit refresh for
complete standalone historical deduplication. External ratings never enter totals.

## Coordinated rollout — not performed by this batch

Do not simply deploy new Rules over old clients. Stage backend, compatible SDK
client and Rules together; old direct SDK edits of approved sources will fail
closed without projection revocation. Legacy projection docs lack the approval
marker and will not be readable with new Rules until explicitly rebuilt.

For reviews use `backend_api/scripts/rebuild_reviews_only.py`, not the broad
Package/Campaign rebuild. A derived-projection refresh is required, not a
source-review schema migration. No automatic approval or source rewrite is needed.
See the R-DEP1S gates below. No production inventory or apply is authorized/enabled.

Emulator API/Rules acceptance and widget/HTML tests are not physical Vivo or
browser-to-browser UI E2E acceptance. Live services, Firebase Rules and production
records remain unchanged until separately authorized rollout.

## Reviews-only migration safety — R-DEP1S

This release enables **only `demo-travelmate-f3p2v` on a loopback Firestore
emulator**, including for CLI inventory. Real-project execution remains denied;
never remove the guard to perform a release. Firebase App identity, environment,
Firestore client project, default database, anonymous credentials and actual SDK
emulator target are checked separately before collection access.

Dry-run reads only `feedback` and `public_destination_reviews`. Its version2
manifest includes project/database, exact affected IDs, planned creates/updates/
deletes, full-content hashes, F-R1 content revisions, Firestore update times,
typed complete projection before-images and derived after-images. Source fields
and Admin decisions are never mutated. `status:approved` alone is not approval;
only the existing visible + moderationStatus reviewed/approved contract applies.
Destination IDs remain exact. All historical source duplicates are retained.

Apply consumes the saved manifest, **does not replan**, and requires the reviewed
canonical SHA-256 digest plus a fresh backup path. It saves/fsyncs the complete
manifest/before-images before the first mutation. Every mutation transaction reads
both source and projection and checks existence, full content and update times;
changed/deleted/recreated records conflict, including orphan cleanup. It rebuilds
the desired allowlisted projection from the current source before writing. Extra
legacy fields are removed by replacement. Conflicts return CLI exit2, not success;
other errors abort. A run is per-document atomic, not globally atomic.

Example **emulator only**, from backend_api, with an existing protected D: folder:

```powershell
python -B scripts/rebuild_reviews_only.py --project demo-travelmate-f3p2v --manifest-path D:\workspace\TravelMate\verification\r-dep1s\reviewed-plan.json
# Human reviews exact IDs, counts, before/after images and printed digest first.
python -B scripts/rebuild_reviews_only.py --project demo-travelmate-f3p2v --apply --reviewed-manifest D:\workspace\TravelMate\verification\r-dep1s\reviewed-plan.json --manifest-sha256 <independently-reviewed-digest> --backup-path D:\workspace\TravelMate\verification\r-dep1s\before-images.json
```

The digest detects changes relative to the independently approved value; it is
**not an approval signature, credential or recoverable backup** by itself. The
before-images are typed Firestore JSON (including timestamps/bytes/references),
not lossy stringified values. They can contain private legacy fields: restrict
the parent directory to the release operator/approved reviewer, encrypt protected
storage, exclude Git/cloud-sync/public logs, and apply a retention policy. New files
are exclusive; POSIX permissions are0600. Windows inherited ACLs must be restricted
and verified separately; this utility does not certify Windows storage security.

### Future production authorization design — not enabled

A separately approved release must implement/test a release gate, not remove
project checks: independently reviewed exact manifest digest bound to project,
database, scope, source commit and expiry; named human approval stored outside the
editable manifest in protected release controls; an interactive confirmation of
that project/digest by the operator; short-lived least-privilege release credentials;
and the independent App/client/transport identity checks. Unattended invocations,
missing/expired approvals and mismatches must deny before network access. An env
variable or `--apply` alone must never authorize production. Approval storage/IAM,
protected backups and this production gate remain release prerequisites, not
features claimed implemented by the emulator-only tool.

### Maintenance and forward recovery

1. Separately authorize read-only inventory; identify actual loaded Backend/Admin,
   installed client versions, Rules and projection revisions. No production state
   was inspected in R-DEP1S. Resolve real browser/Android acceptance gates first.
2. Drain/freeze **all server review writers**, including Admin moderation, jobs and
   old backend instances. A backend toggle cannot freeze direct Firebase SDK writes.
   A separately reviewed temporary Rules policy must deny review source/projection
   client writes as well. Temporarily deny public-review SDK reads and block old
   review API read handlers while stale projections/old writers may remain; an
   approval marker alone cannot repair stale data. Keep other modules' permissions
   intact. Test queued/offline writes after reconnection.
3. Stage compatible Backend+Admin together. Make an explicit upgrade/outage decision
   for old standalone clients: new Rules deny their broad queries and source-only
   edits; do not weaken Rules to make them work. Keep review access frozen if client
   rollout fails. Stale Admin forms must be discarded/refreshed.
4. Under the freeze, capture protected before-images and approved manifest, then
   have one operator perform only separately authorized projection reconciliation.
   Competing migrations can exhaust SDK transaction retries on lock timeouts; they
   fail closed, not guarantee progress. Any conflict or
   partial failure keeps the review cutover gated; regenerate and independently
   review a fresh plan. Do not reuse an old approval digest for a new plan.
5. Activate final Rules and compatible client/backend together; verify approved-only
   reads, privacy, local counts, owner edit/delete revocation and stale moderation.
   Reconcile again before lifting **both** freezes. Rules alone do not constrain
   privileged Admin SDK writers. Rules/client/backend success is not projection success.
6. Recover **forward from current authoritative feedback**. Before-images support
   investigation, not blind restoration. Never restore an old public review merely
   because it was public before interruption: its owner/Admin may since have edited,
   hidden, rejected or deleted it. No restore command is provided. An interruption
   may leave some reviewed actions committed; the backup exists before any write,
   but is not a durable per-action completion journal. Compare current state and
   create a fresh reviewed delta. Do not roll back to unsafe old Rules/writers.

Mixed-version limitations remain: old Backend may publish pending content regardless
of Rules; old Admin forms lack reliable revision acknowledgement; old direct clients
with old Rules can leave stale approved projections after edits. New client + old
Rules cannot perform the required projection-revocation batch. New client + new
Rules hides legacy unmarked projections until refreshed. Cached content cannot be
recalled. No seamless mixed-version rollout is claimed.

Public API lists and aggregates deduplicate approved sources by owner; direct SDK
lists and aggregates deduplicate projections by reviewKey. However, the standalone
sort currently uses updatedAt only, whereas Backend also falls back to submittedAt.
For historical duplicates without updatedAt, the chosen card/contribution may differ
between modes. Migration preserves both source/projection IDs and does not invent
timestamps to mask this. A focused client compatibility fix/acceptance is a release
gate; Local Rating presentation is unchanged in R-DEP1S.
