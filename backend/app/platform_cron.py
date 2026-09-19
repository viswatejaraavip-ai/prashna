"""Auth for Cloud Scheduler -> Cloud Run cron calls (``/internal/cron/*``).

    verify_cron(authorization: str | None = Header(None)) -> dict

FastAPI dependency. Validates the Google-signed OIDC ID token that Cloud
Scheduler attaches (``Authorization: Bearer <jwt>``): signature, expiry,
audience in ``CRON_AUDIENCES`` (comma-separated; terraform sets it to the
Cloud Run service URL and the custom domain) and ``email`` ==
``CRON_SA_EMAIL`` with ``email_verified``. Returns the token claims.

Usage::

    from .platform_cron import verify_cron
    @internal_router.post("/internal/cron/daily-push")
    def daily_push(claims: dict = Depends(verify_cron)): ...

Local development only: ``CRON_INSECURE_DEV=1`` skips verification when not
running on Cloud Run (``K_SERVICE`` unset).
"""

import logging
import os
from typing import Dict, Optional

from fastapi import Header, HTTPException

log = logging.getLogger("udhyath.cron")


def _audiences():
    raw = os.environ.get("CRON_AUDIENCES", os.environ.get("CRON_AUDIENCE", ""))
    return [a.strip().rstrip("/") for a in raw.split(",") if a.strip()]


def _verify_token(token: str) -> Dict:
    from google.auth.transport import requests as g_requests
    from google.oauth2 import id_token
    return id_token.verify_oauth2_token(token, g_requests.Request(), audience=None)


def verify_cron(authorization: Optional[str] = Header(None)) -> Dict:
    if os.environ.get("CRON_INSECURE_DEV") == "1" and not os.environ.get("K_SERVICE"):
        return {"email": "dev", "insecure": True}
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Missing scheduler token")
    audiences = _audiences()
    sa_email = os.environ.get("CRON_SA_EMAIL", "").lower()
    if not audiences or not sa_email:
        log.error("cron auth not configured (CRON_AUDIENCES / CRON_SA_EMAIL)")
        raise HTTPException(503, "Cron auth not configured")
    try:
        claims = _verify_token(authorization[7:].strip())
    except Exception as exc:
        log.warning("cron token rejected: %s", exc)
        raise HTTPException(401, "Invalid scheduler token")
    aud = str(claims.get("aud", "")).rstrip("/")
    if aud not in audiences:
        raise HTTPException(403, "Wrong audience")
    if (claims.get("email", "").lower() != sa_email
            or not claims.get("email_verified", False)):
        raise HTTPException(403, "Caller is not the scheduler service account")
    return claims
