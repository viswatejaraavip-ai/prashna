"""Udhyath on Google Cloud — the app served to the Android client.

Wires the launch workstreams (docs/launch/CONTRACT.md) into one FastAPI app.
The legacy AWS app (app.main: DynamoDB, /v1 metered API, web chat) is not
loaded here, so nothing on this path depends on AWS.
"""

import json
import logging
import re

from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, Response

from . import agent  # noqa: F401  (puts the engine on sys.path)
from . import routes_admin, routes_ai, routes_features, routes_platform, store
from .admin.errors import record_app_error

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Prashna", version="2.0.0", docs_url=None, redoc_url=None)
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
def healthz():
    return {"ok": True}
