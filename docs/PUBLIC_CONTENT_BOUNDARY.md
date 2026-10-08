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
start date arrives. Reviews follow the existing `feedbackStatus == visible`
policy.

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
projection documents and reports counts without printing source records.

Required rollout order is: deploy backend projection writer, deploy Firestore
rules, run the dry-run against the isolated target project, review counts, run
the explicit apply, then release the standalone client. Until that rollout,
existing installed clients may retain previously downloaded data; new clients
using these rules fail closed rather than falling back to raw collections.

The current client uses full reads of the three projection collections, so no
new composite index is required. The source collections remain the canonical
operator/admin records; projection documents keep the same source IDs for
stable package, campaign, and review links.
