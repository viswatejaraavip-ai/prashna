import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

os.environ.setdefault("JWT_SECRET", "features-test-secret-0123456789abcdef")
os.environ.setdefault("CRON_INSECURE_DEV", "1")
os.environ.pop("K_SERVICE", None)

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(os.path.dirname(HERE))
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from tests.features.fakefs import FakeFirestore  # noqa: E402


@pytest.fixture()
def db(monkeypatch):
    from app import store
    fake = FakeFirestore()
    monkeypatch.setattr(store, "_fs", fake)
    from app.features import daily
    daily._MEM.clear()
    return fake


def make_user(db, uid="u1", role="user", plan="free", expires_days=None, lang="te", **extra):
    doc = {"uid": uid, "role": role, "plan": plan, "lang": lang, "balance_units": 0,
           "created_at": "2026-01-01T00:00:00+00:00",
           "notif_prefs": {"daily": True, "transits": True, "promos": False}}
    if expires_days is not None:
        doc["plan_expires_at"] = (datetime.now(timezone.utc)
                                  + timedelta(days=expires_days)).isoformat()
    doc.update(extra)
    db.collection("users").document(uid).set(doc)
    return doc


@pytest.fixture()
def client(db):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app import routes_features
    app = FastAPI()
    app.include_router(routes_features.router)
    app.include_router(routes_features.internal_router)
    return TestClient(app)


def auth(uid="u1"):
    from app import store
    return {"Authorization": "Bearer " + store.issue_token(uid)}


RAVI = {"name": "Ravi", "relation": "self", "gender": "male",
        "birth": {"date": "1990-08-15", "time": "10:30", "place": "Hyderabad"}}
SITA = {"name": "Sita", "relation": "spouse", "gender": "female",
        "birth": {"date": "1993-03-02", "time": "18:45", "lat": 13.0878, "lon": 80.2785,
                  "tz": "Asia/Kolkata", "place": "Chennai"}}
