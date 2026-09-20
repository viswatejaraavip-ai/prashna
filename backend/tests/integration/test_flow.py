"""The cross-module stories: one user journey, and one astrologer journey,
each followed all the way through every module it touches.

These are the tests that would catch a break *between* workstreams — a trace
that the dashboard cannot read, a rollup that is never incremented, a ledger
entry the export misses. Per-endpoint behaviour lives in the other files.
"""

from ai_fakes import FakeClaude, FakeGemini

from conftest import ADMIN_EMAIL, CLIENT, SITA


def test_personal_user_journey(api):
    """Sign up -> trial -> profile -> free snapshot -> top up -> ask ->
    trace + rollup + ledger -> refund request -> operator approves ->
    export -> delete."""
    from app.platform_legal import TERMS_VERSION

    # 1. first launch: phone OTP, Telugu, free trial
    body, h = api.signup("u-journey", device="pixel-journey-01", lang="te")
    assert body["created"] and body["trial_granted"]
    assert body["user"]["balance_units"] == 1000
    assert body["user"]["terms_accepted"] is False

    # 2. accept the current terms
    api.client.post("/api/me/disclaimer", headers=h, json={})
    assert api.client.get("/api/me", headers=h).json()["user"]["terms_accepted"] is True
    assert body["user"]["terms_version_required"] == TERMS_VERSION

    # 3. add the birth profile and read the free snapshot
    p = api.profile(h)
    snap = api.client.get("/api/profiles/%s/snapshot" % p["id"], headers=h)
    assert snap.status_code == 200 and snap.json()["lang"] == "te"
    assert api.client.get("/api/daily?profile_id=%s" % p["id"],
                          headers=h).status_code == 200

    # 4. top up through Google Play
    top = api.client.post("/api/wallet/play/verify", headers=h, json={
        "product_id": "wallet_100", "purchase_token": "play-journey-token-0001"})
    assert top.status_code == 200 and top.json()["balance_units"] == 11000

    # 5. ask a paid question
    sid = api.session(h, p["id"])
    api.set_models(FakeGemini(), FakeClaude(lang="te"))
    ask = api.client.post("/api/sessions/%s/ask" % sid, headers=h,
                          json={"text": "నా ఉద్యోగం ఎప్పుడు మారుతుంది?"})
    assert ask.status_code == 200, ask.text
    answer = ask.json()
    assert answer["status"] == "ok" and answer["charged_units"] == 1000
    assert answer["balance_units"] == 10000
    trace_id = answer["trace_id"]

    # 6. the trace, the rollup and the ledger all agree
    trace = api.db.data("traces/" + trace_id)
    assert trace["uid"] == "u-journey" and trace["charged_units"] == 1000
    assert trace["cost_units"] < 500
    roll = api.rollup()
    assert roll["queries"] == 1 and roll["revenue_units"] == 1000
    assert roll["by_lang"]["te"] == 1 and roll["signups"] == 1
    assert abs(roll["cost_units"] - trace["cost_units"]) < 1e-6
    query_entry = [e for e in api.db.children("users/u-journey/ledger")
                   if e["type"] == "query"][0]
    assert query_entry["ref"] == trace_id and query_entry["delta_units"] == -1000

    # 7. the operator sees exactly that query
    ah = api.admin()
    overview = api.client.get("/api/admin/overview?days=7", headers=ah).json()
    assert overview["totals"]["queries"] == 1
    assert overview["totals"]["revenue_units"] == 1000
    detail = api.client.get("/api/admin/traces/" + trace_id, headers=ah).json()
    assert detail["trace"]["trace_id"] == trace_id
    assert detail["user"]["uid"] == "u-journey"
    found = api.client.get("/api/admin/users?q=u-journey", headers=ah).json()["users"]
    assert [u["uid"] for u in found] == ["u-journey"]

    # 8. the user is unhappy and asks for a refund; the operator approves it
    rid = api.client.post("/api/refunds", headers=h,
                          json={"ref": trace_id, "reason": "not what I asked"}
                          ).json()["id"]
    queue = api.client.get("/api/admin/refunds", headers=ah).json()["refunds"]
    assert [x["id"] for x in queue] == [rid]
    decided = api.client.post("/api/admin/refunds/" + rid, headers=ah,
                              json={"decision": "approve", "note": "goodwill"})
    assert decided.status_code == 200 and decided.json()["status"] == "approved"
    assert api.client.get("/api/me", headers=h).json()["user"]["balance_units"] == 11000
    audit = api.client.get("/api/admin/audit", headers=ah).json()["audit"]
    assert audit[0]["admin"] == ADMIN_EMAIL

    # 9. DPDP: export, then delete
    export = api.client.get("/api/me/export", headers=h).json()
    assert export["sessions"][0]["id"] == sid
    assert len(export["sessions"][0]["messages"]) == 2
    assert {"trial", "topup", "query", "refund"} <= {e["type"] for e in export["ledger"]}
    assert export["refunds"][0]["id"] == rid
    assert api.client.delete("/api/me", headers=h).json()["deleted"] is True
    assert api.client.get("/api/me", headers=h).status_code == 404


def test_astrologer_journey(api):
    """Sign up -> "I am an astrologer" -> top up -> Pro -> client -> Pro
    bundle -> brand -> branded matching PDF -> paid consultation -> the
    operator sees a Pro purchase and a query for the same account."""
    _, h = api.signup("u-astro", device="oneplus-astro-01", lang="ta",
                      email="jyotish@example.com")
    assert api.client.patch("/api/me", headers=h,
                            json={"role": "astrologer"}).json()["user"]["role"] \
        == "astrologer"
    api.topup("u-astro", 200000)

    # Pro from the wallet
    pro = api.client.post("/api/plan/pro/purchase", headers=h)
    assert pro.status_code == 200 and pro.json()["plan"] == "pro"
    assert api.client.get("/api/me", headers=h).json()["user"]["plan"] == "pro"

    # clients + the Pro-only bundle
    a = api.client.post("/api/astro/clients", headers=h, json=CLIENT).json()
    b = api.client.post("/api/astro/clients", headers=h,
                        json={"name": "Bride", "gender": "female",
                              "birth": SITA["birth"], "notes": "matching"}).json()
    bundle = api.client.get("/api/astro/clients/%s/pro-bundle?lang=ta" % a["id"], headers=h)
    assert bundle.status_code == 200 and len(bundle.json()["vargas"]) == 16
    assert api.client.get("/api/profiles/%s/chart?kind=shadbala" % a["id"],
                          headers=h).status_code == 200

    # white-label brand -> branded matching PDF
    api.client.put("/api/astro/brand", headers=h,
                   json={"display_name": "Sri Sai Jyotisham", "phone": "+91 90000 00000",
                         "footer": "Hyderabad"})
    pdf = api.client.post("/api/matching/pdf?lang=ta", headers=h,
                          json={"profile_a": a["id"], "profile_b": b["id"],
                                "brand": True})
    assert pdf.status_code == 200, pdf.text
    data, ctype = api.storage.objects[pdf.json()["path"]]
    assert ctype == "application/pdf" and data[:4] == b"%PDF"

    # a paid consultation about a client
    sid = api.session(h, a["id"])
    api.set_models(FakeGemini(), FakeClaude(lang="ta"))
    ask = api.client.post("/api/sessions/%s/ask" % sid, headers=h,
                          json={"text": "இந்த வாடிக்கையாளரின் திருமணம் எப்போது?"})
    assert ask.status_code == 200 and ask.json()["status"] == "ok"
    assert api.db.data("traces/" + ask.json()["trace_id"])["lang"] == "ta"

    # the money trail the operator sees
    types = api.ledger_types("u-astro")
    assert types.count("subscription") == 1 and types.count("query") == 1
    roll = api.rollup()
    assert roll["by_lang"]["ta"] == 1
    assert roll["revenue_units"] == 49900 + 1000

    ah = api.admin()
    detail = api.client.get("/api/admin/users/u-astro", headers=ah).json()
    assert detail["user"]["role"] == "astrologer" and detail["user"]["plan"] == "pro"
    assert len(detail["profiles"]) == 2 and len(detail["traces"]) == 1
    assert {e["type"] for e in detail["ledger"]} >= {"topup", "subscription", "query"}
