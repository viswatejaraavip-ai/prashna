"""Flow: the operator dashboard — admin sign-in, the overview, the trace
explorer, user lookup, balance adjustment, refund decisions, runtime flags,
errors and the cost-watch cron.

CONTRACT.md -> "Operator — routes_admin.py".
"""

from conftest import ADMIN_EMAIL


def working_user(api, uid="u1", lang="te", asks=1):
    from ai_fakes import FakeClaude, FakeGemini
    _, h = api.signup(uid, device="dev-" + uid + "-ops1", lang=lang)
    api.topup(uid, 50000)
    p = api.profile(h)
    sid = api.session(h, p["id"])
    api.set_models(FakeGemini(), FakeClaude(lang=lang))
    traces = []
    for _ in range(asks):
        r = api.client.post("/api/sessions/%s/ask" % sid, headers=h, json={"text": "career?"})
        assert r.status_code == 200, r.text
        traces.append(r.json()["trace_id"])
    return h, p, sid, traces


# ------------------------------------------------------------------ auth ----

def test_every_admin_route_needs_an_admin_token(api):
    _, user_h = api.signup("u1")
    for path in ("/api/admin/overview", "/api/admin/traces", "/api/admin/users?q=u1",
                 "/api/admin/refunds", "/api/admin/support", "/api/admin/flags",
                 "/api/admin/errors", "/api/admin/audit", "/api/admin/costwatch"):
        assert api.client.get(path).status_code == 401, path
        r = api.client.get(path, headers=user_h)           # a plain user token
        assert r.status_code == 403, (path, r.status_code)
        assert r.json()["code"] == "forbidden"


def test_admin_login_and_me(api):
    ah = api.admin()
    assert api.client.get("/api/admin/me", headers=ah).json() == {"email": ADMIN_EMAIL}
    cfg = api.client.get("/api/admin/config", headers=ah).json()
    assert "firebase" in cfg


def test_dashboard_spa_is_served(api):
    r = api.client.get("/admin")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert api.client.get("/admin/assets/admin.js").status_code == 200
    assert api.client.get("/admin/assets/hack.js").status_code == 404


# -------------------------------------------------------------- overview ----

def test_overview_reports_todays_traffic(api):
    working_user(api, asks=2)
    ah = api.admin()
    r = api.client.get("/api/admin/overview?days=7", headers=ah)
    assert r.status_code == 200, r.text
    o = r.json()
    assert o["days"] == 7 and len(o["series"]) == 7
    assert o["price_units"] == 1000 and o["ceiling_units"] == 500
    assert o["totals"]["queries"] == 2
    assert o["totals"]["revenue_units"] == 2000
    assert o["today"]["rollup"]["queries"] == 2
    sample = o["sample"]
    assert sample["answered"] == 2
    assert sample["avg_cost_units"] > 0 and sample["p95_cost_units"] > 0
    assert "over_ceiling" in sample
    assert o["watch"]["level"] in ("ok", "warn", "over")
    assert o["refunds"]["count"] == 0

    assert api.client.get("/api/admin/overview?days=0", headers=ah).status_code == 422
    assert api.client.get("/api/admin/overview?days=91", headers=ah).status_code == 422


def test_costwatch(api):
    working_user(api, asks=2)
    ah = api.admin()
    r = api.client.get("/api/admin/costwatch?hours=24", headers=ah)
    assert r.status_code == 200, r.text
    c = r.json()
    assert c["answered"] == 2 and c["scanned"] >= 2
    assert c["ceiling_units"] == 500 and c["avg_cost_units"] > 0
    assert len(c["most_expensive"]) == 2
    assert c["over_ceiling"] == []


# ---------------------------------------------------------------- traces ----

def test_trace_explorer_filters_and_detail(api):
    h, p, sid, traces = working_user(api, asks=1)
    tid = traces[0]
    ah = api.admin()

    listing = api.client.get("/api/admin/traces?limit=10", headers=ah).json()
    assert [t["trace_id"] for t in listing["traces"]] == [tid]
    row = listing["traces"][0]
    assert row["uid"] == "u1" and row["status"] == "ok" and row["lang"] == "te"
    assert row["charged_units"] == 1000 and row["cost_units"] > 0
    assert any(m.startswith("claude") for m in row["models"])
    assert "stages" not in row                       # list rows stay compact
    assert "scanned" in listing and "next_before" in listing

    assert api.client.get("/api/admin/traces?uid=u1", headers=ah).json()["traces"]
    assert api.client.get("/api/admin/traces?status=error",
                          headers=ah).json()["traces"] == []
    assert api.client.get("/api/admin/traces?min_cost=999999",
                          headers=ah).json()["traces"] == []
    assert api.client.get("/api/admin/traces?date=notadate",
                          headers=ah).status_code == 400

    detail = api.client.get("/api/admin/traces/" + tid, headers=ah)
    assert detail.status_code == 200, detail.text
    d = detail.json()
    assert d["trace"]["trace_id"] == tid and d["trace"]["stages"]
    assert d["over_ceiling"] is False and d["ceiling_units"] == 500
    assert d["question"]["text"] == "career?" and d["answer"]["text"]
    assert d["user"]["uid"] == "u1" and d["user"]["balance_units"] == 50000

    missing = api.client.get("/api/admin/traces/nope", headers=ah)
    assert missing.status_code == 404 and missing.json()["code"] == "not_found"


def test_session_messages_for_an_operator(api):
    h, p, sid, _ = working_user(api)
    ah = api.admin()
    msgs = api.client.get("/api/admin/sessions/%s/messages" % sid, headers=ah).json()
    assert [m["role"] for m in msgs["messages"]] == ["user", "assistant"]


# ----------------------------------------------------------------- users ----

def test_user_lookup_by_uid_phone_and_email(api):
    h, p, sid, traces = working_user(api)
    api.client.post("/api/support", headers=h, json={"category": "other",
                                                     "message": "hello support"})
    ah = api.admin()
    phone = api.db.data("users/u1")["phone"]

    for q in ("u1", phone):
        found = api.client.get("/api/admin/users?q=" + q.replace("+", "%2B"),
                               headers=ah).json()["users"]
        assert [u["uid"] for u in found] == ["u1"], q

    assert api.client.get("/api/admin/users?q=z", headers=ah).status_code == 422

    d = api.client.get("/api/admin/users/u1", headers=ah)
    assert d.status_code == 200, d.text
    detail = d.json()
    assert detail["user"]["uid"] == "u1"
    assert [x["id"] for x in detail["profiles"]] == [p["id"]]
    assert [x["id"] for x in detail["sessions"]] == [sid]
    assert [t["trace_id"] for t in detail["traces"]] == traces
    assert {e["type"] for e in detail["ledger"]} == {"trial", "topup", "query"}
    assert detail["tickets"] and detail["devices"]["device_hashes"]

    gone = api.client.get("/api/admin/users/ghost", headers=ah)
    assert gone.status_code == 404 and gone.json()["code"] == "not_found"


def test_balance_adjust_is_audited(api):
    from app import routes_admin
    _, h = api.signup("u1")
    ah = api.admin()

    r = api.client.post("/api/admin/users/u1/adjust", headers=ah,
                        json={"delta_units": 2500, "reason": "goodwill after an outage"})
    assert r.status_code == 200, r.text
    assert r.json()["balance_units"] == 3500 and r.json()["audit_id"]
    assert api.client.get("/api/me", headers=h).json()["user"]["balance_units"] == 3500
    assert [e["type"] for e in api.db.children("users/u1/ledger")].count("adjust") == 1

    back = api.client.post("/api/admin/users/u1/adjust", headers=ah,
                           json={"delta_units": -500, "reason": "correction"})
    assert back.json()["balance_units"] == 3000

    audit = api.client.get("/api/admin/audit", headers=ah).json()["audit"]
    assert [a["action"] for a in audit].count("balance_adjust") == 2
    assert all(a["admin"] == ADMIN_EMAIL for a in audit)
    assert audit[0]["target"] == "users/u1" and audit[0]["reason"]

    for bad in ({"delta_units": 0, "reason": "nothing"},
                {"delta_units": -999999, "reason": "too much"},
                {"delta_units": routes_admin.ADJUST_MAX_UNITS + 1, "reason": "too much"}):
        r = api.client.post("/api/admin/users/u1/adjust", headers=ah, json=bad)
        assert r.status_code == 400 and r.json()["code"] == "invalid", bad
    assert api.client.post("/api/admin/users/u1/adjust", headers=ah,
                           json={"delta_units": 10, "reason": "x"}).status_code == 422
    assert api.client.post("/api/admin/users/ghost/adjust", headers=ah,
                           json={"delta_units": 10, "reason": "who"}).status_code == 404


# --------------------------------------------------------------- refunds ----

def test_refund_approval_credits_the_wallet_once(api):
    h, p, sid, traces = working_user(api)
    rid = api.client.post("/api/refunds", headers=h,
                          json={"ref": traces[0], "reason": "wrong answer"}).json()["id"]
    ah = api.admin()

    queue = api.client.get("/api/admin/refunds", headers=ah).json()["refunds"]
    assert [x["id"] for x in queue] == [rid]

    r = api.client.post("/api/admin/refunds/" + rid, headers=ah,
                        json={"decision": "approve", "note": "fair enough"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved" and r.json()["refunded_units"] == 1000
    # 1000 trial + 50000 topup - 1000 query + 1000 refund
    assert api.client.get("/api/me", headers=h).json()["user"]["balance_units"] == 51000
    assert [e["type"] for e in api.db.children("users/u1/ledger")].count("refund") == 1

    again = api.client.post("/api/admin/refunds/" + rid, headers=ah,
                            json={"decision": "approve"})
    assert again.status_code == 409 and again.json()["code"] == "invalid"
    assert api.client.get("/api/refunds", headers=h).json()["refunds"][0]["status"] \
        == "approved"


def test_refund_rejection_does_not_credit(api):
    h, p, sid, traces = working_user(api)
    before = api.client.get("/api/me", headers=h).json()["user"]["balance_units"]
    rid = api.client.post("/api/refunds", headers=h,
                          json={"ref": traces[0]}).json()["id"]
    ah = api.admin()
    r = api.client.post("/api/admin/refunds/" + rid, headers=ah,
                        json={"decision": "reject", "note": "answer was on topic"})
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    assert api.client.get("/api/me", headers=h).json()["user"]["balance_units"] == before

    bad = api.client.post("/api/admin/refunds/" + rid, headers=ah,
                          json={"decision": "maybe"})
    assert bad.status_code == 400 and bad.json()["code"] == "invalid"
    assert api.client.post("/api/admin/refunds/nope", headers=ah,
                           json={"decision": "approve"}).status_code == 404


def test_partial_refund_cannot_exceed_the_request(api):
    h, p, sid, traces = working_user(api)
    rid = api.client.post("/api/refunds", headers=h, json={"ref": traces[0]}).json()["id"]
    ah = api.admin()
    too_much = api.client.post("/api/admin/refunds/" + rid, headers=ah,
                               json={"decision": "approve", "amount_units": 5000})
    assert too_much.status_code == 400 and too_much.json()["code"] == "invalid"
    ok = api.client.post("/api/admin/refunds/" + rid, headers=ah,
                         json={"decision": "approve", "amount_units": 400})
    assert ok.status_code == 200 and ok.json()["refunded_units"] == 400


# ----------------------------------------------------------------- flags ----

def test_flags_read_write_and_validation(api):
    from app import store
    ah = api.admin()
    got = api.client.get("/api/admin/flags", headers=ah).json()
    assert got["flags"]["query_price_units"] == 1000
    assert got["flags"]["cost_ceiling_units"] == 500
    assert got["flags"]["opus_enabled"] is True

    r = api.client.put("/api/admin/flags", headers=ah,
                       json={"maintenance_message": "Back at 6pm", "opus_enabled": False})
    assert r.status_code == 200, r.text
    assert r.json()["changed"] == {"maintenance_message": "Back at 6pm",
                                   "opus_enabled": False}
    assert api.db.data("config_flags/global")["opus_enabled"] is False

    # no-op update
    assert api.client.put("/api/admin/flags", headers=ah,
                          json={"opus_enabled": False}).json()["changed"] == {}

    for bad in ({"unknown_flag": 1}, {"opus_enabled": "yes"},
                {"query_price_units": 10}, {"cost_ceiling_units": 5000}):
        r = api.client.put("/api/admin/flags", headers=ah, json=bad)
        assert r.status_code == 400 and r.json()["code"] == "invalid", bad
    store.clear_flags_cache()


def test_flag_changes_take_effect_for_users(api):
    from app import store
    h, p, sid, _ = working_user(api)
    ah = api.admin()
    api.client.put("/api/admin/flags", headers=ah,
                   json={"maintenance_message": "Upgrading, back soon"})
    store.clear_flags_cache()
    r = api.client.post("/api/sessions/%s/ask" % sid, headers=h, json={"text": "career?"})
    assert r.status_code == 503 and r.json()["code"] == "maintenance"

    api.client.put("/api/admin/flags", headers=ah, json={"maintenance_message": ""})
    store.clear_flags_cache()
    assert api.client.post("/api/sessions/%s/ask" % sid, headers=h,
                           json={"text": "career?"}).status_code == 200
    store.clear_flags_cache()


# ---------------------------------------------------------------- errors ----

def test_error_list_shows_traces_and_app_errors(api):
    from ai_fakes import FakeClaude, FakeGemini
    h, p, sid, _ = working_user(api)

    class Exploding(FakeClaude):
        def stream(self, **kw):
            raise RuntimeError("upstream 529 overloaded")

    api.set_models(FakeGemini(), Exploding(lang="te"))
    r = api.client.post("/api/sessions/%s/ask" % sid, headers=h, json={"text": "career?"})
    assert r.status_code == 200 and r.json()["status"] == "error"
    assert r.json()["charged_units"] == 0            # an error is never charged

    ah = api.admin()
    errs = api.client.get("/api/admin/errors", headers=ah).json()
    assert len(errs["traces"]) == 1
    assert errs["traces"][0]["status"] == "error"
    assert "app_errors" in errs
    assert api.rollup()["errors"] == 1


def test_cost_watch_cron(api, monkeypatch):
    monkeypatch.setenv("CRON_INSECURE_DEV", "1")
    working_user(api, asks=1)
    r = api.client.post("/internal/cron/cost-watch?hours=1")
    assert r.status_code == 200, r.text
    assert "level" in r.json() or "alerted" in r.json()
