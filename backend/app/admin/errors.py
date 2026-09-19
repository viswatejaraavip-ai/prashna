"""Unhandled-exception recorder for the `app_errors` collection.

Register in main.py:

    from app.admin.errors import record_app_error
    app.add_exception_handler(Exception, record_app_error)

HTTPExceptions are not routed here (FastAPI handles them first); only real
500s are. Writing the record must never raise.
"""

import logging
import traceback
from typing import Optional

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .. import store

log = logging.getLogger("udhyath.errors")

MAX_TRACEBACK = 4000
MAX_MESSAGE = 500


def _uid_from(request: Request) -> Optional[str]:
    auth = request.headers.get("authorization") or ""
    if not auth.lower().startswith("bearer "):
        return None
    try:
        import jwt
        claims = jwt.decode(auth[7:], store.JWT_SECRET, algorithms=["HS256"])
        return claims.get("sub")
    except Exception:
        return None


def build_error_doc(request: Request, exc: BaseException) -> dict:
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    return {
        "path": request.url.path,
        "method": request.method,
        "uid": _uid_from(request),
        "error_type": type(exc).__name__,
        "message": str(exc)[:MAX_MESSAGE],
        "traceback": tb[-MAX_TRACEBACK:],  # keep the innermost frames
        "status": 500,
        "created_at": store.now_iso(),
    }


def _write(doc: dict) -> None:
    store.fs().collection("app_errors").add(doc)


async def record_app_error(request: Request, exc: Exception) -> JSONResponse:
    try:
        doc = build_error_doc(request, exc)
        log.error("Unhandled %s on %s: %s", doc["error_type"], doc["path"], doc["message"])
        await run_in_threadpool(_write, doc)
    except Exception:  # the recorder must never make things worse
        log.exception("Failed to record app error")
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
