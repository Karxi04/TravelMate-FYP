# TravelMate Cloud Run deployment preparation

This document prepares deployment only. Do not run the commands until Phase 1B is approved.

## Architecture

Deploy three independent public HTTPS Cloud Run services in one region:

| Service | Image | Public URL use |
| --- | --- | --- |
| `travelmate-api` | `backend_api/Dockerfile` | Flutter API, portal API client, Stripe webhook/return endpoints |
| `travelmate-operator` | `operator_website/Dockerfile` | Operator browser portal |
| `travelmate-admin` | `admin_website/Dockerfile` | Administrator browser portal |

Firestore remains the persistent application store. Cloud Run local files are not persistent and must not store accounts, orders, uploads, or secrets. The API service account uses Firebase Admin/Firestore; the mobile application continues to use Firebase Authentication with its existing client configuration.

## Required manual setup

1. Create or select a Google Cloud project with billing enabled. Enable Cloud Run, Cloud Build, Artifact Registry and Secret Manager.
2. Create an Artifact Registry Docker repository named `travelmate` in the selected region.
3. Create a dedicated Cloud Run API service account with only the Firebase/Firestore permissions needed by this project. The backend already supports Application Default Credentials, so do not upload a Firebase private-key file into an image.
4. Put these values in Secret Manager: Firebase Admin JSON only if Application Default Credentials cannot be used, SerpApi, LiteAPI, Stripe **test** secret, Stripe webhook secret, Gemini key, and independent Operator/Admin session secrets.
5. Build the three images with `cloudbuild.yaml`, then deploy them with immutable image tags. Set Cloud Run secrets as runtime secret references, not literal environment variables in Git.
6. Deploy API first. Use its public HTTPS URL for both portal `BACKEND_URL` values and the Flutter release `API_BASE_URL`. Production portal and Flutter guards reject localhost, emulator, and private-LAN values.
7. After the API URL exists, configure exact Stripe test-mode success/cancel URLs and register `https://API_URL/api/fr9/webhooks/stripe` in Stripe. Copy Stripe's signing secret into Secret Manager.
8. Deploy both portals with `APP_ENV=production`, secure cookies, and their own HTTPS URLs. Update API CORS only if browser API access is later required; current portal calls are server-to-server.
9. Restrict the Firebase client API keys to the registered Android application/package certificate and required Firebase APIs. Keep Firestore rules deployed separately only after review.

## Cloud Run settings

- Public ingress is required for the API webhook/returns and portal browser traffic. Authentication remains in TravelMate's Firebase/portal layers; do not place Cloud Run IAM authentication in front of the public API.
- Use request timeout 120 seconds to match the existing Gunicorn configuration. Set a conservative maximum instance count before provider testing.
- Start at zero minimum instances for the FYP pilot. A minimum instance reduces cold starts but adds idle cost.
- Current request limiting is process-local. Do not treat it as a global abuse limit once Cloud Run scales; Phase 1B needs an explicitly approved shared limiter or edge policy.
- No background reconciliation worker exists. Current payment/hotel reconciliation is request-driven; do not claim background processing until it is designed and deployed.

## Secret mapping

Use Cloud Run `--update-secrets`, not an env file, for these values:

| Service | Environment variable | Secret Manager secret |
| --- | --- | --- |
| API | `SERPAPI_KEY` | `travelmate-serpapi` |
| API | `LITEAPI_KEY` | `travelmate-liteapi` |
| API | `STRIPE_SECRET_KEY` | `travelmate-stripe-test` |
| API | `STRIPE_WEBHOOK_SECRET` | `travelmate-stripe-webhook` |
| API | `GEMINI_API_KEY` | `travelmate-gemini` |
| API | `FIREBASE_SERVICE_ACCOUNT_JSON` | `travelmate-firebase-admin` only if service-account ADC is unavailable |
| Operator | `SECRET_KEY` | `travelmate-operator-session` |
| Admin | `SECRET_KEY` | `travelmate-admin-session` |

## Cost and operations

Cloud Run is pay-per-use and requires a billing-enabled project. It has a monthly free usage allowance, but Cloud Build, Artifact Registry, network egress, Secret Manager, provider usage, and minimum instances can incur separate charges. Stripe test mode has no card charge, but provider quotas still apply. Set a budget alert before deployment.

Cloud Run instances may restart or scale to zero; Firestore keeps user/order records through restarts. Never rely on container files. Keep secrets in Secret Manager, rotate them after exposure, use Cloud Logging with request/error redaction, and retain Stripe webhook delivery logs for the FYP acceptance record.

## Phase 1B command sequence — approval required

The following is intentionally not executable without replacing placeholders and using a real Google Cloud project. It creates paid-capable cloud resources and must be approved separately:

```powershell
# After user approval only: build images, deploy travelmate-api, then deploy the two portals.
gcloud builds submit --config cloudbuild.yaml --substitutions=_REGION=REGION,_REPOSITORY=travelmate .
```

Before any deployment, validate that all service URLs are public HTTPS URLs, all secrets are Secret Manager references, the Stripe endpoint is test mode, `FALLBACK_MODE=false`, and no local/private addresses appear in deployed values.

## Official references

- Cloud Run Python deployment: https://cloud.google.com/run/docs/quickstarts/build-and-deploy/deploy-python-service
- Cloud Run secrets: https://cloud.google.com/run/docs/configuring/services/secrets
- Cloud Run pricing: https://cloud.google.com/run/pricing
- Stripe webhook signature verification: https://docs.stripe.com/webhooks/signature
