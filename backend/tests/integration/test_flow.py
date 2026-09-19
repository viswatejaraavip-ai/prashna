"""End-to-end through main_gcp: real routes, wallet, Firestore data layer
(in-memory fake) and engine; only the Gemini/Claude clients are faked."""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
for p in (os.path.dirname(TESTS), os.path.join(TESTS, "platform"), os.path.join(TESTS, "ai")):
    if p not in sys.path:
        sys.path.insert(0, p)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from ai_fakes import FakeClaude, FakeGemini  # noqa: E402
from platform_fakefs import FakeFirestore  # noqa: E402

ADMIN = "owner@example.com"


@pytest.fixture
def app_client(monkeypatch):
    from app import main_gcp, platform_auth, store
    from app.ai import llm
    db = FakeFirestore()
    monkeypatch.setattr(store, "_fs", db)
    monkeypatch.setattr(store, "run_transaction", db.run_transaction)
    monkeypatch.setattr(store, "ADMIN_EMAILS", {ADMIN})
    store.clear_flags_cache()

    def verify(token):
        uid, _, email = token.partition(":")
        claims = {"uid": uid, "phone_number": "+919900000001",
                  "firebase": {"sign_in_provider": "phone"}}
        if email:
            claims.update(email=email, email_verified=True)
        return claims
    monkeypatch.setattr(platform_auth, "verify_firebase_token", verify)
    llm.reset_capabilities()
    monkeypatch.setattr(llm, "_gemini", FakeGemini())
    monkeypatch.setattr(llm, "_claude", FakeClaude())
    return TestClient(main_gcp.app, raise_server_exceptions=False), db


def test_signup_profile_ask_charge_and_dashboard(app_client):
    client, db = app_client
    r = client.post("/api/auth/firebase",
                    json={"id_token": "u1", "device_id": "dev-1", "lang": "te"})
    assert r.status_code == 200, r.text
    h = {"Authorization": "Bearer " + r.json()["token"]}
    start = client.get("/api/me", headers=h).json()["user"]["balance_units"]

    # Top up through the real wallet (Play verification is out of scope here).
    from app import billing
    billing.credit("u1", 5000, "topup", "test-topup")

    r = client.post("/api/profiles", headers=h, json={
        "name": "Ravi", "relation": "self",
        "birth": {"date": "1990-05-14", "time": "06:30", "place": "Hyderabad"},
        "time_known": True})
    assert r.status_code in (200, 201), r.text
    pid = r.json().get("id") or r.json().get("profile", {}).get("id") or r.json().get("profile_id")
    assert pid, r.json()

    r = client.get("/api/profiles/%s/snapshot" % pid, headers=h)
    assert r.status_code == 200, r.text

    r = client.post("/api/sessions", headers=h, json={"profile_id": pid, "mode": "text"})
    assert r.status_code == 200, r.text
    sid = r.json()["session_id"]
    r = client.post("/api/sessions/%s/ask" % sid, headers=h,
                    json={"text": "నా ఉద్యోగం ఎప్పుడు మారుతుంది?"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok", body
    assert body["charged_units"] == 1000
    assert body["balance_units"] == start + 5000 - 1000

    trace = db.collection("traces").document(body["trace_id"]).get().to_dict()
    assert trace["cost_units"] < 500
    ledger = [d.to_dict()["type"] for d in
              db.collection("users").document("u1").collection("ledger").stream()]
    assert "query" in ledger

    # Operator sees it.
    r = client.post("/api/admin/login", json={"id_token": "adm:" + ADMIN})
    assert r.status_code == 200, r.text
    ah = {"Authorization": "Bearer " + r.json()["token"]}
    r = client.get("/api/admin/overview?days=7", headers=ah)
    assert r.status_code == 200, r.text
    r = client.get("/api/admin/traces/" + body["trace_id"], headers=ah)
    assert r.status_code == 200, r.text

    # DPDP export includes the new session.
    r = client.get("/api/me/export", headers=h)
    assert r.status_code == 200 and r.json()["sessions"], r.text


def test_insufficient_balance_is_402_with_code(app_client):
    client, db = app_client
    r = client.post("/api/auth/firebase",
                    json={"id_token": "u2", "device_id": "dev-2", "lang": "hi"})
    h = {"Authorization": "Bearer " + r.json()["token"]}
    db.collection("users").document("u2").update({"balance_units": 0})
    r = client.post("/api/profiles", headers=h, json={
        "name": "Asha", "relation": "self",
        "birth": {"date": "1988-01-02", "time": "10:00", "place": "Delhi"}, "time_known": True})
    pid = r.json().get("id") or r.json().get("profile", {}).get("id") or r.json().get("profile_id")
    sid = client.post("/api/sessions", headers=h,
                      json={"profile_id": pid, "mode": "text"}).json()["session_id"]
    r = client.post("/api/sessions/%s/ask" % sid, headers=h, json={"text": "मेरी शादी कब होगी?"})
    assert r.status_code == 402, r.text
    assert r.json()["code"] == "insufficient_balance"
