"""Configuration via environment variables (12-factor)."""

import os


def _f(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


# --- Core ---
# DynamoDB single-table store (on-demand). For local dev point
# DYNAMODB_ENDPOINT_URL at DynamoDB Local or a moto server.
DYNAMODB_TABLE = os.environ.get("DYNAMODB_TABLE", "udhyath")
DYNAMODB_ENDPOINT_URL = os.environ.get("DYNAMODB_ENDPOINT_URL", "")
JWT_SECRET = os.environ.get("JWT_SECRET", "change-me-in-production")
JWT_EXPIRY_HOURS = int(os.environ.get("JWT_EXPIRY_HOURS", "72"))

# --- Sign-in options ---
# Google Identity Services OAuth client id; the Google button is hidden when
# unset.
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
# OTP verification emails. EMAIL_MODE "ses" sends via AWS SES from
# SES_FROM_EMAIL; "dev" (default when unset) echoes the OTP in API responses
# for local/testing use.
SES_FROM_EMAIL = os.environ.get("SES_FROM_EMAIL", "")
EMAIL_MODE = os.environ.get("EMAIL_MODE", "ses" if SES_FROM_EMAIL else "dev")
OTP_TTL_MINUTES = int(os.environ.get("OTP_TTL_MINUTES", "10"))
OTP_MAX_ATTEMPTS = int(os.environ.get("OTP_MAX_ATTEMPTS", "5"))

# --- Claude agent ---
# "bedrock" (Claude in Amazon Bedrock, auth via AWS credentials/IAM role) or
# "anthropic" (first-party API, auth via ANTHROPIC_API_KEY).
INFERENCE_PROVIDER = os.environ.get("INFERENCE_PROVIDER", "bedrock").lower()
AWS_REGION = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
# Bedrock model IDs carry an "anthropic." prefix; first-party IDs are bare.
_DEFAULT_MODEL = ("anthropic.claude-opus-4-8" if INFERENCE_PROVIDER == "bedrock"
                  else "claude-opus-4-8")
AGENT_MODEL = os.environ.get("AGENT_MODEL", _DEFAULT_MODEL)
AGENT_MAX_TOKENS = int(os.environ.get("AGENT_MAX_TOKENS", "8192"))
AGENT_MAX_TOOL_ITERATIONS = int(os.environ.get("AGENT_MAX_TOOL_ITERATIONS", "8"))
AGENT_HISTORY_MESSAGES = int(os.environ.get("AGENT_HISTORY_MESSAGES", "30"))

# --- Billing ---
# Prices in USD per million tokens. Keep in sync with https://platform.claude.com/docs/en/pricing
MODEL_PRICES_PER_MTOK = {
    "claude-opus-4-8": {"input": 5.00, "output": 25.00},
    "claude-opus-4-7": {"input": 5.00, "output": 25.00},
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00},
}
# Multiplier applied to raw token cost when charging the user (your gross margin
# on usage). 1.25 = 25% over the Anthropic cost.
BILLING_MARGIN = _f("BILLING_MARGIN", 1.25)
# Wallet currency and conversion from Anthropic's USD prices.
# The wallet is stored in the smallest unit of CURRENCY (paise for INR).
CURRENCY = os.environ.get("CURRENCY", "INR")
USD_TO_WALLET_RATE = _f("USD_TO_WALLET_RATE", 90.0)  # INR per USD; set 1.0 for USD
# Agent pricing is flat per QUESTION — users understand questions, not
# tokens. The first question in a session includes the full chart synthesis
# and costs more; follow-ups ride the cached context. Token costs are still
# recorded per message for margin analytics, but never shown or billed.
AGENT_FIRST_QUESTION_FEE_UNITS = int(
    os.environ.get("AGENT_FIRST_QUESTION_FEE_UNITS", "10000"))  # Rs 100
AGENT_FOLLOWUP_FEE_UNITS = int(
    os.environ.get("AGENT_FOLLOWUP_FEE_UNITS", "5000"))         # Rs 50
# Legacy flat session-start fee — now 0 (the first-question premium plays
# the guaranteed-minimum role instead).
SESSION_FEE_UNITS = int(os.environ.get("SESSION_FEE_UNITS", "0"))
# Reject a new message if the wallet has less than this left (default Rs 10).
MIN_BALANCE_UNITS = int(os.environ.get("MIN_BALANCE_UNITS", "1000"))
# Dev sandbox provider: AICredits (OpenAI-compatible gateway, INR/UPI wallet).
# NEVER the production default — no prompt caching, adds a third party in the
# data path. Select with INFERENCE_PROVIDER=aicredits for local development.
AICREDITS_API_KEY = os.environ.get("AICREDITS_API_KEY", "")
AICREDITS_BASE_URL = os.environ.get("AICREDITS_BASE_URL",
                                    "https://api.aicredits.in/v1")
AICREDITS_MODEL = os.environ.get("AICREDITS_MODEL", "anthropic/claude-opus-4.8")
AICREDITS_GUARD_MODEL = os.environ.get("AICREDITS_GUARD_MODEL",
                                       "anthropic/claude-haiku-4.5")
# Accounts whose agent traffic routes through the sandbox gateway even in
# production (comma-separated emails) — used for dev/testing on live infra.
DEV_SANDBOX_EMAILS = {e.strip().lower() for e in os.environ.get(
    "DEV_SANDBOX_EMAILS", "dev@example.com").split(",") if e.strip()}

# Mega life report (~1,00,000 words, 18 chapters, Opus 4.8).
REPORT_FEE_UNITS = int(os.environ.get("REPORT_FEE_UNITS", "300000"))  # Rs 3000
REPORT_MODEL = os.environ.get("REPORT_MODEL", "claude-opus-4-8")
# ~5600 words x 18 chapters ≈ 1,00,000 words. Lower this env var to smoke-
# test the pipeline cheaply.
REPORT_SECTION_WORDS = int(os.environ.get("REPORT_SECTION_WORDS", "5600"))
# Free teasers allowed per account per day.
REPORT_TEASERS_PER_DAY = int(os.environ.get("REPORT_TEASERS_PER_DAY", "3"))

# Guardrails: classifier gate in front of the agent + per-user rate limit.
GUARD_ENABLED = os.environ.get("GUARD_ENABLED", "1") not in ("0", "false", "")
GUARD_MODEL = os.environ.get("GUARD_MODEL", "claude-haiku-4-5")
AGENT_RATE_LIMIT_MESSAGES = int(os.environ.get("AGENT_RATE_LIMIT_MESSAGES", "20"))
# Unbilled model replies allowed per session (detail-gathering, clarifying).
# Beyond this a canned "please ask your question" nudge is returned instead
# of burning more tokens — prevents free-chat farming.
MAX_FREE_EXCHANGES = int(os.environ.get("MAX_FREE_EXCHANGES", "8"))
# First-question trial for the mobile app: starter credit (paise) granted once
# per account AND once per device (hashed device id). The trial session's flat
# fee is waived; this credit covers the token charges of ~1-2 questions.
TRIAL_CREDIT_UNITS = int(os.environ.get("TRIAL_CREDIT_UNITS", "2000"))
# Allowed top-up amounts in whole currency (rupees), shown as buttons in the UI.
TOPUP_OPTIONS = [100, 200, 500, 1000]
# Price of one metered /v1 API call (also one MCP tool call), in paise.
# Default 100 = Rs 1 per calculation.
API_CALL_FEE_UNITS = int(os.environ.get("API_CALL_FEE_UNITS", "100"))

# Explicit opt-in for the free dev top-up endpoint (local/testing only).
# Never set in production: with Razorpay unconfigured AND this unset, top-ups
# are simply unavailable.
ALLOW_DEV_TOPUP = os.environ.get("ALLOW_DEV_TOPUP", "").lower() in ("1", "true", "yes")

# --- Razorpay ---
RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "")
RAZORPAY_WEBHOOK_SECRET = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "")
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000")
# Public URLs shown in developer docs/snippets (set to the API Gateway domains
# in production).
PUBLIC_API_BASE_URL = os.environ.get("PUBLIC_API_BASE_URL", PUBLIC_BASE_URL)
PUBLIC_MCP_URL = os.environ.get("PUBLIC_MCP_URL", "")


def model_price(model: str) -> dict:
    # Bedrock IDs are "anthropic.<model>"; token prices match the bare model.
    bare = model.split("anthropic.", 1)[-1] if model.startswith("anthropic.") else model
    if bare in MODEL_PRICES_PER_MTOK:
        return MODEL_PRICES_PER_MTOK[bare]
    # Unknown model: bill at the highest tier to stay safe.
    return {"input": 10.00, "output": 50.00}
