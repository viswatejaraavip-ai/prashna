# Udhyath launch contract (GCP + Android)

This is the shared agreement between the five parallel workstreams. **If your
code touches something defined here, match it exactly.** If you truly need to
change it, update this file and say so in your final report.

## Scope

- **Audiences:** personal users (P1–P3) and astrologers (P4). The developer
  API (`/v1`, MCP) stays in the repo untouched but is not promoted in the app.
- **Client:** the Android app is the product surface. The existing web
  (`backend/static/*`) is left alone apart from the new operator dashboard.
- **Cloud:** Google Cloud only. Cloud Run (region `asia-south1`), Firestore
  (Native mode, `asia-south1`), Secret Manager, Artifact Registry, Cloud
  Storage (PDFs, share cards), Cloud Scheduler (daily jobs), Firebase Auth
  (phone OTP + Google), Firebase Cloud Messaging (push). Models: Claude via the first-party
  Anthropic API, Gemini via the Gemini API (no Vertex AI). There is no AWS dependency on the new code path.
- **Languages (exactly five):** `hi` Hindi, `te` Telugu, `ta` Tamil,
  `kn` Kannada, `ml` Malayalam. The user picks one on first launch. The app UI
  **and every AI response** use that language. Astrology terms may stay in
  their native Sanskrit form and script.

## AI pipeline (per paid query)

| Stage | Model | Job |
|---|---|---|
| 1. Plan | Gemini Flash (`GEMINI_MODEL`, default `gemini-3.5-flash-lite`) | Guardrail + intent classification, pick which engine tools to run, JSON plan |
| 2. Execute | Gemini Flash + engine | Run engine tools (deterministic Python), then Flash condenses raw output into a ≤1,500-token "facts brief" relevant to the question. When the engine output is already small (`AI_BRIEF_SKIP_MAX_CHARS`, narrow tools like `current_dasha`) the Flash call is skipped and the JSON goes straight to Opus; the `brief` stage is still traced, with `cost_units: 0` and `detail.skipped` |
| 3. Reason | Claude Opus 4.5 on the Anthropic API (`claude-opus-4-5`, `CLAUDE_MODEL`) | Only this stage uses Claude: interpret the facts brief and answer in the user's language |

- **Price to the user:** flat **₹10 per answered query** (`QUERY_PRICE_UNITS=1000` paise), for text and voice. Clarifying or refused turns are free (no charge) but are capped per session.
- **Cost ceiling:** the total provider cost of a query (Flash + Opus + any cloud speech) must be **< ₹5** (`QUERY_COST_CEILING_UNITS=500`). Enforce it *before* calling Opus: estimate input tokens, set `max_tokens` from the remaining budget, and shrink the brief/history when it won't fit. Record the actual cost afterwards. Any query over the ceiling is flagged in its trace.
- **USD→INR:** `USD_TO_INR` env (default 90).
- **Voice:** on-device Android STT/TTS is the default and costs nothing. The server also offers cloud STT/TTS (Google Cloud Speech-to-Text / Text-to-Speech, Standard or WaveNet voices) for devices missing a language pack. Its cost counts toward the ₹5 ceiling. Voice replies are shorter (spoken style, `VOICE_MAX_OUTPUT_TOKENS`).

## Firestore collections (shared schema)

Use `backend/app/store.py` for the client and helpers. Money is always an
integer number of **paise** (`*_units`). Timestamps are ISO-8601 UTC strings
(`store.now_iso()`).

| Collection | Doc id | Owner | Key fields |
|---|---|---|---|
| `users` | uid (Firebase uid) | platform | `uid, phone, email, name, lang, role ("user"\|"astrologer"), balance_units, plan ("free"\|"pro"), plan_expires_at, created_at, device_hashes[], trial_claimed, disclaimer_accepted_at, deleted_at, fcm_tokens[], notif_prefs{daily,transits,promos}` |
| `users/{uid}/profiles` | auto | features | `name, relation ("self"\|"spouse"\|"child"\|"parent"\|"other"\|"client"), birth{date,time,tz,lat,lon,place}, time_known (bool), gender, notes, created_at` |
| `users/{uid}/ledger` | auto | platform | `type ("topup"\|"query"\|"report"\|"refund"\|"trial"\|"subscription"\|"adjust"), delta_units, balance_after, ref, created_at` |
| `sessions` | auto | ai | `uid, profile_id, lang, mode ("text"\|"voice"), created_at, summary, query_count, free_turns, updated_at` |
| `sessions/{sid}/messages` | auto | ai | `role, text, charged_units, trace_id, created_at` |
| `traces` | auto | ai (writes), admin (reads) | see below |
| `users/{uid}/ai_memory` | profile id | ai | long-term memory per profile: `facts[] (≤8 short English bullets), updated_at` (include in DPDP export/delete) |
| `rollups_daily` | `YYYY-MM-DD` | ai/platform (atomic increments) | `queries, voice_queries, revenue_units, cost_units, over_ceiling, errors, refusals, signups, topups_units, reports, by_lang{hi:..}` |
| `payments` | order/purchase id | platform | `uid, provider ("play"\|"razorpay"), amount_units, status, created_at, raw` |
| `refunds` | auto | platform | `uid, ref, amount_units, reason, status ("requested"\|"approved"\|"rejected"), created_at, decided_by` |
| `support_tickets` | auto | platform | `uid, category, message, status ("open"\|"resolved"), replies[], created_at` |
| `reports` | auto | ai | `report_id, uid, profile_id, profile_name, lang, birth, brand{...}\|null, fee_units, status ("generating"\|"ready"\|"failed"), sections_done, sections_total, cost_units, outline, pdf_path, refund_pending, created_at, completed_at, error`, plus progress: `chapter_titles[] (localized), chapters_started_at, concurrency, chapter_seconds (measured mean), words_target, eta_seconds`; chapters in `reports/{id}/sections/{NN}` `{idx, title, content, created_at}` |
| `astro_brand` | uid | features | astrologer white-label: `display_name, phone, logo_url, footer` |
| `daily_content` | `YYYY-MM-DD_{lang}_{moon_rasi}` | features | cached daily forecast text |
| `config_flags` | `global` | admin (writes), everyone (reads, cached 60s) | `voice_cloud_enabled, opus_enabled, query_price_units, cost_ceiling_units, maintenance_message` |

### `traces` document (one per AI query; the dashboard depends on it)

```json
{
  "trace_id": "...", "uid": "...", "session_id": "...", "lang": "te",
  "mode": "text|voice", "kind": "query|report_chapter|daily|teaser",
  "status": "ok|refused|clarify|error|over_ceiling",
  "question_chars": 120, "created_at": "...", "latency_ms": 5400,
  "stages": [
    {"name": "plan", "model": "gemini-2.5-flash", "in_tok": 900, "out_tok": 150,
     "cost_units": 12, "latency_ms": 700, "detail": {"intent": "career", "tools": ["current_dasha"]}},
    {"name": "tools", "latency_ms": 90, "detail": {"tools": ["current_dasha"], "errors": []}},
    {"name": "brief", "model": "gemini-2.5-flash", "in_tok": 5000, "out_tok": 1200, "cost_units": 40, "latency_ms": 1800},
    {"name": "reason", "model": "claude-opus-4-5", "in_tok": 3800, "cache_read_tok": 0,
     "out_tok": 650, "cost_units": 318, "latency_ms": 2900},
    {"name": "stt|tts", "model": "...", "units": 14, "cost_units": 5}
  ],
  "cost_units": 375, "charged_units": 1000, "error": null
}
```

Stage names used: `stt, plan, tools, brief, reason, tts, memory` (queries),
`outline, reason` (report_chapter), `teaser`.

`latency_ms` is **what the user waited** — up to and including the delivered
answer (the SSE `done` event). The `memory` stage and the Firestore writes run
after that on a background thread, so they are recorded in `stages` with their
own `latency_ms` but are not inside the query's `latency_ms`. Sum the stages if
you want total work done; use `latency_ms` for the latency the dashboard shows.

Optional extra trace fields
written by the AI workstream: `budget {ceiling, limit, spent{}, reserved{}}`,
`charge_error` (answer delivered but the wallet charge failed), and for
`report_chapter`: `report_id, chapter, words_target`.

## HTTP API (all under `/api`, JSON, `Authorization: Bearer <app JWT>`)

Errors: `{"detail": "...", "code": "insufficient_balance|rate_limited|not_found|forbidden|invalid|maintenance"}`.
`lang` query param or `Accept-Language` header selects the response language; otherwise the user's saved `lang` is used.

### Platform (auth, wallet, compliance) — `routes_platform.py`
- `POST /api/auth/firebase` `{id_token, device_id, lang}` → `{token, user}` (verifies Firebase ID token for phone OTP or Google; creates the user; grants the trial once per account and device)
- `GET /api/me` → `{user, pricing}`; `PATCH /api/me` `{name?, lang?, notif_prefs?, role?}`
- `POST /api/me/fcm-token` `{token}`
- `POST /api/me/disclaimer` → records acceptance
- `GET /api/pricing` → `{query_price_units, report_price_units, pro_plan_units, pro_plan_days, topup_options:[...], play_products:[...]}`
- `POST /api/wallet/razorpay/order` `{amount_rupees}` → `{order_id, key_id, amount_units}`; `POST /api/wallet/razorpay/verify` `{order_id, payment_id, signature}`; `POST /api/billing/webhook` (Razorpay backup)
- `POST /api/wallet/play/verify` `{product_id, purchase_token}` → verifies with the Android Publisher API, credits the wallet idempotently, consumes the product
- `GET /api/wallet/ledger?limit=50`
- `POST /api/refunds` `{ref, reason}`; `GET /api/refunds`
- `POST /api/support` `{category, message}`; `GET /api/support`
- `GET /api/me/export` → JSON of all user data (DPDP); `DELETE /api/me` → soft delete now, hard purge by job after 30 days
- `POST /api/plan/pro/purchase` → debit the wallet for the astrologer Pro plan (`PRO_PLAN_UNITS` default ₹499, 30 days)
- `GET /api/legal/{doc}` where doc ∈ `terms|privacy|refund|disclaimer`, returns `{title, body_markdown}` in the requested lang

### AI — `routes_ai.py`
- `POST /api/sessions` `{profile_id, mode}` → `{session_id}`
- `GET /api/sessions?limit=20`; `GET /api/sessions/{sid}/messages`
- `POST /api/sessions/{sid}/ask` `{text}` → `{reply, charged_units, balance_units, status, trace_id}` (status as in traces)
- `POST /api/sessions/{sid}/ask/stream` → same, as SSE: `event: delta` `{text}` … `event: done` `{charged_units, balance_units, status, trace_id}`
- `POST /api/sessions/{sid}/voice` multipart `audio` (16 kHz mono OGG_OPUS or LINEAR16) + `tts` bool → `{transcript, reply, audio_b64?, charged_units, balance_units, status, trace_id}` (cloud speech path)
- `POST /api/reports` `{profile_id, brand?: bool}`; `GET /api/reports`; `GET /api/reports/{id}`; `POST /api/reports/{id}/resume`; `GET /api/reports/{id}/pdf` → signed GCS URL; `POST /api/reports/teaser` `{profile_id}`
- `GET /api/reports/pricing` → `{report_price_units (for the caller's language), report_price_units_by_lang{}, report_chapters, report_words, report_eta_seconds, lang}`
- `GET /api/reports/{id}/progress` → `{status, percent, sections_done, sections_total, current_chapter{idx,title}, chapters:[{idx,title,done}], eta_seconds, elapsed_seconds, error, refund_pending, fee_units}`; the same payload as SSE on `GET /api/reports/{id}/progress/stream` (`event: progress` … `event: done`). `GET /api/reports` and `GET /api/reports/{id}` also carry `percent`/`eta_seconds`.
- **Report price:** 18 chapters × ~1,000 words, delivered in < 5 minutes (chapters generated concurrently). The price is the measured provider cost × 1.5 (`REPORT_MARGIN`), per language, rounded up to ₹50: Hindi ₹250, Telugu/Tamil/Kannada ₹400, Malayalam ₹450, English ₹150 at the modelled tokens-per-word. `REPORT_FEE_UNITS`/`REPORT_PRICE_UNITS` (flat) or `REPORT_FEE_UNITS_<LANG>` override it; `backend/scripts/report_bench.py` measures the real rate. `GET /api/pricing` (platform) should serve `reports.report_fee_units(lang)` so the advertised price matches the charge.

### Personal & astrologer features — `routes_features.py`
- Profiles: `GET/POST /api/profiles`, `GET/PATCH/DELETE /api/profiles/{pid}`
- Free charts: `GET /api/profiles/{pid}/chart?kind=rasi|navamsa|varga&division=9|all|kp|ashtakavarga|shadbala|bhava|dashas|panchanga|yogas|doshas|nadi|varshphal|lalkitab|gemstones`. Basic kinds are free; the deep kinds (`kp, shadbala, ashtakavarga, all vargas, nadi, varshphal, lalkitab`) require `plan == "pro"` for astrologers.
- First reading (free, no LLM, localized templates): `GET /api/profiles/{pid}/snapshot` → lagna, moon sign, nakshatra, current dasha/antardasha with plain-language lines
- Daily: `GET /api/daily?profile_id=` → panchanga, rahu kalam, personal day forecast (cached per moon rasi, date and lang)
- Transit alerts: `GET /api/profiles/{pid}/alerts` → upcoming Sade Sati, dasha changes, eclipses in the next 180 days
- Matching: `POST /api/matching` `{profile_a, profile_b}` → guna milan, doshas, verdict; `POST /api/matching/pdf` → signed URL
- Muhurta: `POST /api/muhurta` `{event: "marriage|griha_pravesam|vehicle|business|travel|naming", from, to, profile_id?, lat, lon}` → ranked windows
- Birth-time helper: `POST /api/profiles/{pid}/rectify` `{events:[{date, type}]}` → candidate times with scores (engine heuristics, no LLM)
- Share card: `POST /api/share-card` `{profile_id, kind: "chart|daily"}` → signed PNG URL
- Places: `GET /api/places?q=` (reuse the existing dataset)
- Astrologer: `GET/POST /api/astro/clients` (alias of profiles with `relation=client`), `GET/PATCH/DELETE /api/astro/clients/{pid}` (PATCH takes notes/name/gender/birth; `relation` is ignored so a client stays a client), `GET/PUT /api/astro/brand`, `GET /api/astro/clients/{pid}/pro-bundle` → all vargas + KP + Shadbala + Ashtakavarga + dashas in one call (Pro only)
  - `GET /api/astro/brand` always returns `{"brand": {display_name, phone, logo_url, footer}}`; an astrologer who has never saved one gets the four keys as empty strings, **never `null`**, so the settings form always has a shape to bind to. (`brand.get_brand()` still returns `None` internally, which is what "no brand" means for report/PDF branding.)
  - `PUT /api/astro/brand` takes the same four keys, all optional; it replaces the document, so a key left out is cleared. Validation failures come back as `{"code": "invalid"}` with a **localized** `detail` that never names a raw field like `display_name`.
- Cron (OIDC-authenticated from Cloud Scheduler, `/internal/...`, not `/api`): `POST /internal/cron/daily-push`, `POST /internal/cron/transit-alerts`, `POST /internal/cron/purge-deleted`

### Operator — `routes_admin.py` (admin only: `ADMIN_EMAILS` via Google sign-in → admin JWT)
- `GET /admin` serves the dashboard SPA (`backend/static/admin/`)
- `GET /api/admin/overview?days=30` → rollups series + today's totals, margin, P50/P95 cost and latency per query, over-ceiling count
- `GET /api/admin/traces?status=&uid=&min_cost=&limit=` and `GET /api/admin/traces/{id}`
- `GET /api/admin/users?q=` (phone/email/uid) and `GET /api/admin/users/{uid}` (profile, ledger, sessions, traces, tickets)
- `POST /api/admin/users/{uid}/adjust` `{delta_units, reason}` (audited)
- `GET /api/admin/refunds`, `POST /api/admin/refunds/{id}` `{decision}`
- `GET /api/admin/support`, `POST /api/admin/support/{id}/reply`
- `GET/PUT /api/admin/flags`
- `GET /api/admin/errors?limit=` (traces with status=error plus recent 5xx from the app log collection `app_errors`)

## Backend module ownership (avoid edit conflicts)

| Workstream | Owns (create/edit) | Must not edit |
|---|---|---|
| Platform + infra | `store.py` (additions only), `config.py`, `auth.py`, `billing.py`, `routes_platform.py`, `platform_*.py`, `Dockerfile`, `backend/requirements.txt`, `deploy/gcp/**`, `docs/launch/DEPLOY_GCP.md`, `cloudbuild.yaml`, `.env.example` | others' modules |
| AI pipeline | `backend/app/ai/**`, `routes_ai.py`, `reports.py`, `guard.py` | others' modules |
| Features | `backend/app/features/**`, `routes_features.py` | others' modules |
| Operator dashboard | `routes_admin.py`, `backend/app/admin/**`, `backend/static/admin/**` | others' modules |
| Android | `android/**` | backend |

`main.py` is wired up by the lead at integration time: each workstream exposes
`router` (and optionally `internal_router`) from its `routes_*.py`. New
dependencies go in `backend/requirements-gcp.txt` (append-only, one line per
package, keep sorted). Everyone may *read* `config.py`; configuration for your
module lives in your own module and reads `os.environ` directly, so you don't
have to edit `config.py`.

Shared helpers available now in `backend/app/store.py`: `fs()`, `now_iso()`,
`today_key()`, `incr_rollup(fields: dict, day=None)`, `get_flags()`,
`current_uid` (FastAPI dependency returning the uid from the app JWT),
`get_user(uid)`, `require_admin`, `lang_of(request, user)`. The platform
workstream owns the implementation behind `current_uid`/JWT; the signature is fixed.
