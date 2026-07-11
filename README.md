# Udhyath

A full-stack Vedic astrology platform with four products:

| Product | Model | Status |
|---|---|---|
| **Web charts** (rasi, 16 vargas, KP, Ashtakavarga, bhava, 4 dashas, panchanga) | Free, no account | Production |
| **REST API** (`/v1/*` via API Gateway, `udh_` tokens) | Pay per call from prepaid wallet | Production |
| **MCP server** (11 tools, stdio + Streamable HTTP) | Same token, pay per call | Production |
| **AI Agent** (chat astrologer on Claude/Bedrock) | Prepaid sessions + metered usage | Experimental |

Components:

- **`engine/`** — Jyotish calculation engine on Swiss Ephemeris (`pyswisseph`):
  sidereal positions (Lahiri/Raman/KP), rasi chart, **all 16 Shodasavarga
  divisional charts** (D1…D60 incl. Navamsa, Hora, Drekkana, Dasamsa,
  Trimsamsa, Shashtiamsa), **bhava chalit** (Sripati), nakshatras + padas,
  **Vimshottari dasha** (maha/antar/pratyantar), panchanga, transits.
- **`mcp_server/`** — MCP server exposing the engine as tools (stdio for
  Claude Desktop/Code, Streamable HTTP for remote agents on AWS).
- **`backend/`** — FastAPI web app: JWT auth, **prepaid INR wallet billing**
  (Razorpay), chat sessions with a **Claude Opus 4.8 agent** (served from
  **Amazon Bedrock**, auth via IAM — no Anthropic API key) that calls the
  engine through tool use, plus a direct chart-viewer API.
- **`backend/static/`** — Web frontend: chat UI, wallet top-up, South Indian
  chart renderer.

Verified against the India independence chart (15 Aug 1947 00:00 IST, Delhi):
Taurus lagna 7°43', Moon in Pushya, Saturn mahadasha balance 18.07y. ✓

## Billing model (prepay, minimum profit per session)

1. Users prepay into an INR wallet (Razorpay Checkout: UPI, cards,
   netbanking, wallets).
2. Starting a chat session charges a flat **session fee**
   (`SESSION_FEE_UNITS`, default ₹50) — your guaranteed minimum profit.
3. Every agent reply charges
   `Anthropic USD token cost × USD_TO_WALLET_RATE × BILLING_MARGIN`
   (defaults: ₹90/USD, 1.25 → 25% gross margin on usage).
4. Messages are refused when the balance is too low; the user tops up and
   continues. Every charge is itemised per message in the UI.

Profit per session = session fee + (margin − 1) × token cost. Tune all three
knobs via env vars without code changes.

Payment flow: backend creates a Razorpay **Order** → frontend opens Razorpay
Checkout → on success the frontend calls `/api/billing/verify` (signature
verified server-side) → wallet credited. A `payment.captured` **webhook** acts
as the server-to-server backup so credits are never lost if the user closes
the tab mid-payment.

## Quick start (local)

```bash
python3.12 -m venv .venv && source .venv/bin/activate   # 3.10+ required for MCP
pip install -r backend/requirements.txt

export JWT_SECRET=$(openssl rand -hex 32)
# Inference defaults to Claude in Amazon Bedrock — make sure your shell has
# AWS credentials (aws configure / SSO) with bedrock:InvokeModel rights and
# Anthropic model access enabled in your AWS_REGION.
export AWS_REGION=us-east-1
# Or use the first-party API instead:
#   export INFERENCE_PROVIDER=anthropic ANTHROPIC_API_KEY=sk-ant-...
# Leave RAZORPAY_KEY_ID unset -> the UI's "Add funds" uses a dev top-up.

cd backend && uvicorn app.main:app --reload
# open http://localhost:8000
```

Engine-only test (works on Python 3.9+):

```bash
pip install pyswisseph
python engine/tests/test_engine.py
```

MCP server for Claude Desktop / Claude Code (stdio):

```bash
pip install -r mcp_server/requirements.txt
python mcp_server/server.py
```

## Docker / production

```bash
cp .env.example .env   # fill in keys
docker compose up --build
# web on :8000, MCP (HTTP) on :8100, Postgres included
```

AWS deployment: **[deploy/DEPLOY.md](deploy/DEPLOY.md)** — full
Infrastructure-as-Code with Terraform (`deploy/terraform/`): App Runner + ECR
+ DynamoDB + Secrets Manager + IAM (Bedrock) + API Gateway + Route 53.
Manual console walkthrough alternative: [deploy/aws.md](deploy/aws.md).

## API summary

| Endpoint | Purpose |
|---|---|
| `POST /api/auth/register` / `login` | JWT auth |
| `GET /api/me` | email, balance, saved birth details |
| `GET /api/pricing` | session fee, per-Mtok user rates, top-up options |
| `POST /api/billing/order` | create Razorpay Order for a top-up |
| `POST /api/billing/verify` | verify Checkout signature, credit wallet |
| `POST /api/billing/webhook` | Razorpay `payment.captured` webhook (backup) |
| `POST /api/billing/dev-topup` | dev-only top-up (when Razorpay unset) |
| `POST /api/sessions` | start chat session (charges session fee) |
| `POST /api/sessions/{id}/messages` | send message → agent reply + charge |
| `POST /api/astrology/chart` | direct chart compute for the viewer |

MCP tools: `birth_chart`, `varga_chart`, `all_varga_charts`,
`bhava_chalit_chart`, `dasha_periods`, `current_dasha`, `birth_panchanga`,
`transits`.

## Accuracy notes

- Default ephemeris is the built-in Moshier model (< 1″ error for planets —
  more than enough for varga boundaries). For maximum precision download the
  Swiss Ephemeris data files and set `SE_EPHE_PATH`.
- Rahu uses the **mean node** (standard in most Vedic software); switch to
  `swe.TRUE_NODE` in `engine/jyotish/ephemeris.py` if you prefer.
- Ayanamsas supported: `lahiri` (default), `raman`, `kp`, `fagan_bradley`,
  `yukteshwar`.

## Roadmap ideas

- Ashtakavarga (BAV/SAV), Shadbala, classical yogas
- Streaming agent replies (SSE) and session summaries
- Geocoding lookup for place names (the agent currently resolves cities itself)
