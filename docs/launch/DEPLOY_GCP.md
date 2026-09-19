# Deploying Udhyath on Google Cloud

Runbook for the GCP + Android launch. Everything except the console-only
steps is in Terraform (`deploy/gcp/terraform/`) and Cloud Build
(`cloudbuild.yaml`). Region: **asia-south1 (Mumbai)**.

## What gets created

| Resource | Purpose |
|---|---|
| Cloud Run `udhyath-api` | FastAPI app (2 vCPU / 2 GiB, 600 s timeout, concurrency 20, min 0 / max 10 instances) |
| Artifact Registry `udhyath` | Container images (keeps the last 10) |
| Firestore `(default)` Native, asia-south1 | All app data, PITR on, delete protection on, 12 composite indexes |
| GCS `<project>-udhyath-files` | Report / matching PDFs, share cards (private, signed URLs, lifecycle expiry) |
| GCS `<project>-udhyath-build` | Cloud Build source staging (14-day expiry) |
| Secret Manager | `JWT_SECRET` (generated), Razorpay keys, extra secrets |
| Service accounts | `udhyath-run` (runtime), `udhyath-scheduler` (cron OIDC), `udhyath-build` (deployer) |
| Cloud Scheduler | `daily-push` 06:30, `transit-alerts` 08:00, `purge-deleted` 03:30 IST → `POST /internal/cron/*` with OIDC |
| Optional HTTPS load balancer | Custom domain + managed cert (`domain` var; ~US$18/month) |
| Optional budget | Monthly budget with 50/90/100 % + forecast alerts |

Runtime SA roles: Firestore user, FCM admin, Firebase Auth
admin (account erasure), Speech client, Service Usage consumer, log/metric/trace
writer, Secret accessor (per secret), Storage object admin (files bucket only),
and Token Creator on itself (to sign GCS URLs).

## 0. Prerequisites

- `gcloud` (≥ 480), `terraform` (≥ 1.5), `docker` (optional), Java 17 (for the
  Firestore emulator), `firebase` CLI (optional, Auth emulator).
- A billing account you can link, and a Google Play developer account.

## 1. Create the project

```bash
export PROJECT_ID=udhyath-prod
gcloud projects create $PROJECT_ID --name="Udhyath"
gcloud billing projects link $PROJECT_ID --billing-account=XXXXXX-XXXXXX-XXXXXX
gcloud config set project $PROJECT_ID
gcloud services enable serviceusage.googleapis.com cloudresourcemanager.googleapis.com
gcloud auth application-default login
gcloud auth application-default set-quota-project $PROJECT_ID
```

## 2. Firebase

1. <https://console.firebase.google.com> → **Add project** → pick the existing
   GCP project `$PROJECT_ID` (do not create a new one). Google Analytics is
   optional.
2. **Authentication → Sign-in method**: enable **Phone** and **Google**. Under
   Phone, add a couple of *test phone numbers* with fixed codes for QA and Play
   review (e.g. `+91 99999 00001` / `123456`), and put them in the Play Console
   review notes.
3. **Authentication → Settings → Authorized domains**: add your custom domain
   (for the operator dashboard) if you use one.
4. **Project settings → Your apps → Add app → Android**, package
   `com.udhyath.app`. Add **SHA-1 and SHA-256** fingerprints for:
   - the debug keystore: `keytool -list -v -keystore ~/.android/debug.keystore -alias androiddebugkey -storepass android`
   - your upload key: `keytool -list -v -keystore upload.jks -alias upload`
   - the **Play App Signing key** (Play Console → Setup → App integrity → App
     signing). Phone auth and Google sign-in fail in Play builds without it.
   Download `google-services.json` into `android/app/` (never commit it).
5. Phone auth on Android uses Play Integrity: enable the **Play Integrity API**
   in the GCP console and link the Cloud project in Play Console → App
   integrity.
6. **Add app → Web** (for the operator dashboard). Copy `apiKey` and `appId`
   into `firebase_web_api_key` / `firebase_web_app_id` in `terraform.tfvars`.
7. **Cloud Messaging** is on by default (FCM HTTP v1); nothing else to do.

## 3. Model API keys (Claude on the Anthropic API, Gemini on the Gemini API)

No Vertex AI is used. Both keys go into `terraform.tfvars`
(`anthropic_api_key`, `gemini_api_key`); Terraform stores them in Secret
Manager and injects them into Cloud Run as `ANTHROPIC_API_KEY` /
`GEMINI_API_KEY`.

1. **Anthropic** — console.anthropic.com → create an organization/workspace
   for Udhyath → add billing credits → **API keys → Create key**. Check the
   workspace's rate limits cover launch traffic for `claude-opus-4-5`
   (Settings → Limits); request a higher tier if needed.
2. **Gemini** — aistudio.google.com → **Get API key** in a Google Cloud
   project with **billing enabled** (paid tier). The free tier may use prompts
   to improve Google's products and has low rate limits, so don't launch on it.
3. Smoke test both keys:

   ```bash
   curl -s https://api.anthropic.com/v1/messages \
     -H "x-api-key: $ANTHROPIC_API_KEY" -H "anthropic-version: 2023-06-01" \
     -H "content-type: application/json" \
     -d '{"model":"claude-opus-4-5","max_tokens":50,"messages":[{"role":"user","content":"Say namaste"}]}'
   curl -s "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent" \
     -H "x-goog-api-key: $GEMINI_API_KEY" -H "content-type: application/json" \
     -d '{"contents":[{"parts":[{"text":"Say namaste"}]}]}'
   ```

Data residency: Cloud Run, Firestore and Storage stay in `asia-south1`, but
the model calls are processed by Anthropic and Google outside India. Mention
this cross-border processing in the privacy policy.

## 4. Terraform

```bash
# State bucket (holds the generated JWT secret: keep it private + versioned)
gcloud storage buckets create gs://$PROJECT_ID-tfstate --location=asia-south1 \
  --uniform-bucket-level-access --public-access-prevention
gcloud storage buckets update gs://$PROJECT_ID-tfstate --versioning

cd deploy/gcp/terraform
cp terraform.tfvars.example terraform.tfvars   # edit: project_id, admin_emails, ...
terraform init -backend-config="bucket=$PROJECT_ID-tfstate"
terraform apply
```

The first apply deploys a placeholder "hello" image; Cloud Build replaces it
(Terraform ignores image changes after that). Notes:

- **Firestore already exists** (e.g. created from the Firebase console): import it
  first: `terraform import google_firestore_database.main "projects/$PROJECT_ID/databases/(default)"`.
  Its location must be `asia-south1`; it can't be changed later.
- **Scheduler service agent missing** (error on `scheduler_agent`): run
  `gcloud beta services identity create --service=cloudscheduler.googleapis.com`
  and apply again.
- Index builds take a few minutes; the app falls back gracefully meanwhile
  but admin pages may error until they finish (`gcloud firestore indexes composite list`).
- `terraform output cron_audience` must equal `terraform output service_url`
  (Cloud Run's deterministic URL). If Google ever returns a different URL
  shape, set the `CRON_AUDIENCES` env via `app_env` and change the scheduler
  audience accordingly.

## 5. First deploy

```bash
cd ../../..   # repo root
gcloud builds submit --config cloudbuild.yaml --region=asia-south1 \
  --service-account="projects/$PROJECT_ID/serviceAccounts/udhyath-build@$PROJECT_ID.iam.gserviceaccount.com" \
  --gcs-source-staging-dir="gs://$PROJECT_ID-udhyath-build/source" \
  --substitutions=SHORT_SHA=$(git rev-parse --short HEAD)
```

`.gcloudignore` uploads only `Dockerfile`, `cloudbuild.yaml`, `backend/` and
`engine/`. For CI, create a Cloud Build trigger on `main` with the same
service account; `SHORT_SHA` is filled automatically.

Rollback: `gcloud run services update-traffic udhyath-api --region=asia-south1 --to-revisions=<rev>=100`.

## 6. Google Play

1. Play Console → create the app (`com.udhyath.app`), upload an internal-testing
   build signed with your upload key.
2. **Monetize → Products → In-app products**: create four *managed* products
   (they are consumed server-side after each purchase):

   | Product id | Price |
   |---|---|
   | `wallet_100` | ₹100 |
   | `wallet_200` | ₹200 |
   | `wallet_500` | ₹500 |
   | `wallet_1000` | ₹1000 |

   The wallet is credited with the full rupee amount; Google's service fee is
   your cost.
3. **Users and permissions → Invite new users** → the runtime SA
   (`terraform output runtime_service_account`) with *View app information*,
   *View financial data* and *Manage orders and subscriptions*. Propagation can
   take up to 24 h; until then verify returns "Could not verify the purchase".
4. The app must call `setObfuscatedAccountId(sha256_hex(firebase_uid))` on the
   billing flow; the server rejects tokens bound to another account.
5. **License testers** (Setup → License testing) buy for free; those purchases
   do credit real wallet balance. Their payments docs carry `test: true`.
6. **Policy**: digital goods sold inside the app must go through Play Billing.
   Razorpay may only be offered in the app under Play's *user choice billing*
   program for India (enrol in Play Console → Monetization setup, and show
   Play as an option alongside). Otherwise keep Razorpay to the website.
7. **Data safety form**: declare phone number / email / name, user content
   (birth details, questions), purchase history, device id (hashed), app
   interactions; encrypted in transit; deletion available in-app and via the
   policy URL. Privacy policy URL: `https://<host>/legal/privacy`
   (terms: `/legal/terms`, refund: `/legal/refund`). Account deletion URL
   (required): point to the in-app path and the privacy policy's section 6,
   or a support form.

## 7. Razorpay (optional)

Set `razorpay_*` in `terraform.tfvars`, `terraform apply`, then in the
Razorpay dashboard → Webhooks → `https://<host>/api/billing/webhook`, event
`payment.captured`, secret = `razorpay_webhook_secret`.

## 8. Smoke tests

```bash
URL=$(cd deploy/gcp/terraform && terraform output -raw service_url)
curl -s $URL/api/pricing | jq .
curl -s "$URL/api/legal/privacy?lang=te" | jq -r .title
curl -s -o /dev/null -w "%{http_code}\n" -X POST $URL/internal/cron/purge-deleted   # 401 expected

# Scheduler -> OIDC -> cron path works:
gcloud scheduler jobs run udhyath-purge-deleted --location=asia-south1
gcloud logging read 'resource.type="cloud_run_revision" AND httpRequest.requestUrl:"/internal/cron/"' --limit=5

# Sign in end to end with a Firebase test user (custom token -> ID token -> app JWT).
# Requires Token Creator on udhyath-run for your user account.
python - <<'EOF'
import firebase_admin, json, os, urllib.request
from firebase_admin import auth
firebase_admin.initialize_app(options={"projectId": os.environ["PROJECT_ID"]})
print(auth.create_custom_token("smoke-test-user").decode())
EOF
# then: POST https://identitytoolkit.googleapis.com/v1/accounts:signInWithCustomToken?key=<web api key>
#       {"token": "<custom>", "returnSecureToken": true}  -> idToken
curl -s -X POST $URL/api/auth/firebase -H 'Content-Type: application/json' \
  -d '{"id_token":"<idToken>","device_id":"smoke-device-0001","lang":"te"}' | jq .
```

Check: `trial_granted: true`, `user.balance_units == 1000`, and the operator
dashboard `/admin` signs in with an `ADMIN_EMAILS` Google account.

## 9. Local development (Firestore emulator)

```bash
gcloud components install cloud-firestore-emulator   # needs Java 17
gcloud emulators firestore start --host-port=localhost:8081 &

export FIRESTORE_EMULATOR_HOST=localhost:8081 GOOGLE_CLOUD_PROJECT=udhyath-dev \
       JWT_SECRET=dev CRON_INSECURE_DEV=1 ADMIN_EMAILS=you@example.com
# Optional Firebase Auth emulator (tokens are then unsigned test tokens):
#   firebase emulators:start --only auth --project udhyath-dev
#   export FIREBASE_AUTH_EMULATOR_HOST=localhost:9099
cd backend
pip install -r requirements.txt -r requirements-gcp.txt
uvicorn app.main_gcp:app --reload --port 8080
```

The emulator doesn't enforce composite indexes. Unit tests need no emulator:
`python -m pytest backend/tests/platform` (in-memory Firestore fake).

## 10. Operations

- **Logs**: Cloud Run → udhyath-api → Logs. **Errors**: Error Reporting.
- **Secrets**: rotate with `gcloud secrets versions add udhyath-jwt-secret` and
  redeploy (rotating `JWT_SECRET` signs everyone out).
- **Scaling/cost**: `min_instances=1` removes cold starts (~₹3–4k/month).
  `cpu_always_allocated=true` is required while reports generate in
  background threads after the response.
- **Cron time limit**: jobs share the 600 s request timeout; long jobs must
  stop and resume on the next run.
- **Backups**: Firestore PITR covers 7 days. For longer retention schedule
  `gcloud firestore export gs://<bucket>/backups/...`.
