"""Udhyath on Google Cloud — the app served to the Android client.

Wires the launch workstreams (docs/launch/CONTRACT.md) into one FastAPI app.
The legacy AWS app (app.main: DynamoDB, /v1 metered API, web chat) is not
loaded here, so nothing on this path depends on AWS.
"""

import contextlib
import json
import logging
import os
import re
import threading
import time

from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, Response

from . import agent  # noqa: F401  (puts the engine on sys.path)
from . import routes_admin, routes_ai, routes_features, routes_platform, store
from .admin.errors import record_app_error

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("udhyath.main")

# Cold starts are the app's worst latency (min_instance_count = 0 means the
# first user after an idle period waits for the container). Nothing heavy may
# be imported at module scope: `anthropic`, `google-genai`, `firebase-admin`,
# `fpdf2` and `PIL` are all imported lazily by the code that needs them, and
# tests/platform/test_perf_imports.py fails the build if that regresses.
WARMUP = os.environ.get("WARMUP_ON_START", "1").lower() not in ("0", "false", "no")


def warm_process() -> None:
    """Do the per-process one-off work before the first request needs it.

    Between them the steps cover almost everything a cold instance would
    otherwise do inside the user's very first request: the Firestore channel
    and ADC token, the Firebase signing certificates (measured at ~0.8 s the
    first time), the 500 KB places dataset, the i18n templates and the Swiss
    Ephemeris files the chart engine opens on first use.

    Each step runs on its own daemon thread: they are independent, and a step
    that hangs (an unreachable Firestore retries for minutes) must not stop
    the others from warming."""
    steps = (
        ("flags+firestore", store.get_flags),
        ("firebase", _warm_firebase),
        ("places", _warm_places),
        ("i18n", _warm_i18n),
        ("engine", _warm_engine),
    )

    def run(name, fn):
        t0 = time.monotonic()
        try:
            fn()
            log.info("warmup %s %d ms", name, (time.monotonic() - t0) * 1000)
        except Exception as exc:
            log.warning("warmup %s failed after %d ms: %s", name,
                        (time.monotonic() - t0) * 1000, exc)

    for name, fn in steps:
        threading.Thread(target=run, args=(name, fn), name="warmup-" + name,
                         daemon=True).start()


def _warm_firebase() -> None:
    from . import platform_auth
    platform_auth.warm()


def _warm_places() -> None:
    from .features import places
    places.load()


def _warm_i18n() -> None:
    from .features import common
    common.templates(store.DEFAULT_LANG)
    common.panchanga_names()


def _warm_engine() -> None:
    """One throwaway chart so swisseph opens its ephemeris files and the
    jyotish modules are imported before a user asks for a chart."""
    from jyotish import api as japi
    japi.birth_chart({"year": 1990, "month": 5, "day": 15, "hour": 10, "minute": 30,
                      "latitude": 17.385, "longitude": 78.4867, "tz_name": "Asia/Kolkata"})


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    if WARMUP:
        warm_process()  # fans out to one daemon thread per step; never blocks
    yield


app = FastAPI(title="Prashna", version="2.0.0", docs_url=None, redoc_url=None,
              lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1024)
store.install_error_handlers(app)
app.add_exception_handler(Exception, record_app_error)

for module in (routes_platform, routes_ai, routes_features, routes_admin):
    app.include_router(module.router)
    internal = getattr(module, "internal_router", None)
    if internal is not None:
        app.include_router(internal)


@app.middleware("http")
async def localize_error_details(request, call_next):
    """Error `detail` strings are written in English across the modules;
    translate them into the caller's language (Accept-Language / ?lang=) so
    the app never shows English to a Telugu/Hindi/... user. Cached; on any
    failure the original response goes out unchanged."""
    response = await call_next(request)
    if response.status_code < 400 or request.url.path.startswith(("/api/admin", "/admin", "/internal")):
        return response
    lang = store.lang_of(request)
    if lang == "en" or "json" not in (response.headers.get("content-type") or ""):
        return response
    body = b"".join([chunk async for chunk in response.body_iterator])
    headers = {k: v for k, v in response.headers.items() if k.lower() != "content-length"}
    try:
        data = json.loads(body)
        detail = data.get("detail") if isinstance(data, dict) else None
        if isinstance(detail, str) and re.search(r"[A-Za-z]{2}", detail):
            from starlette.concurrency import run_in_threadpool
            from .features.translate import translate_many
            data["detail"] = (await run_in_threadpool(translate_many, [detail], lang))[0]
            return JSONResponse(data, status_code=response.status_code, headers=headers)
    except Exception:
        pass
    return Response(body, status_code=response.status_code, headers=headers,
                    media_type=response.media_type)


@app.get("/healthz", include_in_schema=False)
@app.get("/api/healthz", include_in_schema=False)
def healthz():
    """Both paths on purpose: the Google Front End answers `/healthz` itself
    with its own 404 page and never forwards it to the container, so uptime
    checks, the app's start-up warm ping and anything else outside Cloud Run
    must use `/api/healthz`."""
    return {"ok": True}
