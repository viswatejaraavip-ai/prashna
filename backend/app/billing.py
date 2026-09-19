"""Prepaid wallet (Firestore). Money is always integer paise ("units").

Public API for every workstream (import as ``from app import billing``)::

    charge(uid: str, units: int, type: str, ref: str = "", *,
           meta: dict | None = None, idem_key: str | None = None) -> int
        Debit ``units`` (> 0). Returns balance_after. Raises
        billing.InsufficientBalance (HTTP 402, code "insufficient_balance")
        if the wallet would go negative; billing.AccountNotFound (404) if the
        user is missing or soft-deleted.

    credit(uid: str, units: int, type: str, ref: str = "", *,
           meta: dict | None = None, idem_key: str | None = None) -> int
        Add ``units`` (> 0). Returns balance_after.

    refund(uid: str, units: int, ref: str = "", reason: str = "", *,
           idem_key: str | None = None) -> int
        credit() with type "refund" (e.g. a failed report or query). A
        ``type="refund"`` keyword is accepted for symmetry with credit().

    adjust(uid: str, delta_units: int, reason: str, admin_email: str) -> int
        Operator correction (type "adjust"); may be negative, never below 0.

    get_balance(uid: str) -> int
    effective_plan(user: dict) -> "free" | "pro"   (honours plan_expires_at)

``type`` is a ledger type: topup | query | report | refund | trial |
subscription | adjust. ``ref`` points at the thing paid for (trace id,
report id, payment id...). Every change runs in one Firestore transaction
that updates ``users/{uid}.balance_units`` and writes a
``users/{uid}/ledger`` entry ``{type, delta_units, balance_after, ref,
created_at, meta?}``. Pass ``idem_key`` to make a call safe to retry: the
ledger entry id is derived from it, and a second call with the same key is a
no-op that returns the current balance.

charge()/credit() do not touch rollups_daily revenue counters - callers
record ``revenue_units`` themselves (top-ups and refunds are counted here as
``topups_units`` / ``refunds_units``).

The functions further down, under "Legacy", serve only the old DynamoDB web
app and /v1 API (main.py, public_api.py) and import ``db``
lazily so this module stays AWS-free on the new path. A legacy call is one
that passes an email and no ``type``: ``charge(email, units)``.
"""

import hashlib
import math
import re
from datetime import datetime, timezone
from typing import Callable, Dict, Optional, Tuple

from . import store

LEDGER_TYPES = ("topup", "query", "report", "refund", "trial", "subscription", "adjust")


class InsufficientBalance(store.ApiError):
    def __init__(self, needed_units: int, balance_units: int = -1):
        super().__init__(402, "Insufficient balance: need %d paise, have %d"
                         % (needed_units, max(balance_units, 0)),
                         "insufficient_balance")
        self.needed_units = needed_units
        self.balance_units = balance_units


class AccountNotFound(store.ApiError):
    def __init__(self):
        super().__init__(404, "Account not found", "not_found")


def _ledger_id(idem_key: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_\-]", "_", idem_key)[:80]
    return "k_%s_%s" % (safe, hashlib.sha256(idem_key.encode()).hexdigest()[:12])


def _apply(uid: str, delta: int, type_: str, ref: str = "", *,
           meta: Optional[Dict] = None, idem_key: Optional[str] = None,
           user_updates: Optional[Callable[[Dict], Dict]] = None,
           ) -> Tuple[int, bool]:
    """Core wallet mutation. Returns (balance_after, applied)."""
    if type_ not in LEDGER_TYPES:
        raise ValueError("unknown ledger type %r" % type_)
    if not isinstance(delta, int) or isinstance(delta, bool):
        raise ValueError("units must be an int number of paise")
    uref = store.fs().collection("users").document(uid)
    ledger = uref.collection("ledger")
    lref = ledger.document(_ledger_id(idem_key)) if idem_key else ledger.document()
    now = store.now_iso()

    def _txn(txn):
        snap = uref.get(transaction=txn)
        user = (snap.to_dict() or {}) if snap.exists else None
        if user is None or user.get("deleted_at"):
            raise AccountNotFound()
        balance = int(user.get("balance_units") or 0)
        if idem_key and lref.get(transaction=txn).exists:
            return balance, False
        after = balance + delta
        if after < 0:
            raise InsufficientBalance(-delta if delta < 0 else 0, balance)
        updates = {"balance_units": after, "updated_at": now}
        if user_updates:
            updates.update(user_updates(user))
        entry = {"type": type_, "delta_units": delta, "balance_after": after,
                 "ref": ref or "", "created_at": now}
        if meta:
            entry["meta"] = meta
        txn.update(uref, updates)
        txn.set(lref, entry)
        return after, True

    after, applied = store.run_transaction(_txn)
    if applied:
        try:
            if type_ == "topup":
                store.incr_rollup({"topups_units": delta})
            elif type_ == "refund":
                store.incr_rollup({"refunds_units": delta})
        except Exception:  # rollups are best-effort analytics
            pass
    return after, applied


def _positive(units) -> int:
    if not isinstance(units, int) or isinstance(units, bool) or units <= 0:
        raise ValueError("units must be a positive int (paise)")
    return units


def charge(uid: str, units: int, type: Optional[str] = None, ref: str = "", *,  # noqa: A002
           meta: Optional[Dict] = None, idem_key: Optional[str] = None) -> int:
    if type is None:
        return _legacy_adjust(uid, -units)
    return _apply(uid, -_positive(units), type, ref, meta=meta, idem_key=idem_key)[0]


def credit(uid: str, units: int, type: Optional[str] = None, ref: str = "", *,  # noqa: A002
           meta: Optional[Dict] = None, idem_key: Optional[str] = None) -> int:
    if type is None:
        return _legacy_adjust(uid, units)
    return _apply(uid, _positive(units), type, ref, meta=meta, idem_key=idem_key)[0]


def refund(uid: str, units: int, ref: str = "", reason: str = "", *,
           idem_key: Optional[str] = None, type: str = "refund") -> int:  # noqa: A002
    if type != "refund":
        raise ValueError("refund() always writes ledger type 'refund'")
    return _apply(uid, _positive(units), "refund", ref,
                  meta={"reason": reason[:500]} if reason else None,
                  idem_key=idem_key)[0]


def adjust(uid: str, delta_units: int, reason: str, admin_email: str) -> int:
    if not isinstance(delta_units, int) or delta_units == 0:
        raise ValueError("delta_units must be a non-zero int")
    return _apply(uid, delta_units, "adjust", "admin:" + admin_email,
                  meta={"reason": reason[:500], "by": admin_email})[0]


def get_balance(uid: str) -> int:
    snap = store.fs().collection("users").document(uid).get()
    return int((snap.to_dict() or {}).get("balance_units") or 0) if snap.exists else 0


def effective_plan(user: Dict) -> str:
    if (user or {}).get("plan") != "pro":
        return "free"
    exp = user.get("plan_expires_at") or ""
    return "pro" if exp and exp > datetime.now(timezone.utc).isoformat() else "free"


# ===================== Legacy (DynamoDB; old web app + /v1) =====================
# Used only by the legacy main.py / public_api.py, which still call
# charge(email, units) / credit(email, units). Not part of the GCP path.

def _legacy_adjust(email: str, delta_units: int) -> int:
    if "@" not in str(email):
        raise TypeError("billing.charge/credit need a ledger `type` "
                        "(topup|query|report|refund|trial|subscription|adjust)")
    from . import db
    return db.adjust_balance(email, delta_units)


def token_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    from . import config
    price = config.model_price(model)
    return input_tokens * price["input"] / 1e6 + output_tokens * price["output"] / 1e6


def user_charge_units(model: str, input_tokens: int, output_tokens: int) -> int:
    from . import config
    usd = token_cost_usd(model, input_tokens, output_tokens)
    units = usd * config.USD_TO_WALLET_RATE * 100 * config.BILLING_MARGIN
    return max(1, int(math.ceil(units)))


def start_session(email: str) -> Dict:
    """Open a legacy chat session. Free - billing happens per question."""
    from . import config, db
    if config.SESSION_FEE_UNITS:
        _legacy_adjust(email, -config.SESSION_FEE_UNITS)
    return db.create_session(email, config.SESSION_FEE_UNITS)


def question_fee_units(is_first: bool) -> int:
    from . import config
    return (config.AGENT_FIRST_QUESTION_FEE_UNITS if is_first
            else config.AGENT_FOLLOWUP_FEE_UNITS)


def record_usage(email: str, session_id: str, model: str,
                 input_tokens: int, output_tokens: int,
                 is_first: bool = False) -> int:
    """Legacy flat question fee; a trial account's first question is free."""
    from . import db
    units = question_fee_units(is_first)
    if is_first and db.consume_free_session(email):
        units = 0
    if units:
        _legacy_adjust(email, -units)
    db.record_session_usage(session_id, units, input_tokens, output_tokens)
    return units


def can_send_message(user: Dict, is_first: bool = False) -> bool:
    if is_first and int(user.get("free_sessions", 0) or 0) > 0:
        return True
    return user["balance_units"] >= question_fee_units(is_first)


def pricing_info() -> dict:
    """Legacy web pricing payload (GET /api/pricing in main.py)."""
    from . import config
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
