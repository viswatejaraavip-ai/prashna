# Prashna

A Vedic astrology consultation app for India, in six languages — Hindi,
Telugu, Tamil, Kannada, Malayalam and English. An Android client, a FastAPI
backend on Google Cloud, and a Jyotish engine on Swiss Ephemeris.

The astrologer is an agent: Gemini Flash plans which engine tools to run and
condenses their output, Claude Opus writes the reading, and the chart facts
are computed deterministically in-process — never by a language model. A hard
per-query cost ceiling is enforced *before* the expensive call, not measured
afterwards.

**Everything here is AGPL-3.0.** You may run your own instance, change it,
and charge for it. If you do run it as a network service, section 13 obliges
you to offer your users the source of what you are actually running — set
`SOURCE_URL` to your own repository.

---

## Why it is open

The engine depends on the Swiss Ephemeris (via `pyswisseph`), which is dual
licensed: AGPL, or a paid professional licence from Astrodienst. Because the
backend imports the engine in-process, the whole service is one combined
work — there is no arrangement where the engine is open and the pipeline is
not. Rather than buy the way out, this project takes the AGPL side: the whole
thing is public, and anyone who would rather not pay for the hosted instance
can run their own.

The hosted instance is priced at the cost of running it plus a small margin
for operations. Self-hosting is not a second-class path; it is the point.

## Layout

| Path | What it is |
|---|---|
| `engine/jyotish/` | The calculation engine: sidereal positions (Lahiri), rasi, all 16 divisional charts, bhava chalit, nakshatras, four dasha systems, KP, Ashtakavarga, Shadbala, panchanga, transits, muhurta, matching |
| `backend/app/ai/` | The agent: `planner` (Flash) → `executor` (engine tools + facts brief) → `reasoner` (Opus) → `memory`, with `budget` enforcing the ceiling and `delivery`/`dates` checking what comes back |
| `backend/app/` | The product: auth, wallet, profiles, reports, astrologer features, admin |
| `backend/evals/` | Accuracy evaluation against charts with known outcomes — see below |
| `android/` | Kotlin/Compose client, per-app locales, Play Billing |
| `deploy/gcp/terraform/` | The whole cloud footprint as code |
| `docs/launch/` | Contract, deployment, testing and benchmark notes |

The engine is verified against the India independence chart (15 Aug 1947
00:00 IST, Delhi): Taurus lagna 7°43', Moon in Pushya, Saturn mahadasha
balance 18.07y.

## How the agent works, and what it costs

One question runs: plan (Flash) → engine tools (in-process, free) → facts
brief (Flash) → reading (Opus) → memory update (Flash). The client's whole
dasha ladder and the rasi table are handed to Opus **verbatim**, formatted in
Python, because a summary of a ninety-year timeline is either wrong or the
whole brief.

Measured on the live service: **₹3.1–4.1 of provider cost per query**,
against a ₹5.00 ceiling that `budget.py` enforces by shrinking context — and,
if it still will not fit, by dropping the verbatim blocks rather than
returning an error.

## Honest state of the accuracy

`backend/evals/` asks the deployed service real questions about charts whose
outcomes are already known, and scores how close the dated windows came. The
judge model never sees the true date; the hit/miss decision is made in Python.

On the published golden set — public figures, so **every birth time is
unverified** — it dates events within ±1 year about 14% of the time. An
uncertain birth time moves the lagna, the houses and every dasha boundary, so
treat that as a floor rather than a measurement of the method. On a private
run of two charts with known birth times it was 6 of 7, but seven questions
is far too small to quote as a result. Supply your own known charts in
`evals/golden_set.local.json` (gitignored) to measure it properly.

`evals/RESULTS.md` carries the full numbers and a defect list saying which
problems are fixed and which are still open. It is not a marketing document.

## Running your own

You need a Google Cloud project with billing, an Anthropic API key, a Gemini
API key, and a Firebase project for phone/Google sign-in.

```bash
git clone https://github.com/viswatejaraavip-ai/prashna
cd prashna
make venv && make test          # 562 tests, no cloud credentials needed

cd deploy/gcp/terraform
cp terraform.tfvars.example terraform.tfvars   # add your keys and project
terraform init && terraform apply              # ~70 resources
```

Then build the Android client against your own backend:

```bash
cd android
./gradlew assembleDebug -PapiBase=https://your-service.run.app \
                        -PsourceUrl=https://github.com/you/your-fork
```

### Payments are yours, not mine

Nothing routes money to this project. Purchases happen inside *your* app,
published under *your* Play Console account, and Google pays *your* merchant
account; the backend only verifies the purchase token, using your own service
account credentials. Wallet balances live in your Firestore. Razorpay, if you
enable it, uses `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET` from your
environment.

Three things you must change, or Play Billing will not work:

| What | Where | Why |
|---|---|---|
| `applicationId` | `-PapplicationId=com.yourname.app` | Two apps cannot share a package name on Play |
| `PLAY_PACKAGE_NAME` | backend environment | It must match the app whose purchases you are verifying |
| Product IDs | Play Console, or `PLAY_PRODUCTS` in `platform_wallet.py` | `wallet_100`, `wallet_200`, `wallet_500`, `wallet_1000` must exist in your console with those exact IDs |

The defaults point at this project's package, so if you leave them, token
verification fails rather than misrouting anything — but the error will not
be obvious, which is why it is written down here.

`docs/launch/DEPLOY_GCP.md` has the detail, including the Firebase console
steps that terraform cannot do for you. Nothing in this repository contains
credentials; `terraform.tfvars` and the Android signing keystore are
gitignored and must be yours.

**Costs to expect:** the provider cost per query above, plus Cloud Run,
Firestore and Cloud Storage. Cloud Run scales to zero, so an idle instance
costs almost nothing; `min_instances = 1` removes cold starts at roughly
₹9,200/month.

## Testing

```bash
make test-unit          # per-module unit tests
make test-integration   # every user flow end to end, in-memory Firestore, fake models
make test               # both — what CI runs
make eval-dry           # the accuracy harness, free, no network
make eval               # the real evaluation against a live instance (spends money)
```

Integration tests run the real app against an in-memory Firestore and fake
model clients, so the whole suite is offline and takes about forty seconds.

## Name and branding

The code is AGPL. The name **Prashna**, the logo and the store listing are
not — they are not covered by the code licence and are not granted with it.
Run your own instance under your own name. This is the usual arrangement for
AGPL applications, and it exists so that a fork cannot ship something broken
under a name users already trust.

## Astrology, honestly

Astrology shows tendencies. The app says so to its users, refuses medical,
legal and financial guarantees, and routes a person in distress to Tele-MANAS
(14416) before any model is called. If you fork it, please keep that.
