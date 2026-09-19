"""Platform HTTP routes: auth, profile/me, wallet & payments, compliance, legal.

The lead wires these into main.py::

    from . import routes_platform, store
    app.include_router(routes_platform.router)
    app.include_router(routes_platform.internal_router)
    store.install_error_handlers(app)   # {"detail", "code"} error bodies
"""

from typing import Dict, Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from . import platform_auth, platform_compliance, platform_legal, platform_wallet, store
from .platform_cron import verify_cron

router = APIRouter(tags=["platform"])
internal_router = APIRouter(tags=["internal"], include_in_schema=False)


def _user_or_404(uid: str) -> Dict:
    user = store.get_user(uid)
    if not user:
        raise store.ApiError(404, "Account not found", "not_found")
    return user


# ---------------- Auth ----------------

class FirebaseAuthIn(BaseModel):
    id_token: str = Field(min_length=1, max_length=8192)
    device_id: str = Field(default="", max_length=200)
    lang: str = Field(default="", max_length=5)


@router.post("/api/auth/firebase")
def auth_firebase(body: FirebaseAuthIn):
    claims = platform_auth.verify_firebase_token(body.id_token)
    user, created, granted = platform_auth.sign_in(claims, body.device_id, body.lang.lower())
    return {"token": store.issue_token(user["uid"]), "user": platform_auth.public_user(user),
            "created": created, "trial_granted": granted}


class AdminLoginIn(BaseModel):
    id_token: str = Field(min_length=1, max_length=8192)


@router.post("/api/admin/login")
def admin_login(body: AdminLoginIn):
    claims = platform_auth.verify_firebase_token(body.id_token)
    email = platform_auth.admin_email_from(claims)
    if not email:
        raise store.ApiError(403, "This Google account is not an operator", "forbidden")
    return {"token": store.issue_token(claims["uid"], admin_email=email), "email": email}


@router.get("/api/firebase-config")
def firebase_config():
    """Public Firebase web config for the operator dashboard's Google sign-in."""
    import os
    project = os.environ.get("FIREBASE_PROJECT_ID") or store.GCP_PROJECT
    return {"apiKey": os.environ.get("FIREBASE_WEB_API_KEY", ""),
            "authDomain": os.environ.get("FIREBASE_AUTH_DOMAIN",
                                         "%s.firebaseapp.com" % project if project else ""),
            "projectId": project,
            "appId": os.environ.get("FIREBASE_WEB_APP_ID", "")}


# ---------------- Me ----------------

@router.get("/api/me")
def get_me(uid: str = Depends(store.current_uid)):
    user = _user_or_404(uid)
    return {"user": platform_auth.public_user(user), "pricing": platform_wallet.pricing()}


class NotifPrefs(BaseModel):
    daily: Optional[bool] = None
    transits: Optional[bool] = None
    promos: Optional[bool] = None


class MePatch(BaseModel):
    name: Optional[str] = Field(default=None, max_length=100)
    lang: Optional[str] = None
    notif_prefs: Optional[NotifPrefs] = None
    role: Optional[str] = None


@router.patch("/api/me")
def patch_me(body: MePatch, uid: str = Depends(store.current_uid)):
    user = _user_or_404(uid)
    updates: Dict = {}
    if body.name is not None:
        updates["name"] = body.name.strip()
    if body.lang is not None:
        if body.lang not in store.LANGS:
            raise store.ApiError(400, "lang must be one of %s" % ", ".join(store.LANGS), "invalid")
        updates["lang"] = body.lang
    if body.role is not None:
        if body.role not in ("user", "astrologer"):
            raise store.ApiError(400, "role must be user or astrologer", "invalid")
        updates["role"] = body.role
    if body.notif_prefs is not None:
        prefs = dict(user.get("notif_prefs") or {"daily": True, "transits": True, "promos": False})
        prefs.update({k: v for k, v in body.notif_prefs.model_dump().items() if v is not None})
        updates["notif_prefs"] = prefs
    if updates:
        updates["updated_at"] = store.now_iso()
        store.fs().collection("users").document(uid).update(updates)
        user.update(updates)
    return {"user": platform_auth.public_user(user)}


class FcmTokenIn(BaseModel):
    token: str = Field(min_length=10, max_length=4096)


@router.post("/api/me/fcm-token")
def add_fcm_token(body: FcmTokenIn, uid: str = Depends(store.current_uid)):
    from .platform_push import MAX_TOKENS_PER_USER
    ref = store.fs().collection("users").document(uid)

    def _txn(txn):
        snap = ref.get(transaction=txn)
        if not snap.exists:
            raise store.ApiError(404, "Account not found", "not_found")
        tokens = [t for t in ((snap.to_dict() or {}).get("fcm_tokens") or []) if t != body.token]
        tokens = (tokens + [body.token])[-MAX_TOKENS_PER_USER:]
        txn.update(ref, {"fcm_tokens": tokens})
        return len(tokens)

    return {"ok": True, "devices": store.run_transaction(_txn)}


class DisclaimerIn(BaseModel):
    version: str = Field(default="", max_length=20)  # "" = the current TERMS_VERSION


@router.post("/api/me/disclaimer")
def accept_disclaimer(body: Optional[DisclaimerIn] = None, uid: str = Depends(store.current_uid)):
    _user_or_404(uid)
    from .platform_legal import TERMS_VERSION
    return platform_compliance.accept_disclaimer(uid, (body or DisclaimerIn()).version or TERMS_VERSION)


@router.get("/api/me/export")
def export_me(uid: str = Depends(store.current_uid)):
    _user_or_404(uid)
    return platform_compliance.export_user(uid)


@router.delete("/api/me")
def delete_me(uid: str = Depends(store.current_uid)):
    _user_or_404(uid)
    return platform_compliance.soft_delete(uid)


# ---------------- Pricing & wallet ----------------

@router.get("/api/pricing")
def pricing():
    return platform_wallet.pricing()


@router.get("/api/wallet/ledger")
def wallet_ledger(limit: int = Query(50, ge=1, le=200), uid: str = Depends(store.current_uid)):
    user = _user_or_404(uid)
    q = (store.fs().collection("users").document(uid).collection("ledger")
         .order_by("created_at", direction="DESCENDING").limit(limit))
    return {"balance_units": int(user.get("balance_units") or 0),
            "entries": [dict(d.to_dict() or {}, id=d.id) for d in q.stream()]}


class PlayVerifyIn(BaseModel):
    product_id: str = Field(max_length=64)
    purchase_token: str = Field(min_length=16, max_length=1024)


@router.post("/api/wallet/play/verify")
def play_verify(body: PlayVerifyIn, uid: str = Depends(store.current_uid)):
    _user_or_404(uid)
    return platform_wallet.verify_play_purchase(uid, body.product_id, body.purchase_token)


class RazorpayOrderIn(BaseModel):
    amount_rupees: int


@router.post("/api/wallet/razorpay/order")
def razorpay_order(body: RazorpayOrderIn, uid: str = Depends(store.current_uid)):
    _user_or_404(uid)
    return platform_wallet.razorpay_order(uid, body.amount_rupees)


class RazorpayVerifyIn(BaseModel):
    order_id: str = Field(max_length=100)
    payment_id: str = Field(max_length=100)
    signature: str = Field(max_length=200)


@router.post("/api/wallet/razorpay/verify")
def razorpay_verify(body: RazorpayVerifyIn, uid: str = Depends(store.current_uid)):
    return platform_wallet.razorpay_verify(uid, body.order_id, body.payment_id, body.signature)


# NOTE: the legacy main.py also defines POST /api/billing/webhook (DynamoDB).
# Whichever router is included first wins; on GCP the lead should include
# this router before (or instead of) the legacy route.
@router.post("/api/billing/webhook")
async def razorpay_webhook(request: Request):
    payload = (await request.body()).decode("utf-8")
    return platform_wallet.razorpay_webhook(payload, request.headers.get("x-razorpay-signature", ""))


@router.post("/api/plan/pro/purchase")
def pro_purchase(uid: str = Depends(store.current_uid)):
    return platform_wallet.purchase_pro(uid)


# ---------------- Refunds & support ----------------

class RefundIn(BaseModel):
    ref: str = Field(min_length=1, max_length=200)
    reason: str = Field(default="", max_length=2000)


@router.post("/api/refunds")
def create_refund(body: RefundIn, uid: str = Depends(store.current_uid)):
    _user_or_404(uid)
    return platform_compliance.request_refund(uid, body.ref, body.reason)


@router.get("/api/refunds")
def my_refunds(uid: str = Depends(store.current_uid)):
    return {"refunds": platform_compliance.list_refunds(uid)}


class SupportIn(BaseModel):
    category: str = Field(default="other", max_length=40)
    message: str = Field(min_length=3, max_length=5000)


@router.post("/api/support")
def create_support(body: SupportIn, uid: str = Depends(store.current_uid)):
    _user_or_404(uid)
    return platform_compliance.create_ticket(uid, body.category, body.message)


@router.get("/api/support")
def my_support(uid: str = Depends(store.current_uid)):
    return {"tickets": platform_compliance.list_tickets(uid)}


# ---------------- Legal ----------------

def _legal_lang(request: Request) -> str:
    q = (request.query_params.get("lang") or "").lower()[:2]
    return "en" if q == "en" else store.lang_of(request)


@router.get("/api/legal/{doc}")
def legal(doc: str, request: Request):
    if doc not in platform_legal.DOCS:
        raise store.ApiError(404, "Unknown document", "not_found")
    d = platform_legal.get_doc(doc, _legal_lang(request))
    return {"title": d["title"], "body_markdown": d["body_markdown"], "lang": d["lang"]}


@router.get("/legal/{doc}", response_class=HTMLResponse, include_in_schema=False)
def legal_page(doc: str, request: Request):
    """Public policy pages (Play Console privacy-policy URL etc.); English
    unless ?lang= is given."""
    if doc not in platform_legal.DOCS:
        raise store.ApiError(404, "Unknown document", "not_found")
    lang = (request.query_params.get("lang") or "en").lower()[:2]
    return HTMLResponse(platform_legal.render_html(doc, lang))


# ---------------- Cron ----------------

@internal_router.post("/internal/cron/purge-deleted")
def cron_purge_deleted(claims: Dict = Depends(verify_cron)):
    return platform_compliance.purge_deleted()
