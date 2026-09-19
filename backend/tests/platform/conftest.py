import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..")))  # backend/
sys.path.insert(0, HERE)

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("ADMIN_EMAILS", "boss@example.com")
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "test-project")
os.environ.setdefault("TRIAL_CREDIT_UNITS", "1000")

from platform_fakefs import FakeFirestore  # noqa: E402


@pytest.fixture
def fake(monkeypatch):
    from app import store
    db = FakeFirestore()
    monkeypatch.setattr(store, "_fs", db)
    monkeypatch.setattr(store, "run_transaction", db.run_transaction)
    # store may have been imported by another suite before our env defaults.
    monkeypatch.setattr(store, "ADMIN_EMAILS", {"boss@example.com"})
    store.clear_flags_cache()
    return db


@pytest.fixture
def firebase(monkeypatch):
    """Map fake ID tokens ("tok:<uid>[:email]") to claims."""
    from app import platform_auth

    def verify(token):
        if not token.startswith("tok:"):
            from app import store
            raise store.ApiError(401, "bad", "forbidden")
        parts = token.split(":")
        claims = {"uid": parts[1], "phone_number": "+919900000000",
                  "firebase": {"sign_in_provider": "phone"}}
        if len(parts) > 2 and "@" in parts[2]:
            claims.update(email=parts[2], email_verified=True)
        return claims

    monkeypatch.setattr(platform_auth, "verify_firebase_token", verify)
    monkeypatch.setattr(platform_auth, "revoke_and_delete_firebase_user",
                        lambda uid, hard=False: None)
    return verify


@pytest.fixture
def client(fake, firebase):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app import routes_platform, store
    app = FastAPI()
    app.include_router(routes_platform.router)
    app.include_router(routes_platform.internal_router)
    store.install_error_handlers(app)
    return TestClient(app)


def login(client, uid="u1", device="device-0001", lang="te"):
    r = client.post("/api/auth/firebase",
                    json={"id_token": "tok:" + uid + ":" + "x" * 8, "device_id": device, "lang": lang})
    assert r.status_code == 200, r.text
    return r.json(), {"Authorization": "Bearer " + r.json()["token"]}
