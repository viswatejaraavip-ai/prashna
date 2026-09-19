"""Mega life report on the new store: charge, chapter generation, traces,
failure refund, resume keeping chapters, white-label PDF upload."""

import importlib.util
import os
import sys
import types

import pytest

from ai_fakes import HERE, FakeClaude, FakeGemini

UID = "astro-1"


def _fake_firestore():
    spec = importlib.util.spec_from_file_location(
        "ai_tests_fake_firestore", os.path.join(HERE, "..", "admin", "admin_fakefs.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.FakeFirestore()


@pytest.fixture
def rep(env, monkeypatch):
    import app
    from app import reports, store
    db = _fake_firestore()
    monkeypatch.setattr(store, "_fs", db)
    monkeypatch.setattr(store, "get_flags", lambda: dict(env.flags))
    monkeypatch.setattr(reports, "REPORT_SECTION_WORDS", 300)
    monkeypatch.setattr(reports, "_launch", lambda rid: reports._generate(rid))

    class Billing:
        InsufficientBalance = type("InsufficientBalance", (Exception,), {})

        def __init__(self):
            self.charges, self.refunds, self.balance = [], [], 200000

        def charge(self, uid, units, type, ref):
            if units > self.balance:
                raise self.InsufficientBalance()
            self.balance -= units
            self.charges.append((uid, units, type, ref))

        def refund(self, uid, units, type, ref):
            self.balance += units
            self.refunds.append((uid, units, type, ref))

    bill = Billing()
    monkeypatch.setitem(sys.modules, "app.billing", bill)
    monkeypatch.setattr(app, "billing", bill, raising=False)

    uploads = {}
    storage = types.SimpleNamespace(
        upload_bytes=lambda path, data, ct: uploads.__setitem__(path, (data, ct)) or path,
        signed_url=lambda path, minutes=60: "https://signed/" + path)
    monkeypatch.setitem(sys.modules, "app.platform_storage", storage)
    monkeypatch.setattr(app, "platform_storage", storage, raising=False)

    db.collection("astro_brand").document(UID).set(
        {"display_name": "Sri Sai Jyotish", "phone": "+91 90000 00000",
         "logo_url": "", "footer": "Sri Sai Jyotish, Hyderabad"})
    env.set_models(FakeGemini(), FakeClaude(lang="te", out_fraction=0.9))
    return types.SimpleNamespace(reports=reports, db=db, billing=bill, uploads=uploads,
                                 env=env)


def test_full_report_flow_with_brand_and_pdf(rep):
    r = rep.reports.start_report(UID, "p1", "te", brand=True)
    rid = r["report_id"]
    assert rep.billing.charges == [(UID, 105000, "report", rid)]
    got = rep.reports.get_report(UID, rid)
    assert got["status"] == "ready" and got["sections_done"] == 18 and got["branded"]
    assert len(got["sections"]) == 18
    chapter_traces = [t for t in rep.env.repo.traces if t["kind"] == "report_chapter"]
    assert len(chapter_traces) == 18
    assert all(s["name"] in ("outline", "reason") for t in chapter_traces for s in t["stages"])
    assert chapter_traces[0]["stages"][0]["name"] == "outline"   # Flash planned it
    assert {"reports": 1, "revenue_units": 105000} in rep.env.repo.rollups

    url = rep.reports.pdf_url(UID, rid)
    path = "reports/%s/%s.pdf" % (UID, rid)
    assert url == "https://signed/" + path
    data, ct = rep.uploads[path]
    assert ct == "application/pdf" and data[:4] == b"%PDF" and len(data) > 10000
    # second call reuses the uploaded file
    rep.uploads.clear()
    assert rep.reports.pdf_url(UID, rid) == url and not rep.uploads


def test_failure_refunds_and_resume_keeps_chapters(rep, monkeypatch):
    reports = rep.reports
    real = reports._write_chapter
    calls = {"n": 0}

    def flaky(*a, **kw):
        calls["n"] += 1
        if calls["n"] > 5:
            raise RuntimeError("vertex 529 overloaded")
        return real(*a, **kw)

    monkeypatch.setattr(reports, "_write_chapter", flaky)
    rid = reports.start_report(UID, "p1", "te")["report_id"]
    meta = reports.get_report(UID, rid)
    assert meta["status"] == "failed" and meta["sections_done"] == 5
    assert rep.billing.refunds == [(UID, 105000, "refund", rid)]

    monkeypatch.setattr(reports, "_write_chapter", real)
    out = reports.resume_report(UID, rid)
    assert out["status"] == "generating"
    meta = reports.get_report(UID, rid)
    assert meta["status"] == "ready" and meta["sections_done"] == 18
    assert [s["idx"] for s in meta["sections"]] == list(range(1, 19))
    assert len(rep.billing.charges) == 2


def test_insufficient_balance_and_brand_required(rep):
    from app.ai.pipeline import AiError
    rep.billing.balance = 100
    with pytest.raises(AiError) as e:
        rep.reports.start_report(UID, "p1", "te")
    assert e.value.code == "insufficient_balance"
    with pytest.raises(AiError) as e:
        rep.reports.start_report("someone-else", "p1", "te", brand=True)
    assert e.value.code == "invalid"


def test_cost_guard_shortens_late_chapters(rep, monkeypatch):
    reports = rep.reports
    monkeypatch.setattr(reports, "REPORT_COST_CEILING_UNITS", 1000)   # ₹10, absurdly low
    rid = reports.start_report(UID, "p1", "ml")["report_id"]
    targets = [t["words_target"] for t in rep.env.repo.traces if t["kind"] == "report_chapter"]
    assert targets[0] == 300 and min(targets) == 150     # floored at 50%


def test_teaser_is_flash_only(rep):
    out = rep.reports.generate_teaser(UID, "p1", "te")
    assert "teaser" in out and out["full_report"]["price_units"] == 105000
    t = rep.env.repo.traces[-1]
    assert t["kind"] == "teaser" and t["stages"][0]["model"].startswith("gemini")
