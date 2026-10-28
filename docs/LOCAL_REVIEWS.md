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

`screening` is additive private metadata: local Unicode normalization/tokenization,
lexical abuse, URL/unsafe-content and repetition flags, risk, method, timestamp and
content hash. This is deterministic rule-based NLP triage, not Gemini, a trained
toxicity model or a confidence score. All new/edited reviews await Admin approval,
including low-risk content. Failures become uncertain/pending; nothing is discarded
or falsely approved. Standalone writes have no server screening at submission;
the Admin queue computes current triage and persists it with the decision.

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
fallback. Destination Details shows external and TravelMate ratings separately.
Existing legacy projections without contribution keys need explicit refresh for
complete standalone historical deduplication. External ratings never enter totals.

## Coordinated rollout — not performed by this batch

Do not simply deploy new Rules over old clients. Stage backend, compatible SDK
client and Rules together; old direct SDK edits of approved sources will fail
closed without projection revocation. Legacy projection docs lack the approval
marker and will not be readable with new Rules until explicitly rebuilt.

Use the existing dry-run-by-default `backend_api/scripts/rebuild_public_content.py`
only after separate approval and an explicit target project/count review. It now
excludes pending/unmoderated reviews and republishes only existing affirmative
decisions using CAS. A derived-projection refresh is required, not a source-review
schema migration; no automatic approval, source rewrite or production rebuild is
authorized here. The tool also handles package/campaign projections, so any future
apply requires reviewing its complete existing scope before approval.

Emulator API/Rules acceptance and widget/HTML tests are not physical Vivo or
browser-to-browser UI E2E acceptance. Live services, Firebase Rules and production
records remain unchanged until separately authorized rollout.
