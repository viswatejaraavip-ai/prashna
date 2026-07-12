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
# Flat fee charged when a chat session starts, in smallest currency units
# (paise). This is the guaranteed minimum profit per session, independent of
# how few tokens the user consumes. Default: 5000 paise = Rs 50.
SESSION_FEE_UNITS = int(os.environ.get("SESSION_FEE_UNITS", "5000"))
# Reject a new message if the wallet has less than this left (default Rs 10).
MIN_BALANCE_UNITS = int(os.environ.get("MIN_BALANCE_UNITS", "1000"))
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
