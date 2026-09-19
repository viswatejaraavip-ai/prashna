"""Shared Firestore access + request helpers for the GCP build.

Every workstream imports from here so they agree on the client, the app JWT,
language selection and the daily rollup counters. See docs/launch/CONTRACT.md.

Local development: set FIRESTORE_EMULATOR_HOST (e.g. localhost:8080) and
GOOGLE_CLOUD_PROJECT; the client then talks to the emulator.
"""

import os
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

import jwt
from fastapi import Depends, Header, HTTPException, Request

GCP_PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", os.environ.get("GCP_PROJECT", ""))
JWT_SECRET = os.environ.get("JWT_SECRET", "change-me-in-production")
JWT_EXPIRY_HOURS = int(os.environ.get("JWT_EXPIRY_HOURS", str(24 * 30)))
ADMIN_EMAILS = {e.strip().lower() for e in os.environ.get("ADMIN_EMAILS", "").split(",")
                if e.strip()}
LANGS = ("hi", "te", "ta", "kn", "ml", "en")
# The app's name as written in each language's script.
BRAND = {"hi": "प्रश्न", "te": "ప్రశ్న", "ta": "பிரஷ்னா", "kn": "ಪ್ರಶ್ನ", "ml": "പ്രശ്ന", "en": "Prashna"}


def brand(lang: str) -> str:
    return BRAND.get(lang, BRAND["en"])
DEFAULT_LANG = os.environ.get("DEFAULT_LANG", "te")
IST = timezone(timedelta(hours=5, minutes=30))

_fs = None


def fs():
    """Process-wide Firestore client (lazy; honours FIRESTORE_EMULATOR_HOST)."""
    global _fs
    if _fs is None:
        from google.cloud import firestore
        _fs = firestore.Client(project=GCP_PROJECT or None)
    return _fs


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def today_key(dt: Optional[datetime] = None) -> str:
    """Rollup day key in IST, which is the business day for Indian users."""
    return (dt or datetime.now(timezone.utc)).astimezone(IST).strftime("%Y-%m-%d")


def incr_rollup(fields: Dict[str, float], day: Optional[str] = None) -> None:
    """Atomically add to rollups_daily/<day>. Dotted keys (by_lang.te) nest."""
    from google.cloud import firestore
    ref = fs().collection("rollups_daily").document(day or today_key())
    ref.set({k: firestore.Increment(v) for k, v in fields.items() if v}, merge=True)


# ---------- Runtime flags (operator kill switches) ----------

_FLAG_DEFAULTS = {
    "voice_cloud_enabled": True,
    "opus_enabled": True,
    "query_price_units": int(os.environ.get("QUERY_PRICE_UNITS", "1000")),
    "cost_ceiling_units": int(os.environ.get("QUERY_COST_CEILING_UNITS", "500")),
    "maintenance_message": "",
}
_flags_cache: Dict = {"at": 0.0, "val": None}


def get_flags() -> Dict:
    if _flags_cache["val"] is not None and time.time() - _flags_cache["at"] < 60:
        return _flags_cache["val"]
    val = dict(_FLAG_DEFAULTS)
    try:
        snap = fs().collection("config_flags").document("global").get()
        if snap.exists:
            val.update(snap.to_dict() or {})
    except Exception:  # flags must never take the app down
        pass
    _flags_cache.update(at=time.time(), val=val)
    return val


def clear_flags_cache() -> None:
    _flags_cache.update(at=0.0, val=None)


# ---------- App JWT ----------

def issue_token(uid: str, admin_email: str = "") -> str:
    now = int(time.time())
    claims = {"sub": uid, "iat": now, "exp": now + JWT_EXPIRY_HOURS * 3600}
    if admin_email:
        claims["adm"] = admin_email.lower()
        claims["exp"] = now + 12 * 3600
    return jwt.encode(claims, JWT_SECRET, algorithm="HS256")


def _claims(authorization: Optional[str]) -> Dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Missing token")
    try:
        return jwt.decode(authorization[7:], JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid or expired token")


def current_uid(authorization: Optional[str] = Header(None)) -> str:
    return _claims(authorization)["sub"]


def require_admin(authorization: Optional[str] = Header(None)) -> str:
    """Returns the admin's email. Admin tokens carry an `adm` claim."""
    email = _claims(authorization).get("adm", "")
    if not email or email not in ADMIN_EMAILS:
        raise HTTPException(403, "Admin only")
    return email


def get_user(uid: str) -> Optional[Dict]:
    snap = fs().collection("users").document(uid).get()
    if not snap.exists:
        return None
    user = snap.to_dict() or {}
    return None if user.get("deleted_at") else user


def current_user(uid: str = Depends(current_uid)) -> Dict:
    user = get_user(uid)
    if not user:
        raise HTTPException(401, "Account not found")
    return user


def lang_of(request: Request, user: Optional[Dict] = None) -> str:
    """?lang= beats Accept-Language beats the saved preference."""
    q = (request.query_params.get("lang") or "").lower()[:2]
    if q in LANGS:
        return q
    header = (request.headers.get("accept-language") or "").lower()[:2]
    if header in LANGS:
        return header
    saved = (user or {}).get("lang")
    return saved if saved in LANGS else DEFAULT_LANG


# ---------- Transactions + API errors (platform additions) ----------

def run_transaction(fn):
    """Run ``fn(transaction)`` in a Firestore transaction (retried on
    contention) and return its result. ``fn`` must do all reads through
    ``ref.get(transaction=transaction)`` before any ``transaction.set/update``
    and must be free of side effects, because Firestore may re-run it.
    Tests replace this function with an in-memory runner."""
    from google.cloud import firestore
    return firestore.transactional(fn)(fs().transaction())


class ApiError(HTTPException):
    """HTTPException that renders as the contract error body
    ``{"detail": "...", "code": "..."}`` once ``install_error_handlers(app)``
    is called (without it FastAPI still returns ``{"detail": ...}``)."""

    def __init__(self, status_code: int, detail: str, code: str = "invalid"):
        super().__init__(status_code=status_code, detail=detail)
        self.code = code


_STATUS_CODES = {400: "invalid", 401: "forbidden", 402: "insufficient_balance",
                 403: "forbidden", 404: "not_found", 409: "invalid",
                 422: "invalid", 429: "rate_limited", 503: "maintenance"}


def install_error_handlers(app) -> None:
    """Make every HTTPException (incl. ApiError and billing.InsufficientBalance)
    render as ``{"detail", "code"}``. Call once from main.py."""
    from fastapi.responses import JSONResponse
    from starlette.exceptions import HTTPException as StarletteHTTPException

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request, exc):  # noqa: ANN001
        headers = getattr(exc, "headers", None) or {}
        code = (getattr(exc, "code", None) or headers.get("X-Error-Code")
                or _STATUS_CODES.get(exc.status_code, "invalid"))
        body = {"detail": exc.detail, "code": code}
        for attr in ("needed_units", "balance_units"):
            if getattr(exc, attr, None) is not None:
                body[attr] = getattr(exc, attr)
        return JSONResponse(status_code=exc.status_code, content=body,
                            headers=headers or None)
