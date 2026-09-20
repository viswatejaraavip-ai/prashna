"""Mega life report on the new store: charge, chapter generation, traces,
failure refund, resume keeping chapters, white-label PDF upload."""

import importlib.util
import threading
import time
import os
import sys
import types

import pytest

from ai_fakes import HERE, FakeClaude, FakeGemini

UID = "astro-1"


def _threaded_launch(reports):
    """The production _launch (a real background thread), so a test can poll
    progress while chapters are being written."""
    def launch(rid):
        t = threading.Thread(target=reports._generate, args=(rid,), daemon=True)
        t.start()
        launch.threads.append(t)
    launch.threads = []
    return launch


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
    claude = FakeClaude(lang="te", out_fraction=0.9)
    env.set_models(FakeGemini(), claude)
    return types.SimpleNamespace(reports=reports, db=db, billing=bill, uploads=uploads,
                                 env=env, claude=claude)


def test_full_report_flow_with_brand_and_pdf(rep):
    fee = rep.reports.report_fee_units("te")
    r = rep.reports.start_report(UID, "p1", "te", brand=True)
    rid = r["report_id"]
    assert rep.billing.charges == [(UID, fee, "report", rid)]
    got = rep.reports.get_report(UID, rid)
    assert got["status"] == "ready" and got["sections_done"] == 18 and got["branded"]
    assert len(got["sections"]) == 18
    chapter_traces = [t for t in rep.env.repo.traces if t["kind"] == "report_chapter"]
    assert len(chapter_traces) == 18
    assert all(s["name"] in ("outline", "reason") for t in chapter_traces for s in t["stages"])
    # Flash planned it once; that stage is billed to whichever chapter was
    # submitted first (they now finish in any order).
    assert sum(1 for t in chapter_traces
               if t["stages"][0]["name"] == "outline") == 1
    assert {"reports": 1, "revenue_units": fee} in rep.env.repo.rollups
    # the bundle cache is written once up front, not by every chapter
    assert len(rep.claude.warms) == 1 and rep.claude.warms[0]["max_tokens"] == 0

    url = rep.reports.pdf_url(UID, rid)
    path = "reports/%s/%s.pdf" % (UID, rid)
    assert url == "https://signed/" + path
    data, ct = rep.uploads[path]
    assert ct == "application/pdf" and data[:4] == b"%PDF" and len(data) > 10000
    # second call reuses the uploaded file
    rep.uploads.clear()
    assert rep.reports.pdf_url(UID, rid) == url and not rep.uploads


def test_failure_refunds_and_resume_keeps_chapters(rep):
    """Chapters 6-18 fail; the 5 that landed survive the refund and the resume
    only re-writes the missing ones."""
    reports = rep.reports
    fee = reports.report_fee_units("te")
    rep.claude.fail_chapters = set(range(6, 19))
    rid = reports.start_report(UID, "p1", "te")["report_id"]
    meta = reports.get_report(UID, rid)
    assert meta["status"] == "failed" and meta["sections_done"] == 5
    assert rep.billing.refunds == [(UID, fee, "refund", rid)]
    assert reports.progress(UID, rid)["percent"] == 27        # 5/18

    rep.claude.fail_chapters = set()
    before = len(rep.claude.calls)
    out = reports.resume_report(UID, rid)
    assert out["status"] == "generating"
    meta = reports.get_report(UID, rid)
    assert meta["status"] == "ready" and meta["sections_done"] == 18
    assert [s["idx"] for s in meta["sections"]] == list(range(1, 19))
    assert len(rep.billing.charges) == 2
    # only the 13 missing chapters were regenerated (3 attempts each for the
    # failed ones already happened in the first run)
    assert len(rep.claude.calls) - before == 13


def test_insufficient_balance_and_brand_required(rep):
    from app.ai.pipeline import AiError
    rep.billing.balance = 100
    with pytest.raises(AiError) as e:
        rep.reports.start_report(UID, "p1", "te")
    assert e.value.code == "insufficient_balance"
    with pytest.raises(AiError) as e:
        rep.reports.start_report("someone-else", "p1", "te", brand=True)
    assert e.value.code == "invalid"


def test_cost_ceiling_caps_every_chapter(rep, monkeypatch):
    """The ceiling is enforced per chapter up front (max_tokens), because
    parallel chapters cannot be shortened after the fact."""
    reports = rep.reports
    full_words, full_max = reports._chapter_plan("ml", reports.REPORT_SECTION_WORDS)
    monkeypatch.setattr(reports, "REPORT_COST_CEILING_UNITS", 1000)   # ₹10, absurdly low
    words, max_tok = reports._chapter_plan("ml", reports.REPORT_SECTION_WORDS)
    assert max_tok < full_max and words < full_words and max_tok >= 800

    reports.start_report(UID, "p1", "ml")
    assert all(kw["max_tokens"] == max_tok for kw in rep.claude.calls)
    targets = [t["words_target"] for t in rep.env.repo.traces if t["kind"] == "report_chapter"]
    assert targets and set(targets) == {words}


def test_chapters_run_concurrently(rep, monkeypatch):
    """18 chapters in one wave: the pool must actually overlap them, and the
    whole report must stay well inside the 5-minute budget."""
    reports = rep.reports
    rep.claude.chapter_delay = 0.05
    t0 = time.time()
    rid = reports.start_report(UID, "p1", "te")["report_id"]
    elapsed = time.time() - t0
    assert reports.get_report(UID, rid)["status"] == "ready"
    assert rep.claude.max_live >= 10          # not one chapter at a time
    assert elapsed < 18 * 0.05                # cheaper than running them serially


def test_global_chapter_semaphore_bounds_parallel_calls(rep, monkeypatch):
    reports = rep.reports
    monkeypatch.setattr(reports, "_GLOBAL_CHAPTERS", threading.BoundedSemaphore(4))
    rep.claude.chapter_delay = 0.02
    reports.start_report(UID, "p1", "te")
    assert rep.claude.max_live <= 4


def test_pre_warm_failure_is_not_fatal(rep):
    rep.claude.reject_warm = True
    rid = rep.reports.start_report(UID, "p1", "te")["report_id"]
    assert rep.reports.get_report(UID, rid)["status"] == "ready"


def test_teaser_is_flash_only(rep):
    out = rep.reports.generate_teaser(UID, "p1", "te")
    assert "teaser" in out
    assert out["full_report"]["price_units"] == rep.reports.report_fee_units("te")
    assert out["full_report"]["eta_seconds"] == rep.reports.REPORT_BUDGET_S
    t = rep.env.repo.traces[-1]
    assert t["kind"] == "teaser" and t["stages"][0]["model"].startswith("gemini")


# ---------------- pricing ----------------

def test_price_is_measured_cost_times_margin(rep, monkeypatch):
    reports = rep.reports
    monkeypatch.setattr(reports, "REPORT_SECTION_WORDS", 1000)   # the shipped length
    for lang in ("hi", "te", "ml", "en"):
        est = reports.estimate_cost_units(lang)
        fee = reports.report_fee_units(lang)
        assert fee >= est["total_units"] * reports.REPORT_MARGIN     # never under-priced
        assert fee % reports.REPORT_PRICE_ROUND_UNITS == 0           # a round price point
        assert fee - est["total_units"] * reports.REPORT_MARGIN < reports.REPORT_PRICE_ROUND_UNITS
        assert est["margin_pct"] >= 33.0                             # 1.5x cost => >= 1/3
    # Indic scripts cost more per word, so they cost more than English
    assert reports.report_fee_units("ml") > reports.report_fee_units("hi")
    assert reports.report_fee_units("hi") > reports.report_fee_units("en")
    # an unknown language can never be cheaper than the priciest real one
    assert reports.report_fee_units("") >= max(
        reports.report_fee_units(l) for l in reports.LANGS)


def test_price_env_overrides(rep, monkeypatch):
    reports = rep.reports
    monkeypatch.setenv("REPORT_FEE_UNITS_TE", "77700")
    assert reports.report_fee_units("te") == 77700
    monkeypatch.setattr(reports, "_FLAT_FEE_ENV", "105000")
    assert reports.report_fee_units("ml") == 105000       # flat override
    assert reports.report_fee_units("te") == 77700        # per-language still wins


def test_report_pricing_payload(rep):
    p = rep.reports.report_pricing()
    assert p["report_price_units"] == rep.reports.report_fee_units("")
    assert set(p["report_price_units_by_lang"]) == set(rep.reports.LANGS)
    assert p["report_chapters"] == 18 and p["report_eta_seconds"] == 300


# ---------------- progress ----------------

def test_progress_reports_percent_chapter_and_eta(rep, monkeypatch):
    """Poll the live endpoint while a real (threaded) generation runs."""
    reports = rep.reports
    monkeypatch.setattr(reports, "_launch", _threaded_launch(reports))
    # Deterministic partial states: 18 chapters two at a time means the poller
    # always sees several mid-generation snapshots. At full concurrency every
    # chapter can land between two polls and the test sees 0 -> 18.
    monkeypatch.setattr(reports, "REPORT_CONCURRENCY", 2)
    rep.claude.chapter_delay = 0.05
    seen = []
    rid = reports.start_report(UID, "p1", "te")["report_id"]
    for _ in range(400):
        p = reports.progress(UID, rid)
        seen.append(p)
        if p["status"] != "generating":
            break
        time.sleep(0.01)
    mid = [p for p in seen if 0 < p["sections_done"] < 18]
    assert mid, "no partial progress was ever visible"
    mid = mid[len(mid) // 2]
    assert 0 < mid["percent"] < 100 and mid["sections_total"] == 18
    assert mid["current_chapter"]["title"] and mid["current_chapter"]["idx"] >= 1
    assert mid["eta_seconds"] > 0 and mid["status"] == "generating"
    assert len(mid["chapters"]) == 18
    assert sum(1 for c in mid["chapters"] if c["done"]) == mid["sections_done"]

    end = reports.progress(UID, rid)
    assert end["percent"] == 100 and end["eta_seconds"] == 0
    assert end["status"] == "ready" and end["current_chapter"] is None
    assert all(c["done"] for c in end["chapters"])
    assert end["fee_units"] == reports.report_fee_units("te")


def test_progress_after_failure_shows_what_is_done(rep):
    rep.claude.fail_chapters = {9}
    rid = rep.reports.start_report(UID, "p1", "te")["report_id"]
    p = rep.reports.progress(UID, rid)
    assert p["status"] == "failed" and p["error"] and p["eta_seconds"] == 0
    assert 0 < p["percent"] < 100
    assert sum(1 for c in p["chapters"] if c["done"]) == p["sections_done"]


def test_progress_is_owner_only(rep):
    from app.ai.pipeline import AiError
    rid = rep.reports.start_report(UID, "p1", "te")["report_id"]
    with pytest.raises(AiError) as e:
        rep.reports.progress("someone-else", rid)
    assert e.value.code == "not_found"


# ---------------- the benchmark script ----------------

def test_report_bench_dry_run_prints_prices(rep, capsys, monkeypatch):
    """scripts/report_bench.py --dry-run: same arithmetic as the module, no
    network. (The measured mode needs ANTHROPIC_API_KEY and costs money.)"""
    import importlib.util
    monkeypatch.setattr(rep.reports, "REPORT_SECTION_WORDS", 1000)
    spec = importlib.util.spec_from_file_location(
        "report_bench", os.path.join(HERE, "..", "..", "scripts", "report_bench.py"))
    bench = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bench)
    rows = [bench.modelled(rep.reports, l, 1000, 18) for l in ("hi", "te", "ml", "en")]
    from app.ai import costs
    tpw = costs.TOKENS_PER_WORD["te"]
    assert rows[1]["tpw"] == tpw and rows[1]["out_tok"] == pytest.approx(1000 * tpw)
    bench.report_rows(rep.reports, rows, 1000, 18, 18, 300)
    out = capsys.readouterr().out
    assert "REPORT_FEE_UNITS_TE=%d" % rep.reports.report_fee_units("te") in out
    assert "1 wave(s)" in out and "TOKENS_PER_WORD" in out
