"""Flow: the Mega life report — free teaser, purchase, generation, progress,
PDF, failure + refund + resume, and the astrologer's branded edition.

CONTRACT.md -> "AI": POST /api/reports, GET /api/reports[/{id}],
POST /api/reports/{id}/resume, GET /api/reports/{id}/pdf, POST /api/reports/teaser.
"""

import pytest

BRAND = {"display_name": "Sri Sai Jyotisham", "phone": "+91 90000 00000",
         "footer": "Consultations by appointment"}


def buyer(api, uid="u1", lang="te", units=200000):
    _, h = api.signup(uid, device="dev-" + uid + "-rep01", lang=lang)
    p = api.profile(h)
    api.topup(uid, units)
    return h, p


def fee_for(lang):
    from app import reports
    return reports.report_fee_units(lang)


# ----------------------------------------------------------------- teaser ----

def test_free_teaser_then_daily_limit(api):
    from app import reports
    h, p = buyer(api)
    before = api.db.data("users/u1")["balance_units"]
    r = api.client.post("/api/reports/teaser", headers=h, json={"profile_id": p["id"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["teaser"]
    full = body["full_report"]
    assert full["price_units"] > 0
    assert len(full["chapters"]) == len(reports.SECTIONS)
    assert api.db.data("users/u1")["balance_units"] == before      # free

    traces = [d.to_dict() for d in api.db.collection("traces").stream()]
    assert [t["kind"] for t in traces] == ["teaser"]

    for _ in range(reports.REPORT_TEASERS_PER_DAY - 1):
        assert api.client.post("/api/reports/teaser", headers=h,
                               json={"profile_id": p["id"]}).status_code == 200
    r = api.client.post("/api/reports/teaser", headers=h, json={"profile_id": p["id"]})
    assert r.status_code == 429 and r.json()["code"] == "rate_limited"


def test_teaser_for_an_unknown_profile(api):
    h, _ = buyer(api)
    r = api.client.post("/api/reports/teaser", headers=h, json={"profile_id": "nope"})
    assert r.status_code == 404 and r.json()["code"] == "not_found"


# -------------------------------------------------- purchase -> PDF story ----

def test_report_purchase_generation_and_pdf(api):
    from app import reports
    h, p = buyer(api, lang="te")
    start_balance = api.db.data("users/u1")["balance_units"]

    r = api.client.post("/api/reports", headers=h, json={"profile_id": p["id"]})
    assert r.status_code == 200, r.text
    started = r.json()
    rid = started["report_id"]
    assert started["sections_total"] == len(reports.SECTIONS)

    fee = fee_for("te")
    assert api.db.data("users/u1")["balance_units"] == start_balance - fee
    ledger = [e for e in api.db.children("users/u1/ledger") if e["type"] == "report"]
    assert len(ledger) == 1 and ledger[0]["delta_units"] == -fee
    assert ledger[0]["ref"] == rid
    roll = api.rollup()
    assert roll["reports"] == 1 and roll["revenue_units"] == fee

    # generation ran inline (see conftest: reports._launch)
    got = api.client.get("/api/reports/%s" % rid, headers=h)
    assert got.status_code == 200, got.text
    rep = got.json()
    assert rep["status"] == "ready"
    assert rep["sections_done"] == rep["sections_total"] == len(reports.SECTIONS)
    assert rep["lang"] == "te" and rep["profile_name"] == "Ravi"
    assert rep["completed_at"] and rep["error"] is None
    assert rep["branded"] is False
    assert len(rep["sections"]) == len(reports.SECTIONS)
    assert [s["idx"] for s in rep["sections"]] == list(range(1, len(reports.SECTIONS) + 1))
    assert all(s["title"] and s["content"] for s in rep["sections"])

    lst = api.client.get("/api/reports", headers=h).json()
    assert [x["report_id"] for x in lst] == [rid]
    assert set(lst[0]) >= set(reports._PUBLIC)

    # one trace per chapter, all inside the cost ceiling
    chapter_traces = [d.to_dict() for d in api.db.collection("traces").stream()
                      if (d.to_dict() or {}).get("kind") == "report_chapter"]
    assert len(chapter_traces) == len(reports.SECTIONS)
    assert all(t["report_id"] == rid for t in chapter_traces)
    assert all(s["name"] in ("outline", "reason") for t in chapter_traces
               for s in t["stages"])
    total_cost = sum(t["cost_units"] for t in chapter_traces)
    assert total_cost > 0
    assert api.db.data("reports/" + rid)["cost_units"] > 0

    # PDF is rendered once, stored and handed out as a signed URL
    r = api.client.get("/api/reports/%s/pdf" % rid, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["url"].startswith("https://signed.example/reports/u1/")
    path = "reports/u1/%s.pdf" % rid
    data, ctype = api.storage.objects[path]
    assert ctype == "application/pdf" and data[:4] == b"%PDF"
    assert api.db.data("reports/" + rid)["pdf_path"] == path
    # second call reuses the stored object
    n = len(api.storage.objects)
    assert api.client.get("/api/reports/%s/pdf" % rid, headers=h).status_code == 200
    assert len(api.storage.objects) == n


def test_progress_is_visible_while_generating(api):
    from app import reports
    h, p = buyer(api)
    api.launch.paused = True
    rid = api.client.post("/api/reports", headers=h,
                          json={"profile_id": p["id"]}).json()["report_id"]
    assert api.launched == [rid]

    rep = api.client.get("/api/reports/%s" % rid, headers=h).json()
    assert rep["status"] == "generating"
    assert rep["sections_done"] == 0
    assert rep["sections_total"] == len(reports.SECTIONS)
    assert rep["sections"] == [] and rep["completed_at"] is None

    # the PDF is refused until it is ready
    r = api.client.get("/api/reports/%s/pdf" % rid, headers=h)
    assert r.status_code == 400 and r.json()["code"] == "invalid"

    reports._generate(rid)
    rep = api.client.get("/api/reports/%s" % rid, headers=h).json()
    assert rep["status"] == "ready" and rep["sections_done"] == len(reports.SECTIONS)


def test_failed_report_is_refunded_and_can_be_resumed(api):
    from ai_fakes import FakeClaude
    from app import reports
    h, p = buyer(api)
    start_balance = api.db.data("users/u1")["balance_units"]

    # Opus blows up from chapter 4 on.
    failing = range(4, len(reports.SECTIONS) + 1)
    api.set_models(c=FakeClaude(lang="te", fail_chapters=failing))
    rid = api.client.post("/api/reports", headers=h,
                          json={"profile_id": p["id"]}).json()["report_id"]

    rep = api.client.get("/api/reports/%s" % rid, headers=h).json()
    assert rep["status"] == "failed" and rep["error"]
    assert 0 < rep["sections_done"] < rep["sections_total"]
    kept = rep["sections_done"]
    kept_text = {s["idx"]: s["content"] for s in rep["sections"]}
    # the fee came back
    assert api.db.data("users/u1")["balance_units"] == start_balance
    assert [e["type"] for e in api.db.children("users/u1/ledger")
            if e["ref"] in (rid, "report:" + rid)].count("refund") == 1

    # resume re-charges and keeps the finished chapters
    api.set_models(c=FakeClaude(lang="te"))
    r = api.client.post("/api/reports/%s/resume" % rid, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["sections_done"] >= kept
    rep = api.client.get("/api/reports/%s" % rid, headers=h).json()
    assert rep["status"] == "ready" and rep["sections_done"] == rep["sections_total"]
    # the chapters that had already been written were not rewritten
    after = {s["idx"]: s["content"] for s in rep["sections"]}
    assert {i: after[i] for i in kept_text} == kept_text
    assert api.db.data("users/u1")["balance_units"] < start_balance


def test_only_failed_reports_can_be_resumed(api):
    h, p = buyer(api)
    rid = api.client.post("/api/reports", headers=h,
                          json={"profile_id": p["id"]}).json()["report_id"]
    r = api.client.post("/api/reports/%s/resume" % rid, headers=h)
    assert r.status_code == 400 and r.json()["code"] == "invalid"


def test_report_needs_enough_balance(api):
    _, h = api.signup("u1")
    p = api.profile(h)
    api.db.collection("users").document("u1").update({"balance_units": 100})
    r = api.client.post("/api/reports", headers=h, json={"profile_id": p["id"]})
    assert r.status_code == 402 and r.json()["code"] == "insufficient_balance"
    assert list(api.db.collection("reports").stream()) == []


def test_reports_are_private(api):
    h, p = buyer(api, "u1")
    rid = api.client.post("/api/reports", headers=h,
                          json={"profile_id": p["id"]}).json()["report_id"]
    _, h2 = api.signup("u2", device="dev-u2-rep99")
    for path in ("/api/reports/%s" % rid, "/api/reports/%s/pdf" % rid):
        r = api.client.get(path, headers=h2)
        assert r.status_code == 404 and r.json()["code"] == "not_found"
    assert api.client.get("/api/reports", headers=h2).json() == []


def test_report_for_an_unknown_profile(api):
    h, _ = buyer(api)
    r = api.client.post("/api/reports", headers=h, json={"profile_id": "nope"})
    assert r.status_code == 404 and r.json()["code"] == "not_found"


def test_reports_respect_the_maintenance_flag(api):
    from app import store
    h, p = buyer(api)
    api.db.collection("config_flags").document("global").set({"opus_enabled": False})
    store.clear_flags_cache()
    r = api.client.post("/api/reports", headers=h, json={"profile_id": p["id"]})
    assert r.status_code == 503 and r.json()["code"] == "maintenance"
    store.clear_flags_cache()


# ------------------------------------------------------- astrologer brand ----

def test_branded_report_needs_a_brand_first(api):
    h, p = buyer(api, "astro-1")
    api.set_role("astro-1")
    r = api.client.post("/api/reports", headers=h,
                        json={"profile_id": p["id"], "brand": True})
    assert r.status_code == 400 and r.json()["code"] == "invalid"

    assert api.client.put("/api/astro/brand", headers=h, json=BRAND).status_code == 200
    r = api.client.post("/api/reports", headers=h,
                        json={"profile_id": p["id"], "brand": True})
    assert r.status_code == 200, r.text
    rid = r.json()["report_id"]
    rep = api.client.get("/api/reports/%s" % rid, headers=h).json()
    assert rep["branded"] is True and rep["status"] == "ready"
    assert api.db.data("reports/" + rid)["brand"]["display_name"] == BRAND["display_name"]

    assert api.client.get("/api/reports/%s/pdf" % rid, headers=h).status_code == 200
    data, _ = api.storage.objects["reports/astro-1/%s.pdf" % rid]
    assert data[:4] == b"%PDF" and len(data) > 5000


def test_advertised_report_price_is_what_the_wallet_is_charged(api):
    """Regression: /api/pricing once advertised a flat price while the wallet
    debited the per-language one."""
    h, p = buyer(api, lang="te")
    advertised = api.client.get("/api/pricing", headers=h).json()["report_price_units"]
    before = api.db.data("users/u1")["balance_units"]
    api.launch.paused = True
    api.client.post("/api/reports?lang=te", headers=h, json={"profile_id": p["id"]})
    charged = before - api.db.data("users/u1")["balance_units"]
    assert charged == advertised


def test_resume_charges_the_same_fee_as_the_purchase(api):
    from ai_fakes import FakeClaude
    from app import reports
    h, p = buyer(api, lang="hi", units=500000)
    api.set_models(c=FakeClaude(lang="hi", fail_chapters=range(2, len(reports.SECTIONS) + 1)))
    rid = api.client.post("/api/reports?lang=hi", headers=h,
                          json={"profile_id": p["id"]}).json()["report_id"]
    paid = fee_for("hi")
    api.set_models(c=FakeClaude(lang="hi"))
    before = api.db.data("users/u1")["balance_units"]
    api.client.post("/api/reports/%s/resume" % rid, headers=h)
    assert before - api.db.data("users/u1")["balance_units"] == paid
