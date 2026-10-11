# TravelMate Firebase Hosting portal preparation

This preparation maps two **provisional** Firebase Hosting targets to the existing portal Cloud Run services. It creates or deploys nothing by itself.

| Hosting target | Confirm in Firebase Console before deployment | Expected URL after creation | Cloud Run rewrite |
| --- | --- | --- | --- |
| `operator` | `travelmate-operator-ckx` | `https://travelmate-operator-ckx.web.app` | `travelmate-operator` in `asia-southeast1` |
| `admin` | `travelmate-admin-ckx` | `https://travelmate-admin-ckx.web.app` | `travelmate-admin` in `asia-southeast1` |

The Hosting public directory is deliberately empty. Its `**` rewrite forwards every request, including `/`, `/static/...`, form POSTs, and Flask redirects, to the relevant Cloud Run portal. The browser remains on its own `.web.app` origin, so existing same-origin Flask sessions, secure `Lax` cookies, CSRF tokens, relative redirects, CSS, and JavaScript paths continue to work. Do not add an `index.html` there.

The Android application does **not** use Hosting. Set its release `API_BASE_URL` to the public `https://...run.app` API URL after API deployment.

## Preconditions — manual and approval-gated

1. In Firebase Console for `travelmate2-30a8a`, open **Hosting** and create two additional sites only after approval. Confirm the actual IDs exactly match the provisional IDs above. If Firebase rejects either ID or assigns a different value, update the matching `.firebaserc` target before deployment; do not deploy it to the wrong site.
2. In Google Cloud Console, link billing and enable Cloud Run, Cloud Build, Artifact Registry, Secret Manager, Firebase Hosting, Firestore, and Firebase Authentication APIs. These actions can create billable usage.
3. Create Artifact Registry repository `travelmate` in `asia-southeast1`, the service accounts named in the Cloud Run templates, Secret Manager secrets documented in [CLOUD_RUN_DEPLOYMENT.md](CLOUD_RUN_DEPLOYMENT.md), and the Firestore TTL policy for collection group `rate_limit_windows`, field `expiresAt`.
4. Keep Cloud Run `minScale: 0`. The supplied maximums are API `2`, Operator `1`, and Admin `1`; they are capacity/cost caps, not abuse protection. Keep the API’s transactional Firestore limiter enabled and fail-closed.

## Cloud Shell deployment sequence — approval required

Use browser-based Cloud Shell. It uses Cloud Build for image creation; do not install Docker or Google Cloud CLI on Windows. Run only after the prerequisites above are complete and approved.

```bash
PROJECT_ID=travelmate2-30a8a
REGION=asia-southeast1
REPOSITORY=travelmate
TAG="$(git rev-parse --short=12 HEAD)"
gcloud config set project "$PROJECT_ID"

# Builds the existing three Dockerfiles remotely. This is billable-capable.
gcloud builds submit --config=cloudbuild.yaml \
  --substitutions="_REGION=$REGION,_REPOSITORY=$REPOSITORY,_IMAGE_TAG=$TAG" .

API_IMAGE="$REGION-docker.pkg.dev/$PROJECT_ID/$REPOSITORY/travelmate-api:$TAG"
OPERATOR_IMAGE="$REGION-docker.pkg.dev/$PROJECT_ID/$REPOSITORY/travelmate-operator:$TAG"
ADMIN_IMAGE="$REGION-docker.pkg.dev/$PROJECT_ID/$REPOSITORY/travelmate-admin:$TAG"

# Render only temporary Cloud Shell manifests; never commit rendered files.
sed -e "s/PROJECT_ID/$PROJECT_ID/g" -e "s|IMAGE_URI|$API_IMAGE|g" \
  deploy/cloudrun/services/travelmate-api.yaml.template >/tmp/travelmate-api.yaml
sed -e "s/PROJECT_ID/$PROJECT_ID/g" -e "s|IMAGE_URI|$OPERATOR_IMAGE|g" \
  deploy/cloudrun/services/travelmate-operator.yaml.template >/tmp/travelmate-operator.yaml
sed -e "s/PROJECT_ID/$PROJECT_ID/g" -e "s|IMAGE_URI|$ADMIN_IMAGE|g" \
  deploy/cloudrun/services/travelmate-admin.yaml.template >/tmp/travelmate-admin.yaml
gcloud run services replace /tmp/travelmate-api.yaml --region="$REGION"
gcloud run services replace /tmp/travelmate-operator.yaml --region="$REGION"
gcloud run services replace /tmp/travelmate-admin.yaml --region="$REGION"
```

Before serving traffic, use Cloud Run Console’s environment-variable and Secret Manager-reference UI to apply the corresponding `deploy/cloudrun/*.env.example` values. Keep every provider and session value as a Secret Manager reference; set `APP_ENV=production`, `FALLBACK_MODE=false`, and `SESSION_COOKIE_SECURE=true` for both portals. Fetch the API service URL, then set both portal `BACKEND_URL` values and the API’s Stripe success/cancel return URLs to public HTTPS values. Set API `CORS_ALLOWED_ORIGINS` to the two confirmed `.web.app` origins. Do not place a private, localhost, emulator, or LAN address in any deployed value.

After Cloud Run validation, make the services publicly invokable, then deploy only the configured Hosting targets:

```bash
for SERVICE in travelmate-api travelmate-operator travelmate-admin; do
  gcloud run services add-iam-policy-binding "$SERVICE" --region="$REGION" \
    --member="allUsers" --role="roles/run.invoker"
done

npx --yes firebase-tools@latest deploy \
  --only hosting:operator,hosting:admin --project "$PROJECT_ID"
```

Validate `https://travelmate-operator-ckx.web.app/health` and `https://travelmate-admin-ckx.web.app/health`, then verify anonymous login-page access and a signed-in POST form in each portal. Finally configure Stripe **test-mode** webhook delivery to the API Cloud Run URL—not either Hosting URL.

## Security and cost notes

- Hosting rewrites do not remove the need for public Cloud Run ingress: Hosting reaches the public portal services, and the Flutter app and Stripe use the public API service.
- Operator and Admin retain different cookie names and session secrets. Do not reuse the API/provider secrets in portal services.
- Hosting and Cloud Run can use free quotas, but enabling billing, Cloud Build, Artifact Registry, Cloud Logging, Firestore, network egress, Secret Manager, and external providers can incur charges. Set a low monthly budget and 50%, 90%, and 100% alerts before deployment.
- Firestore TTL deletion is asynchronous. The rate limiter remains correct because its transaction evaluates the stored expiry; TTL only bounds retained documents.

## References

- Firebase Hosting rewrites to Cloud Run: https://firebase.google.com/docs/hosting/cloud-run
- Firebase Hosting multiple sites: https://firebase.google.com/docs/hosting/multisites
- Cloud Run scale settings: https://cloud.google.com/run/docs/configuring/services/min-instances
