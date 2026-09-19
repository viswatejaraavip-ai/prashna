"""Firebase sign-in (phone OTP + Google), user bootstrap and the free trial.

Both the Android app and the operator dashboard sign in with Firebase Auth and
send the Firebase ID token here; we verify it with firebase-admin and answer
with our own app JWT (``store.issue_token``).

Trial: ``TRIAL_CREDIT_UNITS`` (default 1000 paise = one free query) is granted
once per account AND once per device. The raw device id never leaves this
module - only a salted SHA-256 is stored (``trial_devices/{hash}``).
"""

import hashlib
import logging
import os
from typing import Dict, Optional, Tuple

from . import billing, store

log = logging.getLogger("udhyath.auth")

TRIAL_CREDIT_UNITS = int(os.environ.get("TRIAL_CREDIT_UNITS", "1000"))
_DEVICE_SALT = os.environ.get("DEVICE_HASH_SALT", "udhyath-device-v1")
_PRIVATE_USER_FIELDS = ("device_hashes", "fcm_tokens")

_app = None


def firebase_app():
    """Lazy firebase-admin app using Application Default Credentials."""
    global _app
    if _app is None:
        import firebase_admin
        try:
            _app = firebase_admin.get_app()
        except ValueError:
            project = os.environ.get("FIREBASE_PROJECT_ID") or store.GCP_PROJECT
            _app = firebase_admin.initialize_app(
                options={"projectId": project} if project else None)
    return _app


def verify_firebase_token(id_token: str) -> Dict:
    """Verify a Firebase ID token; returns its decoded claims or raises 401."""
    if not id_token:
        raise store.ApiError(401, "Missing Firebase ID token", "forbidden")
    from firebase_admin import auth as fb_auth
    try:
        return fb_auth.verify_id_token(id_token, app=firebase_app(), check_revoked=True)
    except Exception as exc:  # invalid, expired, revoked, wrong project...
        log.info("firebase token rejected: %s", type(exc).__name__)
        raise store.ApiError(401, "Sign-in failed, please try again", "forbidden")


def device_hash(device_id: str) -> str:
    return hashlib.sha256((_DEVICE_SALT + ":" + device_id.strip()).encode()).hexdigest()


def public_user(user: Dict) -> Dict:
    out = {k: v for k, v in (user or {}).items() if k not in _PRIVATE_USER_FIELDS}
    out["plan"] = billing.effective_plan(user or {})
    out.setdefault("notif_prefs", {"daily": True, "transits": True, "promos": False})
    return out


def _new_user(uid: str, claims: Dict, lang: str, now: str) -> Dict:
    return {
        "uid": uid,
        "phone": claims.get("phone_number") or "",
        "email": (claims.get("email") or "").lower(),
        "name": claims.get("name") or "",
        "lang": lang,
        "role": "user",
        "balance_units": 0,
        "plan": "free",
        "plan_expires_at": None,
        "created_at": now,
        "device_hashes": [],
        "trial_claimed": False,
        "disclaimer_accepted_at": None,
        "deleted_at": None,
        "fcm_tokens": [],
        "notif_prefs": {"daily": True, "transits": True, "promos": False},
        "sign_in_provider": (claims.get("firebase") or {}).get("sign_in_provider", ""),
    }


def sign_in(claims: Dict, device_id: str = "", lang: str = "") -> Tuple[Dict, bool, bool]:
    """Create or load ``users/{uid}``, set ``lang``, grant the trial if eligible.

    Returns (user, created, trial_granted). One transaction covers the user
    doc, the device lock and the trial ledger entry, so two concurrent sign-ins
    can never grant twice. Signing in during the 30-day deletion grace period
    cancels the deletion."""
    uid = claims["uid"]
    lang = lang if lang in store.LANGS else ""
    dhash = device_hash(device_id) if device_id and len(device_id.strip()) >= 8 else ""
    db = store.fs()
    uref = db.collection("users").document(uid)
    dref = db.collection("trial_devices").document(dhash) if dhash else None
    lref = uref.collection("ledger").document("trial")
    now = store.now_iso()

    def _txn(txn):
        snap = uref.get(transaction=txn)
        dsnap = dref.get(transaction=txn) if dref is not None else None
        created = not snap.exists
        user = _new_user(uid, claims, lang or store.DEFAULT_LANG, now) if created \
            else (snap.to_dict() or {})
        updates: Dict = {"last_login_at": now}
        if not created:
            if lang:
                updates["lang"] = lang
            if user.get("deleted_at"):
                updates["deleted_at"] = None
            for field, claim in (("phone", "phone_number"), ("email", "email")):
                if claims.get(claim) and not user.get(field):
                    updates[field] = claims[claim].lower() if field == "email" else claims[claim]
        if dhash and dhash not in (user.get("device_hashes") or []):
            updates["device_hashes"] = ((user.get("device_hashes") or []) + [dhash])[-20:]
        granted = False
        if (TRIAL_CREDIT_UNITS > 0 and dref is not None and not user.get("trial_claimed")
                and not dsnap.exists):
            granted = True
            balance = int(user.get("balance_units") or 0) + TRIAL_CREDIT_UNITS
            updates.update(trial_claimed=True, balance_units=balance)
            txn.set(dref, {"uid": uid, "created_at": now})
            txn.set(lref, {"type": "trial", "delta_units": TRIAL_CREDIT_UNITS,
                           "balance_after": balance, "ref": "trial", "created_at": now})
        user.update(updates)
        if created:
            txn.set(uref, user)
        else:
            txn.update(uref, updates)
        return user, created, granted

    user, created, granted = store.run_transaction(_txn)
    try:
        fields: Dict = {}
        if created:
            fields["signups"] = 1
        if granted:
            fields["trials"] = 1
        if fields:
            store.incr_rollup(fields)
    except Exception:
        pass
    return user, created, granted


def admin_email_from(claims: Dict) -> Optional[str]:
    """The verified Google email on a Firebase token if it is an admin."""
    email = (claims.get("email") or "").lower()
    if email and claims.get("email_verified") and email in store.ADMIN_EMAILS:
        return email
    return None


def revoke_and_delete_firebase_user(uid: str, hard: bool = False) -> None:
    """Revoke refresh tokens (soft delete) or delete the Firebase user (purge)."""
    from firebase_admin import auth as fb_auth
    try:
        if hard:
            fb_auth.delete_user(uid, app=firebase_app())
        else:
            fb_auth.revoke_refresh_tokens(uid, app=firebase_app())
    except Exception as exc:  # user already gone etc.
        log.info("firebase user %s cleanup: %s", "delete" if hard else "revoke",
                 type(exc).__name__)
