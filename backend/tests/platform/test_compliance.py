from datetime import datetime, timedelta, timezone

import pytest

from conftest import login


def _spend(fake, uid="u1"):
    from app import billing
    return billing.charge(uid, 1000, "query", "trace-1")


def test_refund_request_and_admin_decision(client, fake):
    from app import platform_compliance as pc
    _, h = login(client)
    _spend(fake)
    assert client.post("/api/refunds", headers=h, json={"ref": "nope"}).status_code == 404
    r = client.post("/api/refunds", headers=h, json={"ref": "trace-1", "reason": "bad answer"})
    assert r.status_code == 200 and r.json()["amount_units"] == 1000
    rid = r.json()["id"]
    dup = client.post("/api/refunds", headers=h, json={"ref": "trace-1"})
    assert dup.status_code == 409
    assert client.get("/api/refunds", headers=h).json()["refunds"][0]["status"] == "requested"
    out = pc.decide_refund(rid, "approved", "boss@example.com")
    assert out["balance_units"] == 1000
    with pytest.raises(Exception):
        pc.decide_refund(rid, "approved", "boss@example.com")  # credited already
    assert fake.data("users/u1")["balance_units"] == 1000
    assert fake.data("refunds/" + rid)["decided_by"] == "boss@example.com"


def test_refund_rejected(client, fake):
    from app import platform_compliance as pc
    _, h = login(client)
    _spend(fake)
    rid = client.post("/api/refunds", headers=h, json={"ref": "trace-1"}).json()["id"]
    pc.decide_refund(rid, "rejected", "boss@example.com")
    assert fake.data("users/u1")["balance_units"] == 0


def test_support_tickets(client, monkeypatch):
    from app import platform_compliance as pc
    import app.platform_push as push
    monkeypatch.setattr(push, "send_push", lambda *a, **k: 0)
    _, h = login(client)
    t = client.post("/api/support", headers=h, json={"category": "weird", "message": "help me"}).json()
    assert t["category"] == "other" and t["status"] == "open"
    pc.reply_ticket(t["id"], "Fixed", "boss@example.com")
    got = client.get("/api/support", headers=h).json()["tickets"][0]
    assert got["status"] == "resolved" and got["replies"][0]["text"] == "Fixed"


def test_disclaimer_and_export(client, fake):
    _, h = login(client)
    assert client.post("/api/me/disclaimer", headers=h, json={"version": "2"}).status_code == 200
    fake.collection("users").document("u1").collection("profiles").document("p1").set(
        {"name": "Me", "created_at": "2026-01-01"})
    fake.collection("sessions").document("s1").set({"uid": "u1", "created_at": "2026-01-01"})
    fake.collection("sessions").document("s1").collection("messages").document("m1").set(
        {"role": "user", "text": "hi", "created_at": "2026-01-01"})
    fake.collection("sessions").document("s2").set({"uid": "other", "created_at": "2026-01-01"})
    fake.collection("reports").document("r1").set({"uid": "u1", "created_at": "2026-01-01"})
    ex = client.get("/api/me/export", headers=h).json()
    assert ex["user"]["disclaimer_version"] == "2"
    assert "device_hashes" not in ex["user"]
    assert [p["name"] for p in ex["profiles"]] == ["Me"]
    assert len(ex["sessions"]) == 1 and ex["sessions"][0]["messages"][0]["text"] == "hi"
    assert [r["id"] for r in ex["reports"]] == ["r1"]
    assert ex["ledger"][0]["type"] == "trial"


def test_delete_then_purge_after_30_days(client, fake):
    from app import platform_compliance as pc
    _, h = login(client)
    login(client, "keep", "device-keep")
    fake.collection("sessions").document("s1").set({"uid": "u1", "created_at": "x"})
    fake.collection("sessions").document("s1").collection("messages").document("m").set({"t": 1})
    fake.collection("payments").document("p1").set({"uid": "u1", "raw": {"x": 1}, "created_at": "x"})
    assert client.delete("/api/me", headers=h).json()["deleted"]
    assert pc.purge_deleted()["purged"] == 0  # still in grace period
    old = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
    fake.document("users/u1").update({"deleted_at": old})
    assert pc.purge_deleted()["purged"] == 1
    assert fake.data("users/u1") is None
    assert fake.children("users/u1/ledger") == []
    assert fake.data("sessions/s1") is None and fake.data("sessions/s1/messages/m") is None
    pay = fake.data("payments/p1")
    assert pay["uid"].startswith("erased:") and pay["raw"] is None
    assert fake.data("users/keep") is not None


def test_purge_expires_pro_plans(fake):
    from app import platform_compliance as pc
    fake.collection("users").document("p").set({"plan": "pro", "plan_expires_at": "2000-01-01",
                                                "deleted_at": None})
    assert pc.purge_deleted()["plans_expired"] == 1
    assert fake.data("users/p")["plan"] == "free"


def test_cron_route_requires_auth(client, monkeypatch):
    monkeypatch.delenv("CRON_INSECURE_DEV", raising=False)
    assert client.post("/internal/cron/purge-deleted").status_code == 401


@pytest.mark.parametrize("doc", ["terms", "privacy", "refund", "disclaimer"])
@pytest.mark.parametrize("lang", ["hi", "te", "ta", "kn", "ml", "en"])
def test_legal_docs(client, doc, lang):
    r = client.get("/api/legal/%s?lang=%s" % (doc, lang))
    assert r.status_code == 200
    body = r.json()
    assert body["lang"] == lang and body["title"] and len(body["body_markdown"]) > 400
    assert "{{" not in body["body_markdown"]
    assert "DRAFT" not in body["body_markdown"]
    assert "14416" in body["body_markdown"] or doc != "disclaimer"


def test_legal_uses_saved_or_header_lang(client):
    r = client.get("/api/legal/terms", headers={"Accept-Language": "ml-IN"})
    assert r.json()["lang"] == "ml"
    assert client.get("/api/legal/nope").status_code == 404
    page = client.get("/legal/privacy")
    assert page.status_code == 200 and "Privacy Policy" in page.text
