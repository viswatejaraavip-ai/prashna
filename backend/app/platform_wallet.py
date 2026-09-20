"""Top-ups (Google Play Billing primary, Razorpay for web / user-choice
billing), pricing, and the astrologer Pro plan.

Play: the Android app buys a consumable in-app product (``wallet_100`` ...),
then POSTs the purchase token here. We verify it with the Android Publisher
API, credit the wallet exactly once (``payments/{purchase_token}`` +
ledger idem key), then consume it so it can be bought again. The app must set
``BillingFlowParams.setObfuscatedAccountId(sha256_hex(firebase_uid))`` so a
token can't be redeemed by another account.
"""

import hashlib
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

from . import billing, store

log = logging.getLogger("udhyath.wallet")

PLAY_PACKAGE_NAME = os.environ.get("PLAY_PACKAGE_NAME", "com.prashna.app")
# product id -> rupees credited
PLAY_PRODUCTS = {"wallet_100": 100, "wallet_200": 200, "wallet_500": 500, "wallet_1000": 1000}
TOPUP_RUPEES = [100, 200, 500, 1000]
PRO_PLAN_UNITS = int(os.environ.get("PRO_PLAN_UNITS", "49900"))
PRO_PLAN_DAYS = int(os.environ.get("PRO_PLAN_DAYS", "30"))
REPORT_PRICE_UNITS = int(os.environ.get("REPORT_PRICE_UNITS",
                                        os.environ.get("REPORT_FEE_UNITS", "105000")))
RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "")
RAZORPAY_WEBHOOK_SECRET = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9._:\-]{16,1024}$")


def pricing(lang: str = "") -> Dict:
    from .platform_auth import TRIAL_CREDIT_UNITS
    # The report price is per language and lives in reports.py, which also
    # charges the wallet: advertise exactly what we debit.
    from . import reports
    return {
        "currency": "INR",
        "query_price_units": int(store.get_flags().get("query_price_units", 1000)),
        "report_price_units": reports.report_fee_units(lang),
        "pro_plan_units": PRO_PLAN_UNITS,
        "pro_plan_days": PRO_PLAN_DAYS,
        "trial_credit_units": TRIAL_CREDIT_UNITS,
        "topup_options": [{"amount_rupees": r, "amount_units": r * 100} for r in TOPUP_RUPEES],
        "play_products": [{"product_id": pid, "amount_rupees": r, "amount_units": r * 100}
                          for pid, r in PLAY_PRODUCTS.items()],
        "razorpay_enabled": bool(RAZORPAY_KEY_ID),
        **{k: v for k, v in reports.report_pricing().items() if k != "report_price_units"},
    }


def account_hash(uid: str) -> str:
    """Value the app passes as Play's obfuscatedAccountId."""
    return hashlib.sha256(uid.encode()).hexdigest()


# ---------------- Google Play ----------------

def _publisher():
    """Android Publisher v3 client on ADC (the runtime service account must be
    invited in Play Console with 'View financial data' + 'Manage orders')."""
    import google.auth
    from googleapiclient.discovery import build
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/androidpublisher"])
    return build("androidpublisher", "v3", credentials=creds, cache_discovery=False)


def play_get_purchase(product_id: str, token: str) -> Dict:
    return _publisher().purchases().products().get(
        packageName=PLAY_PACKAGE_NAME, productId=product_id, token=token).execute()


def play_consume(product_id: str, token: str) -> None:
    _publisher().purchases().products().consume(
        packageName=PLAY_PACKAGE_NAME, productId=product_id, token=token).execute()


def verify_play_purchase(uid: str, product_id: str, purchase_token: str) -> Dict:
    if product_id not in PLAY_PRODUCTS:
        raise store.ApiError(400, "Unknown product", "invalid")
    if not _TOKEN_RE.match(purchase_token or ""):
        raise store.ApiError(400, "Invalid purchase token", "invalid")
    pref = store.fs().collection("payments").document(purchase_token)
    existing = pref.get()
    if existing.exists:
        pay = existing.to_dict() or {}
        if pay.get("uid") != uid:
            raise store.ApiError(409, "Purchase belongs to another account", "invalid")
        if pay.get("status") in ("credited", "consumed"):
            if pay.get("status") != "consumed":
                _try_consume(pref, product_id, purchase_token)
            return {"credited": False, "already_processed": True,
                    "balance_units": billing.get_balance(uid)}
    try:
        purchase = play_get_purchase(product_id, purchase_token)
    except Exception as exc:
        log.warning("Play verify failed: %s", exc)
        raise store.ApiError(400, "Could not verify the purchase with Google Play", "invalid")
    state = purchase.get("purchaseState", 0)
    if state == 2:
        raise store.ApiError(409, "Payment is pending; your wallet will be credited "
                             "once Google Play confirms it", "invalid")
    if state != 0:
        raise store.ApiError(400, "Purchase was cancelled", "invalid")
    acct = purchase.get("obfuscatedExternalAccountId")
    if acct and acct != account_hash(uid):
        raise store.ApiError(409, "Purchase belongs to another account", "invalid")
    if purchase.get("consumptionState") == 1 and not existing.exists:
        raise store.ApiError(409, "Purchase was already used", "invalid")
    units = PLAY_PRODUCTS[product_id] * 100
    order_id = purchase.get("orderId", "")
    now = store.now_iso()
    pref.set({"uid": uid, "provider": "play", "product_id": product_id,
              "amount_units": units, "status": "verified", "order_id": order_id,
              "test": purchase.get("purchaseType") == 0, "created_at": now,
              "raw": {k: purchase.get(k) for k in (
                  "orderId", "purchaseState", "consumptionState", "purchaseTimeMillis",
                  "purchaseType", "regionCode", "acknowledgementState")}}, merge=True)
    balance = billing.credit(uid, units, "topup", "play:" + (order_id or purchase_token[:40]),
                             meta={"provider": "play", "product_id": product_id},
                             idem_key="play_" + hashlib.sha256(purchase_token.encode()).hexdigest())
    pref.update({"status": "credited", "credited_at": store.now_iso()})
    _try_consume(pref, product_id, purchase_token)
    return {"credited": True, "amount_units": units, "balance_units": balance}


def _try_consume(pref, product_id: str, token: str) -> None:
    try:
        play_consume(product_id, token)
        pref.update({"status": "consumed", "consumed_at": store.now_iso()})
    except Exception as exc:  # credited already; the app retries verify later
        log.warning("Play consume failed (will retry on next verify): %s", exc)


# ---------------- Razorpay ----------------

def _razorpay():
    if not RAZORPAY_KEY_ID:
        raise store.ApiError(503, "Card/UPI payments are not enabled", "maintenance")
    import razorpay
    return razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))


def razorpay_order(uid: str, amount_rupees: int) -> Dict:
    if amount_rupees not in TOPUP_RUPEES:
        raise store.ApiError(400, "Amount must be one of %s" % TOPUP_RUPEES, "invalid")
    units = amount_rupees * 100
    order = _razorpay().order.create({"amount": units, "currency": "INR",
                                      "notes": {"uid": uid}})
    store.fs().collection("payments").document(order["id"]).set({
        "uid": uid, "provider": "razorpay", "amount_units": units,
        "status": "created", "created_at": store.now_iso(), "raw": {"order": order.get("id")}})
    return {"order_id": order["id"], "key_id": RAZORPAY_KEY_ID, "amount_units": units,
            "currency": "INR"}


def _complete_razorpay(order_id: str, payment_id: str = "", uid: Optional[str] = None) -> Dict:
    """Credit a Razorpay order once (verify + webhook may both arrive)."""
    pref = store.fs().collection("payments").document(order_id)
    snap = pref.get()
    if not snap.exists:
        raise store.ApiError(404, "Unknown order", "not_found")
    pay = snap.to_dict() or {}
    if uid is not None and pay.get("uid") != uid:
        raise store.ApiError(403, "Order belongs to another account", "forbidden")
    balance = billing.credit(pay["uid"], int(pay["amount_units"]), "topup",
                             "razorpay:" + order_id,
                             meta={"provider": "razorpay", "payment_id": payment_id},
                             idem_key="rzp_" + order_id)
    if pay.get("status") != "credited":
        pref.update({"status": "credited", "payment_id": payment_id,
                     "credited_at": store.now_iso()})
    return {"balance_units": balance, "amount_units": int(pay["amount_units"])}


def razorpay_verify(uid: str, order_id: str, payment_id: str, signature: str) -> Dict:
    client = _razorpay()
    import razorpay
    try:
        client.utility.verify_payment_signature({
            "razorpay_order_id": order_id, "razorpay_payment_id": payment_id,
            "razorpay_signature": signature})
    except razorpay.errors.SignatureVerificationError:
        raise store.ApiError(400, "Payment signature verification failed", "invalid")
    return _complete_razorpay(order_id, payment_id, uid=uid)


def razorpay_webhook(payload: str, signature: str) -> Dict:
    if not RAZORPAY_WEBHOOK_SECRET:
        raise store.ApiError(503, "Webhook not configured", "maintenance")
    import razorpay
    try:
        _razorpay().utility.verify_webhook_signature(payload, signature, RAZORPAY_WEBHOOK_SECRET)
    except razorpay.errors.SignatureVerificationError:
        raise store.ApiError(400, "Invalid webhook signature", "invalid")
    event = json.loads(payload)
    if event.get("event") == "payment.captured":
        entity = event["payload"]["payment"]["entity"]
        if entity.get("order_id"):
            try:
                _complete_razorpay(entity["order_id"], entity.get("id", ""))
            except store.ApiError as exc:
                if exc.status_code != 404:  # orders from the legacy web app
                    raise
    return {"received": True}


# ---------------- Astrologer Pro plan ----------------

def purchase_pro(uid: str) -> Dict:
    """Debit PRO_PLAN_UNITS and extend the plan by PRO_PLAN_DAYS (stacking on
    an unexpired plan)."""
    now = datetime.now(timezone.utc)
    result: Dict = {}

    def _updates(user: Dict) -> Dict:
        current = user.get("plan_expires_at") or ""
        start = now
        if user.get("plan") == "pro" and current > now.isoformat():
            start = datetime.fromisoformat(current)
        expires = (start + timedelta(days=PRO_PLAN_DAYS)).isoformat()
        result["plan_expires_at"] = expires
        return {"plan": "pro", "plan_expires_at": expires}

    balance, _ = billing._apply(uid, -PRO_PLAN_UNITS, "subscription", "pro_plan",
                                meta={"days": PRO_PLAN_DAYS}, user_updates=_updates)
    try:
        store.incr_rollup({"revenue_units": PRO_PLAN_UNITS, "pro_purchases": 1})
    except Exception:
        pass
    return {"plan": "pro", "plan_expires_at": result["plan_expires_at"],
            "balance_units": balance}
