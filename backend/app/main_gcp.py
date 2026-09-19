"""Udhyath on Google Cloud — the app served to the Android client.

Wires the launch workstreams (docs/launch/CONTRACT.md) into one FastAPI app.
The legacy AWS app (app.main: DynamoDB, /v1 metered API, web chat) is not
loaded here, so nothing on this path depends on AWS.
"""

import logging

from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware

from . import agent  # noqa: F401  (puts the engine on sys.path)
from . import routes_admin, routes_ai, routes_features, routes_platform, store
from .admin.errors import record_app_error

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Udhyath", version="2.0.0", docs_url=None, redoc_url=None)
app.add_middleware(GZipMiddleware, minimum_size=1024)
store.install_error_handlers(app)
app.add_exception_handler(Exception, record_app_error)

for module in (routes_platform, routes_ai, routes_features, routes_admin):
    app.include_router(module.router)
    internal = getattr(module, "internal_router", None)
    if internal is not None:
        app.include_router(internal)


@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"ok": True}
