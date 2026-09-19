import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.abspath(os.path.join(HERE, "..", ".."))
for p in (BACKEND, HERE, os.path.join(BACKEND, "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

os.environ.setdefault("JWT_SECRET", "test-secret-for-admin-dashboard-tests-0123456789")

import pytest  # noqa: E402

from admin_fakefs import FakeFirestore  # noqa: E402

ADMIN = "owner@example.com"


@pytest.fixture
def db(monkeypatch):
    from app import store
    fake = FakeFirestore()
    monkeypatch.setattr(store, "_fs", fake)
    monkeypatch.setattr(store, "ADMIN_EMAILS", {ADMIN})
    store.clear_flags_cache()
    yield fake
    store.clear_flags_cache()


@pytest.fixture
def client(db):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app import routes_admin
    app = FastAPI()
    app.include_router(routes_admin.router)
    app.include_router(routes_admin.internal_router)
    return TestClient(app)


@pytest.fixture
def admin_headers():
    from app import store
    return {"Authorization": "Bearer " + store.issue_token("admin-uid", admin_email=ADMIN)}
