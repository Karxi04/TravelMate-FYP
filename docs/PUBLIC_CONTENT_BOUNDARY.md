# PU-1 public-content boundary

Before PU-1, standalone Flutter queried `tourism_packages`,
`promotional_campaigns`, and visible `feedback` documents directly. Those
documents also contained operator IDs, author IDs, moderation decisions, and
reviewer fields. Client-side filtering could not protect those fields because
Firestore rules authorize whole documents rather than selected fields.

PU-1 uses three server-authored projections:

* `public_tourism_packages/{id}`
* `public_promotional_campaigns/{id}`
* `public_destination_reviews/{id}`

The trusted Flask persistence boundary rebuilds or removes a projection after
every source write. A projection is replaced, never merged, so old private
fields cannot survive. Package and campaign projections are fail-closed when
approval, availability, campaign status, or the package relationship is not
eligible. Approved campaign date windows remain in the safe projection and
are evaluated at read time, so a future campaign becomes visible when its
start date arrives. F-R1 reviews require an affirmative moderation decision as
well as visible status; see LOCAL_REVIEWS.md for the coordinated Rules/client
and derived-projection rollout, including atomic owner revocation.

Expiry is a presentation policy: an expired campaign remains a safe historical
public record in its projection, while the cloud list, standalone list, and
package promotion sections exclude it as an active offer. A direct
authenticated projection read remains historical and does not make the
application present or apply an expired promotion as an active offer.

Source mutations revoke the affected projection before changing the canonical
document. Publication is then attempted from the committed source. If
publication fails, the mutation returns an error and the public document stays
removed; this is a deliberate fail-closed availability trade-off rather than
an atomic cross-document transaction.

The backend public routes build the same allowlisted contracts directly from
trusted source reads. Standalone Flutter reads only the projection
collections, while owner review CRUD continues to use the owner-authenticated
`feedback` path. The rules deny all traveller reads and writes to mixed
package/campaign sources, deny public-projection writes, and allow a traveller
to read only their own raw feedback record.

`backend_api/scripts/rebuild_public_content.py` is a dry-run-by-default,
idempotent rebuild tool. A future operator must supply `--apply --project
<explicit-project-id>` after rules are deployed and counts are reviewed. No
live rebuild or rules deployment is performed by PU-1. The tool removes stale
projection documents and reports counts without printing source records. Apply
mode re-reads each source immediately before publication and compares a
sanitized content fingerprint. A record changed by moderation during the run
is skipped instead of republishing the old snapshot; stale cleanup also
rechecks current eligibility before deleting a target document.

Required rollout is coordinated: deploy the backend projection writer, run the
dry-run against the isolated target project, review counts, run the explicit
apply, and stage the client that reads projections. Deploy the final rules with
that client release. Existing clients may temporarily lose shared content when
the raw-source deny takes effect; they must never regain raw reads as a
rollback. Previously downloaded data cannot be remotely recalled.

The current client uses full reads of the three projection collections, so no
new composite index is required. The source collections remain the canonical
operator/admin records; projection documents keep the same source IDs for
stable package, campaign, and review links.

PU-1V emulator verification used Firebase CLI 15.32.1, Java 21, and the
`demo-travelmate-pu1v` project ID on an isolated local port with synthetic
records. It exercised unauthenticated, traveller, operator, administrator,
owner-review, cross-owner, projection-read, projection-write, source-read, and
source-query decisions. This local emulator run does not verify deployed
Firebase rules.
