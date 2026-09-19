"""Firebase Cloud Messaging helper.

    send_push(uid: str, title: str, body: str, data: dict | None = None,
              category: str | None = None) -> int
        Send a notification to every registered device of ``uid``; returns the
        number of devices that accepted it. ``data`` values are stringified.
        ``category`` ("daily" | "transits" | "promos") is checked against the
        user's ``notif_prefs`` - the push is skipped (returns 0) when the user
        opted out. Tokens FCM reports as unregistered/invalid are removed from
        ``users/{uid}.fcm_tokens``. Never raises for delivery problems.
"""

import logging
from typing import Dict, List, Optional

from . import store
from .platform_auth import firebase_app

log = logging.getLogger("udhyath.push")

_DEAD_TOKEN_ERRORS = ("UnregisteredError", "SenderIdMismatchError", "InvalidArgumentError")
MAX_TOKENS_PER_USER = 10


def _send(tokens: List[str], title: str, body: str, data: Dict[str, str]):
    """Returns a list parallel to ``tokens``: None on success or the error."""
    from firebase_admin import messaging
    msg = messaging.MulticastMessage(
        tokens=tokens,
        notification=messaging.Notification(title=title, body=body),
        data=data,
        android=messaging.AndroidConfig(
            priority="high",
            notification=messaging.AndroidNotification(channel_id="udhyath_default")),
    )
    resp = messaging.send_each_for_multicast(msg, app=firebase_app())
    return [None if r.success else r.exception for r in resp.responses]


def send_push(uid: str, title: str, body: str, data: Optional[Dict] = None,
              category: Optional[str] = None) -> int:
    user = store.get_user(uid)
    if not user:
        return 0
    if category and (user.get("notif_prefs") or {}).get(category) is False:
        return 0
    tokens = [t for t in (user.get("fcm_tokens") or []) if t][-MAX_TOKENS_PER_USER:]
    if not tokens:
        return 0
    payload = {str(k): str(v) for k, v in (data or {}).items()}
    try:
        results = _send(tokens, title[:200], body[:1000], payload)
    except Exception as exc:
        log.warning("FCM send failed for %s: %s", uid, exc)
        return 0
    # INVALID_ARGUMENT can also mean a bad payload; only treat it as a dead
    # token when some other device accepted the same message.
    any_ok = any(err is None for err in results)
    dead = [t for t, err in zip(tokens, results)
            if err is not None and type(err).__name__ in _DEAD_TOKEN_ERRORS
            and (any_ok or type(err).__name__ != "InvalidArgumentError")]
    if dead:
        try:
            from google.cloud import firestore
            store.fs().collection("users").document(uid).update(
                {"fcm_tokens": firestore.ArrayRemove(dead)})
        except Exception as exc:
            log.info("pruning FCM tokens for %s failed: %s", uid, exc)
    return sum(1 for err in results if err is None)
