"""Prepaid wallet billing on DynamoDB (INR wallet, Razorpay top-ups).

Model: users prepay into a wallet held in paise.
Agent chat is billed FLAT PER QUESTION — predictable for the user:
  * first question in a session (full chart synthesis): AGENT_FIRST_QUESTION_FEE
  * every follow-up: AGENT_FOLLOWUP_FEE
  * a trial account's very first question is free (free_sessions waiver).
Raw token costs are recorded on each message for margin analytics only.
Metered /v1 API and MCP calls charge API_CALL_FEE_UNITS each.

All balance changes are atomic conditional updates, so concurrent requests
can never overdraw a wallet.
"""

import math
from typing import Dict

from . import config, db
from .db import InsufficientBalance  # re-exported for callers  # noqa: F401


def token_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    price = config.model_price(model)
    return input_tokens * price["input"] / 1e6 + output_tokens * price["output"] / 1e6


def user_charge_units(model: str, input_tokens: int, output_tokens: int) -> int:
    usd = token_cost_usd(model, input_tokens, output_tokens)
    units = usd * config.USD_TO_WALLET_RATE * 100 * config.BILLING_MARGIN
    return max(1, int(math.ceil(units)))


def charge(email: str, units: int) -> int:
    """Deduct from the wallet atomically; returns the new balance."""
    return db.adjust_balance(email, -units)


def credit(email: str, units: int) -> int:
    return db.adjust_balance(email, units)


def start_session(email: str) -> Dict:
    """Open a chat session. Free — billing happens per question."""
    if config.SESSION_FEE_UNITS:
        charge(email, config.SESSION_FEE_UNITS)
    return db.create_session(email, config.SESSION_FEE_UNITS)


def question_fee_units(is_first: bool) -> int:
    return (config.AGENT_FIRST_QUESTION_FEE_UNITS if is_first
            else config.AGENT_FOLLOWUP_FEE_UNITS)


def record_usage(email: str, session_id: str, model: str,
                 input_tokens: int, output_tokens: int,
                 is_first: bool = False) -> int:
    """Charge the flat question fee; returns units charged.

    A trial account's first question consumes its waiver and is free.
    Token counts are stored with the message for margin analytics."""
    units = question_fee_units(is_first)
    if is_first and db.consume_free_session(email):
        units = 0
    if units:
        charge(email, units)
    db.record_session_usage(session_id, units, input_tokens, output_tokens)
    return units


def can_send_message(user: Dict, is_first: bool = False) -> bool:
    if is_first and int(user.get("free_sessions", 0) or 0) > 0:
        return True
    return user["balance_units"] >= question_fee_units(is_first)


def pricing_info() -> dict:
    price = config.model_price(config.AGENT_MODEL)
    factor = config.USD_TO_WALLET_RATE * config.BILLING_MARGIN
    return {
        "model": config.AGENT_MODEL,
        "currency": config.CURRENCY,
        "session_fee": config.SESSION_FEE_UNITS / 100.0,
        "agent_first_question_fee": config.AGENT_FIRST_QUESTION_FEE_UNITS / 100.0,
        "agent_followup_fee": config.AGENT_FOLLOWUP_FEE_UNITS / 100.0,
        "margin_multiplier": config.BILLING_MARGIN,
        "usd_to_wallet_rate": config.USD_TO_WALLET_RATE,
        "user_price_per_mtok": {
            "input": round(price["input"] * factor, 2),
            "output": round(price["output"] * factor, 2),
        },
        "topup_options": config.TOPUP_OPTIONS,
        "api_call_fee": config.API_CALL_FEE_UNITS / 100.0,
        "api_base_url": config.PUBLIC_API_BASE_URL,
        "mcp_url": config.PUBLIC_MCP_URL,
        "google_client_id": config.GOOGLE_CLIENT_ID,
        "payments_enabled": bool(config.RAZORPAY_KEY_ID) or config.ALLOW_DEV_TOPUP,
    }
