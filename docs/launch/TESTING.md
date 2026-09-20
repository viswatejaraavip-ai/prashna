# Testing, CI and automatic deploy

Every user flow of Prashna has an integration test. They run **locally in
seconds with one command and no cloud credentials**, GitHub runs them on every
push and pull request, and a green CI on `main` is what triggers the Cloud Run
deploy.

```
you ──► make test-integration ──► git push ──► CI (ci.yml) ──► green ──► deploy.yml ──► Cloud Run
```

---

## 1. Run the tests locally

```bash
make test-integration        # every user flow, end to end     (~8 s)
make test-unit               # the per-module unit tests       (~13 s)
make test                    # both — exactly what CI runs
make test-android            # ./gradlew testDebugUnitTest (needs a JDK + Android SDK)
```

`make test-integration` is a thin wrapper around
`backend/scripts/run_integration.sh`, which you can also call directly and
pass pytest arguments to:

```bash
backend/scripts/run_integration.sh                      # all flows
backend/scripts/run_integration.sh -k astrologer -vv    # one flow, verbose
backend/scripts/run_integration.sh -x --lf              # stop at the first failure, re-run failures
```

Both create `.venv/` and install `backend/requirements*.txt` on first use, set
a deterministic offline environment, and print a clear **PASS / FAIL** line at
the end. Nothing reads `GOOGLE_APPLICATION_CREDENTIALS`, no emulator is
started, and no request leaves the machine — so this works on a laptop, on a
plane, and on a fresh CI runner.

### What is real and what is faked

The suite boots the **real application** — `app.main_gcp`, every router, the
JWT auth, the error middleware, the wallet, the Jyotish engine, the PDF and
share-card renderers, the guard, and the whole AI pipeline. Only what would
leave the machine is replaced (`backend/tests/integration/conftest.py`):

| Real dependency | Stand-in |
|---|---|
| Firestore | `tests/platform/platform_fakefs.py` — in-memory documents, queries, transactions |
| Gemini + Claude | `tests/ai/ai_fakes.py` — realistic token usage, priced through `ai/costs.py` |
| Firebase Auth | `verify_firebase_token` mapping `"<uid>"` → phone sign-in, `"<uid>:<email>"` → Google |
| Cloud Speech STT/TTS | stubs that still produce priced `stt` / `tts` trace stages |
| Cloud Storage | in-memory bucket; tests assert the real PDF/PNG bytes that were uploaded |
| FCM | `platform_push._send` (the opt-out and token logic stays real) |
| Android Publisher | `platform_wallet._publisher()` with the real googleapiclient call shape |
| Razorpay | `platform_wallet._razorpay()`, raising the real `SignatureVerificationError` |

Assertions are written against **`docs/launch/CONTRACT.md`** — response shapes,
error `code`s, money in paise, trace documents, rollup counters — not merely
against HTTP 200. That is deliberate: four workstreams edit `backend/app/**`
in parallel, and the contract is the thing they all promised to keep.

### What is covered, flow by flow

`backend/tests/integration/` — 163 tests:

| File | Flows |
|---|---|
| `test_signup_auth.py` | Phone-OTP sign-up, Google sign-up, the free trial (once per account **and** once per device), rejected Firebase tokens, missing or invalid app JWTs, `/api/me` read and patch (name, language, **role → astrologer**, notification prefs), FCM token registration, the **terms/disclaimer version gate** (accepting an old version does not satisfy it), all four legal documents in all six languages, the public HTML policy pages, `/api/pricing`, `/healthz`, operator login rejection for a non-operator Google account |
| `test_profiles_charts.py` | Profile CRUD, validation errors and their codes, **"time unknown"** (noon is used, snapshot/lagna flagged approximate, fixing the time clears it), cross-account isolation, place lookup, the **free snapshot in all six languages** (and that it costs nothing and writes no trace), `?lang` / `Accept-Language` / saved-language precedence, **every chart kind**: 10 free kinds and the 7 Pro-gated deep kinds for both the denied and the allowed case, expired Pro, bad kinds, matching + matching PDF |
| `test_daily_tools.py` | Daily panchanga + personal forecast in all six languages and its `daily_content` cache, daily without a profile, transit alerts (types, ordering, 180-day window), muhurta for all six event types plus validation, the birth-time helper, share cards (chart and daily, real PNG bytes), and the three cron endpoints: unauthenticated → 401, daily-push honouring opt-outs and being retry-safe, transit-alerts |
| `test_ai_consultation.py` | Sessions (create, list, messages, ownership), **ask**: `ok` (charge ₹10, contract-shaped trace, ledger, session transcript, rollups), answering in each of the five app languages, `refused`, `clarify`, the pre-filter refusal that spends no tokens, the per-session free-turn cap, **`insufficient_balance` 402**, **`rate_limited` 429**, empty/overlong input, the maintenance and Opus kill switches; the **SSE stream** (delta framing, `done` payload, refusal as one delta, HTTP errors before the stream opens); **voice** (transcript, `stt`/`tts` stages inside the ₹5 ceiling, `audio_b64`, size limits, cloud-voice kill switch) |
| `test_mega_report.py` | Free teaser + its daily limit, **purchase → generation → progress → PDF** (charge, ledger, rollup, per-chapter traces, chapter contents, real `%PDF` bytes, PDF rendered once), progress visible while generating and the PDF refused until ready, **failure → automatic refund → resume keeping the finished chapters**, resume only on failed reports, insufficient balance, ownership, maintenance flag, and the astrologer's **branded** report (brand required first) |
| `test_wallet_payments.py` | **Play verify** (Android Publisher call arguments, credit once, consume, replay protection, consume-failure retry, wrong product, wrong account via `obfuscatedExternalAccountId`, pending/cancelled/unknown purchases), **Razorpay** order → verify (bad signature, idempotency, wrong owner) and the webhook, the ledger, refund requests (duplicate → 409, too many open → 429), and the **Pro plan purchase** including stacking and 402 |
| `test_astrologer.py` | The whole astrologer path: a personal user is refused every `/api/astro/*` route, an astrologer without Pro is refused the Pro features, **Pro purchase from the wallet unlocks them**, expiry locks them again, client CRUD + search + separation from family profiles, client privacy between astrologers, the Pro bundle contents, brand settings round-trip and validation, **branded vs plain matching PDFs**, and a paid consultation about a client |
| `test_support_dpdp.py` | Support tickets (categories, validation, the operator reply and resolve), **DPDP export** (everything present, no device hashes or FCM tokens, no raw payment data), **account deletion** (soft delete hides the account, signing in inside the grace period restores it), and the **purge cron** (only accounts past 30 days, payments pseudonymised, Firebase user deleted, expired Pro plans downgraded) |
| `test_operator_dashboard.py` | Admin auth on every route (401 anonymous, 403 with a user token), login/`me`/config, the SPA and its assets, the overview (series, totals, percentiles, watch level, refunds), cost watch, the trace explorer (filters, compact rows, detail with question/answer/user, 404), session messages, user lookup by uid and phone, **balance adjust with the audit trail** and its limits, **refund approve / reject / partial**, runtime flags (read, write, validation, and that a flag change immediately changes what users get), the error list, and the cost-watch cron |
| `test_flow.py` | The two **cross-module stories**: a personal user from sign-up through trial, snapshot, Play top-up, a paid question, the trace/rollup/ledger agreeing, the operator finding that exact query, a refund approved, export and deletion; and an astrologer from role switch through Pro, clients, Pro bundle, brand, branded PDF and a paid consultation, ending at what the operator dashboard shows |

---

## 2. CI on GitHub (`.github/workflows/ci.yml`)

Runs on **every push and every pull request**.

| Job | What it does |
|---|---|
| `backend` | Python 3.11 (same as the Dockerfile), pip cache, install `requirements.txt` + `requirements-gcp.txt`, import-check that `app.main_gcp` really loads, run the unit tests, run the integration suite, write a results table into the job summary and upload the JUnit XML |
| `android` | Temurin JDK 17 + Gradle cache, drops in `google-services.example.json` (the real one is gitignored and the unit tests never touch Firebase), runs `./gradlew testDebugUnitTest` |
| `ci` | A single roll-up status check — this is the one to make required in branch protection, and the one `deploy.yml` waits for |

If a runner cannot provision the Android SDK, set the repository variable
`ANDROID_TESTS=off` (Settings → Secrets and variables → Actions → Variables);
the `android` job is then skipped and `ci` still passes on the backend alone.

### Branch protection — make `main` require CI

Do this once, or `deploy.yml` will happily deploy commits that were pushed
straight to `main` without review:

**Settings → Branches → Add branch ruleset** (or *Add rule*) for `main`:

- ☑ **Require a pull request before merging** (1 approval; ☑ dismiss stale approvals)
- ☑ **Require status checks to pass before merging**
  - ☑ Require branches to be up to date before merging
  - required check: **`CI`** (add `Backend (unit + integration)` and
    `Android unit tests` too if you prefer them listed individually)
- ☑ **Require conversation resolution before merging**
- ☑ **Block force pushes**, ☑ **Restrict deletions**
- ☑ **Do not allow bypassing the above settings** (include administrators)

With `gh`:

```bash
gh api -X PUT repos/viswa-cpu/udhyath/branches/main/protection \
  -H "Accept: application/vnd.github+json" \
  -f 'required_status_checks[strict]=true' \
  -f 'required_status_checks[contexts][]=CI' \
  -f 'enforce_admins=true' \
  -f 'required_pull_request_reviews[required_approving_review_count]=1' \
  -f 'restrictions=' \
  -f 'allow_force_pushes=false' \
  -f 'allow_deletions=false'
```

---

## 3. Deploy (GCP) — `.github/workflows/deploy.yml`

Triggered by the **CI workflow completing successfully on `main`**, it checks
out the exact commit CI tested, authenticates with **Workload Identity
Federation** (no service-account key exists anywhere), and runs the existing
`cloudbuild.yaml` (build → push to Artifact Registry → `gcloud run deploy`) in
project `$PROJECT_ID`, region `asia-south1`, service `udhyath-api`, as the
build service account `udhyath-build@$PROJECT_ID.iam.gserviceaccount.com`.
It then smoke-tests the new revision: `/healthz` is 200, `/api/pricing`
returns a price, and `/internal/cron/purge-deleted` is still 401 to an
anonymous caller. A failure prints the rollback command.

`workflow_dispatch` lets you redeploy any SHA by hand.

### What the owner must do, once

**a. Terraform** — `deploy/gcp/terraform/cicd.tf` (new file, added by this
workstream) creates the Workload Identity pool + provider, the
`udhyath-deployer` service account, and the exact IAM it needs
(`cloudbuild.builds.editor`, `logging.viewer`, `serviceusage.serviceUsageConsumer`,
`run.viewer`, `actAs` on `udhyath-build`, and object admin on the build staging
bucket). Only the configured repository, through its OIDC token, can
impersonate it.

```bash
cd deploy/gcp/terraform
# in terraform.tfvars, if your repo is not viswa-cpu/udhyath:
#   github_repository = "<owner>/<name>"
terraform apply
terraform output github_actions_variables
```

**b. Enable the two extra APIs** (terraform does this, but if you apply only
`cicd.tf` targets, do it explicitly):

```bash
gcloud services enable sts.googleapis.com iamcredentials.googleapis.com \
  --project=$PROJECT_ID
```

**c. GitHub repository variables** — paste the terraform output. These are
*variables*, not secrets: none of them are sensitive, and that is the whole
point of WIF.

```bash
REPO=viswa-cpu/udhyath
gh variable set GCP_PROJECT_ID   --repo $REPO --body "$PROJECT_ID"
gh variable set GCP_REGION       --repo $REPO --body "asia-south1"
gh variable set GCP_SERVICE      --repo $REPO --body "udhyath-api"
gh variable set GCP_BUILD_SA     --repo $REPO --body "udhyath-build@$PROJECT_ID.iam.gserviceaccount.com"
gh variable set GCP_BUILD_BUCKET --repo $REPO --body "$PROJECT_ID-udhyath-build"
gh variable set GCP_WIF_PROVIDER --repo $REPO \
  --body "$(cd deploy/gcp/terraform && terraform output -raw github_wif_provider)"
gh variable set GCP_DEPLOYER_SA  --repo $REPO \
  --body "$(cd deploy/gcp/terraform && terraform output -raw github_deployer_service_account)"
```

`GCP_WIF_PROVIDER` looks like
`projects/<project-number>/locations/global/workloadIdentityPools/github-pool/providers/github-provider`.

**d. (Optional) a `production` environment** — Settings → Environments → New
environment → `production` → *Required reviewers*. `deploy.yml` already
targets it, so every deploy then waits for a human click. Leaving the
environment uncreated simply means no approval step.

**e. Verify**: push a trivial commit to a branch, open a PR, watch CI go
green, merge, and watch `Deploy to Cloud Run` run. The job summary prints the
new revision and URL.

### Rollback

```bash
gcloud run revisions list --service=udhyath-api --region=asia-south1 --project=$PROJECT_ID
gcloud run services update-traffic udhyath-api --project=$PROJECT_ID \
  --region=asia-south1 --to-revisions=<previous-revision>=100
```

---

## 4. Adding a test

Put it in `backend/tests/integration/`. The `api` fixture gives you the
whole system:

```python
def test_something(api):
    _, h = api.signup("u1", device="dev-0001", lang="te")   # trial granted
    p = api.profile(h)                                      # a birth profile
    api.topup("u1", 5000)                                   # wallet, in paise
    sid = api.session(h, p["id"])
    r = api.client.post("/api/sessions/%s/ask" % sid, headers=h, json={"text": "..."})
    assert r.json()["charged_units"] == 1000
    assert api.db.data("traces/" + r.json()["trace_id"])["status"] == "ok"
```

Handy members: `api.client` (TestClient), `api.db` (with `.data(path)` and
`.children(path)`), `api.admin()` (operator headers), `api.set_role`,
`api.set_pro`, `api.set_models(gemini, claude)`, `api.storage.objects`,
`api.play`, `api.razorpay`, `api.pushes`, `api.rollup()`,
`api.ledger_types(uid)`, `api.launch.paused` (hold report generation).

Two rules that keep this suite trustworthy:

1. **Assert the contract**, not the implementation: status codes, error
   `code`s, field names and money amounts from `docs/launch/CONTRACT.md`.
2. **No sleeps, no network, no clock dependence** beyond the deliberate "today"
   arithmetic the engine needs.

Test module basenames must be unique across `backend/tests/**` (the
directories are not packages), e.g. `test_mega_report.py` rather than another
`test_reports.py`.

---

## 5. Known product issues the suite documents

* **`xfail`: the advertised report price is not the price charged.**
  `GET /api/pricing` returns `report_price_units` from
  `platform_wallet.REPORT_PRICE_UNITS` (₹1,050), while `POST /api/reports`
  charges `reports.report_fee_units(lang)` — currently ₹250 (hi) to ₹450 (ml),
  ₹150 (en). The app would show one number and debit another. One of the two
  has to become the source of truth; `reports.report_pricing()` already exists
  and looks like the intended one. The test
  `test_advertised_report_price_is_what_the_wallet_is_charged` in
  `test_mega_report.py` is marked `xfail` and will announce itself as XPASS the
  moment the two agree — delete the marker then.
* **Two support-reply shapes.** `routes_admin.reply_support` writes
  `{from, admin, message, created_at}` and defaults to `resolve=false`, while
  `platform_compliance.reply_ticket` writes `{by, text, at}`, always resolves
  and sends the user a push. Only the admin route is reachable over HTTP, so
  the Android app must read `message` (not `text`) and the user currently gets
  **no push** when support replies. Worth unifying on one writer.
