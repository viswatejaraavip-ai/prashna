import sys
import types
from datetime import datetime, timedelta, timezone

import pytest

from app import store
from app.admin import alerts, metrics
from app.admin.errors import build_error_doc

from conftest import ADMIN


def _trace(cost, status="ok", lang="te", mode="text", kind="query", mins_ago=5,
           charged=None, stages=None, uid="u1", latency=4000):
    at = datetime.now(timezone.utc) - timedelta(minutes=mins_ago)
    if charged is None:
        charged = 1000 if status in ("ok", "over_ceiling") and kind == "query" else 0
    return {"uid": uid, "session_id": "", "lang": lang, "mode": mode, "kind": kind,
            "status": status, "created_at": at.isoformat(), "latency_ms": latency,
            "stages": stages if stages is not None else [
                {"name": "plan", "model": "gemini-2.5-flash", "cost_units": 10},
                {"name": "brief", "model": "gemini-2.5-flash", "cost_units": 40},
                {"name": "reason", "model": "claude-opus-4-5",
                 "cost_units": cost - 50}],
            "cost_units": cost, "charged_units": charged, "error": None}


# ---------- pure math ----------

def test_percentile_matches_linear_interpolation():
    xs = [100, 200, 300, 400, 500]
    assert metrics.percentile(xs, 50) == 300
    assert metrics.percentile(xs, 95) == pytest.approx(480)
    assert metrics.percentile(xs, 0) == 100
    assert metrics.percentile([], 50) is None
    assert metrics.percentile([7], 95) == 7
    assert metrics.percentile(range(1, 101), 95) == pytest.approx(95.05)


def test_margin():
    assert metrics.margin_pct(1000, 375) == 62.5
    assert metrics.margin_pct(0, 10) is None
    assert metrics.margin_pct(2000, 2500) == -25.0


def test_summarize_traces_math():
    # 10 answered queries: costs 300..570 step 30, one of them status over_ceiling.
    traces = [_trace(300 + 30 * i) for i in range(10)]
    traces[9]["status"] = "over_ceiling"
    traces[0]["mode"] = "voice"
    traces[0]["stages"].append({"name": "tts", "model": "google-tts", "cost_units": 0})
    # Free/error turns: excluded from per-query stats but reported.
    traces.append(_trace(60, status="refused",
                         stages=[{"name": "plan", "model": "gemini-2.5-flash", "cost_units": 60}]))
    traces.append(_trace(100, status="error"))
    traces.append(_trace(2000, kind="report_chapter"))

    s = metrics.summarize_traces(traces, ceiling_units=500)
    costs = [300 + 30 * i for i in range(10)]
    assert s["answered"] == 10
    assert s["cost_units"] == sum(costs) == 4350
    assert s["revenue_units"] == 10000
    assert s["margin_pct"] == 56.5
    assert s["avg_cost_units"] == 435.0
    assert s["p50_cost_units"] == 435.0
    assert s["p95_cost_units"] == pytest.approx(556.5)
    # Over ceiling (> 500): 510, 540, 570 -> 3 of 10.
    assert s["over_ceiling"] == 3
    assert s["over_ceiling_pct"] == 30.0
    assert s["free_turns"] == 1 and s["free_turn_cost_units"] == 60
    assert s["errors"] == 1
    assert s["error_rate_pct"] == pytest.approx(100 / 12, rel=1e-3)
    assert s["by_stage"]["plan"] == 100 and s["by_stage"]["brief"] == 400
    assert s["by_stage"]["reason"] == 4350 - 500
    assert s["by_model"]["claude-opus-4-5"]["calls"] == 10
    assert s["by_mode"]["voice"]["queries"] == 1
    assert s["by_mode"]["text"]["queries"] == 9
    assert s["by_lang"]["te"]["queries"] == 10 and s["by_lang"]["hi"]["queries"] == 0
    assert s["reports"] == {"chapters": 1, "cost_units": 2000}
    assert sum(b["count"] for b in s["cost_histogram"]) == 10


def test_rollup_totals_and_watch_level():
    series = metrics.rollup_series(["d1", "d2"], {
        "d1": {"queries": 10, "revenue_units": 10000, "cost_units": 4000, "over_ceiling": 1,
               "by_lang": {"te": 10}},
        "d2": {"queries": 30, "revenue_units": 30000, "cost_units": 15000, "over_ceiling": 3,
               "by_lang": {"te": 20, "hi": 10}},
    })
    assert series[0]["margin_pct"] == 60.0 and series[0]["avg_cost_units"] == 400.0
    tot = metrics.rollup_totals(series)
    assert tot["queries"] == 40 and tot["cost_units"] == 19000
    assert tot["margin_pct"] == 52.5
    assert tot["avg_cost_units"] == 475.0
    assert tot["over_ceiling_pct"] == 10.0
    assert tot["by_lang"] == {"te": 30, "hi": 10}
    assert metrics.watch_level(440) == "ok"
    assert metrics.watch_level(460) == "warning"
    assert metrics.watch_level(520) == "breach"
    assert metrics.watch_level(None) == "ok"


# ---------- API ----------

def test_admin_guard_rejects_non_admins(client, db):
    assert client.get("/api/admin/overview").status_code == 401
    user_tok = store.issue_token("some-user")
    r = client.get("/api/admin/overview", headers={"Authorization": "Bearer " + user_tok})
    assert r.status_code == 403
    stranger = store.issue_token("x", admin_email="stranger@example.com")
    r = client.get("/api/admin/flags", headers={"Authorization": "Bearer " + stranger})
    assert r.status_code == 403
    r = client.post("/api/admin/users/u1/adjust", json={"delta_units": 100, "reason": "x" * 5},
                    headers={"Authorization": "Bearer " + user_tok})
    assert r.status_code == 403
    assert db.dump("admin_audit") == {}
    # Config endpoint is public (needed before sign-in).
    assert client.get("/api/admin/config").status_code == 200


def test_overview_endpoint(client, db, admin_headers):
    for i, t in enumerate([_trace(300), _trace(400), _trace(600, status="over_ceiling")]):
        db.collection("traces").document("t%d" % i).set(t)
    today = store.today_key()
    db.collection("rollups_daily").document(today).set(
        {"queries": 3, "revenue_units": 3000, "cost_units": 1300, "over_ceiling": 1})
    r = client.get("/api/admin/overview?days=7", headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["series"]) == 7 and body["series"][-1]["day"] == today
    assert body["totals"]["margin_pct"] == pytest.approx(56.7)
    assert body["sample"]["p50_cost_units"] == 400
    assert body["sample"]["over_ceiling"] == 1
    assert body["watch"]["avg_cost_units"] == pytest.approx(433.3)
    assert body["watch"]["level"] == "ok"
    # Every trace query was bounded.
    assert all(q[3] is not None for q in db.queries if q[0] == "traces")


def test_adjust_goes_through_billing_and_is_audited(client, db, admin_headers, monkeypatch):
    db.collection("users").document("u1").set({"uid": "u1", "balance_units": 500})
    calls = []
    fake_billing = types.ModuleType("app.billing")

    def credit(uid, units, type, ref):
        calls.append((uid, units, type, ref))
        return 500 + units
    fake_billing.credit = credit
    monkeypatch.setitem(sys.modules, "app.billing", fake_billing)
    import app
    monkeypatch.setattr(app, "billing", fake_billing, raising=False)

    r = client.post("/api/admin/users/u1/adjust",
                    json={"delta_units": 1000, "reason": "Goodwill for outage"},
                    headers=admin_headers)
    assert r.status_code == 200, r.text
    assert r.json()["balance_units"] == 1500
    assert calls == [("u1", 1000, "adjust", "admin:" + r.json()["audit_id"])]
    # Balance was not written by the admin module.
    assert db.dump("users")["u1"]["balance_units"] == 500
    audits = db.dump("admin_audit")
    assert len(audits) == 1
    a = audits[r.json()["audit_id"]]
    assert a["admin"] == ADMIN and a["action"] == "balance_adjust"
    assert a["target"] == "users/u1"
    assert a["before"] == {"balance_units": 500}
    assert a["after"]["balance_units"] == 1500
    assert a["reason"] == "Goodwill for outage" and a["created_at"]

    # Negative result is refused, nothing audited.
    r = client.post("/api/admin/users/u1/adjust",
                    json={"delta_units": -600, "reason": "oops"}, headers=admin_headers)
    assert r.status_code == 400
    assert len(db.dump("admin_audit")) == 1


def test_refund_approve_and_reject(client, db, admin_headers, monkeypatch):
    db.collection("refunds").document("r1").set(
        {"uid": "u1", "ref": "t1", "amount_units": 1000, "status": "requested",
         "created_at": store.now_iso()})
    db.collection("refunds").document("r2").set(
        {"uid": "u2", "ref": "t2", "amount_units": 1000, "status": "requested",
         "created_at": store.now_iso()})
    calls = []
    fake_billing = types.ModuleType("app.billing")
    fake_billing.refund = lambda uid, units, ref, idem_key=None: calls.append((uid, units, ref)) or 2000
    monkeypatch.setitem(sys.modules, "app.billing", fake_billing)
    import app
    monkeypatch.setattr(app, "billing", fake_billing, raising=False)

    r = client.post("/api/admin/refunds/r1", json={"decision": "approve"}, headers=admin_headers)
    assert r.status_code == 200, r.text
    assert calls == [("u1", 1000, "refund:r1")]
    assert db.dump("refunds")["r1"]["status"] == "approved"
    # Second decision is refused (no double refund).
    r = client.post("/api/admin/refunds/r1", json={"decision": "approve"}, headers=admin_headers)
    assert r.status_code == 409 and len(calls) == 1
    r = client.post("/api/admin/refunds/r2", json={"decision": "reject", "note": "used"},
                    headers=admin_headers)
    assert r.status_code == 200 and len(calls) == 1
    assert db.dump("refunds")["r2"]["status"] == "rejected"
    actions = sorted(a["action"] for a in db.dump("admin_audit").values())
    assert actions == ["refund_approved", "refund_rejected"]


def test_flags_update_validates_audits_and_clears_cache(client, db, admin_headers):
    store.get_flags()  # warm cache
    r = client.put("/api/admin/flags", json={"opus_enabled": "no"}, headers=admin_headers)
    assert r.status_code == 400
    r = client.put("/api/admin/flags", json={"cost_ceiling_units": 1200}, headers=admin_headers)
    assert r.status_code == 400  # ceiling must stay below price
    r = client.put("/api/admin/flags", json={"opus_enabled": False,
                                             "maintenance_message": " Back soon "},
                   headers=admin_headers)
    assert r.status_code == 200, r.text
    assert db.dump("config_flags")["global"]["opus_enabled"] is False
    assert store.get_flags()["opus_enabled"] is False  # cache was cleared
    (a,) = db.dump("admin_audit").values()
    assert a["before"] == {"opus_enabled": True, "maintenance_message": ""}
    assert a["after"] == {"opus_enabled": False, "maintenance_message": "Back soon"}


def test_support_reply_audited(client, db, admin_headers):
    db.collection("support_tickets").document("s1").set(
        {"uid": "u1", "message": "help", "status": "open", "replies": [],
         "created_at": store.now_iso()})
    r = client.post("/api/admin/support/s1/reply", json={"message": "Done", "resolve": True},
                    headers=admin_headers)
    assert r.status_code == 200
    t = db.dump("support_tickets")["s1"]
    assert t["status"] == "resolved" and t["replies"][0]["admin"] == ADMIN
    assert list(db.dump("admin_audit").values())[0]["action"] == "support_reply"


def test_trace_detail_joins_messages(client, db, admin_headers):
    t = _trace(350)
    t.update(trace_id="tx", session_id="s1")
    db.collection("traces").document("tx").set(t)
    msgs = db.collection("sessions").document("s1").collection("messages")
    msgs.document("m1").set({"role": "user", "text": "When will I marry?", "trace_id": "tx",
                             "created_at": "2026-01-01T00:00:00+00:00"})
    msgs.document("m2").set({"role": "assistant", "text": "Answer", "trace_id": "tx",
                             "created_at": "2026-01-01T00:00:05+00:00"})
    r = client.get("/api/admin/traces/tx", headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["question"]["text"] == "When will I marry?"
    assert r.json()["answer"]["text"] == "Answer"
    assert client.get("/api/admin/traces/nope", headers=admin_headers).status_code == 404


def test_trace_filters(client, db, admin_headers):
    db.collection("traces").document("a").set(_trace(300, lang="te"))
    db.collection("traces").document("b").set(_trace(700, lang="hi", mode="voice"))
    db.collection("traces").document("c").set(_trace(100, status="error", uid="u2"))
    r = client.get("/api/admin/traces?min_cost=500", headers=admin_headers).json()
    assert [t["id"] for t in r["traces"]] == ["b"]
    r = client.get("/api/admin/traces?lang=hi&mode=voice", headers=admin_headers).json()
    assert [t["id"] for t in r["traces"]] == ["b"]
    r = client.get("/api/admin/traces?uid=u2&status=error", headers=admin_headers).json()
    assert [t["id"] for t in r["traces"]] == ["c"]
    r = client.get("/api/admin/errors", headers=admin_headers).json()
    assert [t["id"] for t in r["traces"]] == ["c"]


def test_user_lookup(client, db, admin_headers):
    db.collection("users").document("u9").set({"uid": "u9", "phone": "+919876543210",
                                              "email": "a@b.com", "balance_units": 0})
    for q in ("9876543210", "+919876543210", "a@b.com", "u9"):
        r = client.get("/api/admin/users", params={"q": q}, headers=admin_headers).json()
        assert [u["id"] for u in r["users"]] == ["u9"], q
    d = client.get("/api/admin/users/u9", headers=admin_headers).json()
    assert d["user"]["uid"] == "u9" and d["ledger"] == []


def test_seeded_demo_overview(client, db, admin_headers):
    from seed_admin_demo import seed
    counts = seed(db, days=10, users=25)
    assert counts["traces"] > 20
    body = client.get("/api/admin/overview?days=10", headers=admin_headers).json()
    assert body["totals"]["queries"] > 0
    assert 0 < body["sample"]["avg_cost_units"] < 1000
    assert client.get("/api/admin/costwatch", headers=admin_headers).status_code == 200


# ---------- errors + alerts ----------

def test_record_app_error_doc():
    from starlette.requests import Request
    tok = store.issue_token("u42")
    req = Request({"type": "http", "method": "POST", "path": "/api/x", "query_string": b"",
                   "headers": [(b"authorization", ("Bearer " + tok).encode())]})
    try:
        raise KeyError("lat")
    except KeyError as e:
        doc = build_error_doc(req, e)
    assert doc["uid"] == "u42" and doc["path"] == "/api/x"
    assert doc["error_type"] == "KeyError" and "KeyError" in doc["traceback"]


def test_cost_watch_cron(client, db, monkeypatch):
    for i in range(6):
        db.collection("traces").document("t%d" % i).set(_trace(560, status="over_ceiling"))
    sent = []
    monkeypatch.setattr(alerts, "post_webhook", lambda text: sent.append(text) or True)
    platform_cron = types.ModuleType("app.platform_cron")

    def verify_cron(request):
        if request.headers.get("authorization") != "Bearer cron":
            from fastapi import HTTPException
            raise HTTPException(403, "no")
    platform_cron.verify_cron = verify_cron
    monkeypatch.setitem(sys.modules, "app.platform_cron", platform_cron)

    assert client.post("/internal/cron/cost-watch").status_code == 403
    r = client.post("/internal/cron/cost-watch", headers={"Authorization": "Bearer cron"})
    assert r.status_code == 200, r.text
    assert r.json()["level"] == "breach" and r.json()["sent"] is True
    assert len(sent) == 1 and "breach" in sent[0]
    # Same alert again within the repeat window is suppressed.
    r = client.post("/internal/cron/cost-watch", headers={"Authorization": "Bearer cron"})
    assert r.json().get("suppressed") is True and len(sent) == 1


def test_negative_adjust_uses_wallet_adjust(client, db, admin_headers, monkeypatch):
    db.collection("users").document("u1").set({"uid": "u1", "balance_units": 5000})
    calls = []
    fake_billing = types.ModuleType("app.billing")
    fake_billing.adjust = lambda uid, delta, reason, admin: calls.append(
        (uid, delta, reason, admin)) or 5000 + delta
    monkeypatch.setitem(sys.modules, "app.billing", fake_billing)
    import app
    monkeypatch.setattr(app, "billing", fake_billing, raising=False)
    r = client.post("/api/admin/users/u1/adjust",
                    json={"delta_units": -2000, "reason": "Duplicate top-up"},
                    headers=admin_headers)
    assert r.status_code == 200, r.text
    assert calls == [("u1", -2000, "Duplicate top-up", ADMIN)]
    (a,) = db.dump("admin_audit").values()
    assert a["before"] == {"balance_units": 5000} and a["after"]["balance_units"] == 3000
