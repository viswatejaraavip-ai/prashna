"""HTTP surface of routes_ai (contract shapes, SSE framing, error codes)."""

import json

import pytest

from ai_fakes import FLAGS, FakeClaude, FakeGemini

UID = "u-routes"


@pytest.fixture
def client(env, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app import routes_ai, store
    from app.ai import repo

    sessions = {"s1": {"id": "s1", "uid": UID, "profile_id": "p1", "lang": "te",
                       "mode": "text", "summary": "", "free_turns": 0}}
    monkeypatch.setattr(repo, "get_session", lambda sid: sessions.get(sid))
    monkeypatch.setattr(repo, "create_session", lambda uid, pid, lang, mode: "s-new")
    monkeypatch.setattr(store, "get_user", lambda uid: {"uid": uid, "lang": "te",
                                                        "balance_units": env.repo.balance})
    monkeypatch.setattr(store, "get_flags", lambda: dict(FLAGS))
    app = FastAPI()
    app.include_router(routes_ai.router)
    c = TestClient(app)
    c.headers.update({"Authorization": "Bearer " + store.issue_token(UID)})
    return c


def test_create_session(client):
    r = client.post("/api/sessions", json={"profile_id": "p1", "mode": "voice"})
    assert r.status_code == 200 and r.json() == {"session_id": "s-new"}


def test_ask_contract_shape(client, env):
    env.set_models(FakeGemini(), FakeClaude())
    r = client.post("/api/sessions/s1/ask", json={"text": "నా ఉద్యోగం ఎలా ఉంటుంది?"})
    body = r.json()
    assert r.status_code == 200, body
    assert set(body) == {"reply", "charged_units", "balance_units", "status", "trace_id"}
    assert body["status"] == "ok" and body["charged_units"] == 1000
    assert body["balance_units"] == 4000


def test_ask_stream_sse(client, env):
    env.set_models(FakeGemini(), FakeClaude())
    r = client.post("/api/sessions/s1/ask/stream", json={"text": "నా వివాహం ఎప్పుడు?"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    events = [blk for blk in r.text.split("\n\n") if blk.startswith("event:")]
    assert events[0].startswith("event: delta") and events[-1].startswith("event: done")
    done = json.loads(events[-1].split("data: ", 1)[1])
    assert set(done) == {"charged_units", "balance_units", "status", "trace_id"}


def test_stream_refusal_sent_as_single_delta(client, env):
    env.set_models(FakeGemini(plan={"status": "clarify", "intent": "greeting", "tools": [],
                                    "focus": "", "reply": "నమస్తే! మీ ప్రశ్న అడగండి."}),
                   FakeClaude())
    r = client.post("/api/sessions/s1/ask/stream", json={"text": "hi"})
    events = [blk for blk in r.text.split("\n\n") if blk.startswith("event:")]
    assert len(events) == 2 and "నమస్తే" in events[0]
    assert json.loads(events[1].split("data: ", 1)[1])["charged_units"] == 0


def test_errors_use_contract_codes(client, env):
    env.repo.balance = 10
    r = client.post("/api/sessions/s1/ask", json={"text": "career?"})
    assert r.status_code == 402 and r.json()["code"] == "insufficient_balance"
    r = client.post("/api/sessions/nope/ask", json={"text": "career?"})
    assert r.status_code == 404 and r.json() == {"detail": "Session not found",
                                                 "code": "not_found"}
    r = client.post("/api/sessions/s1/ask", json={"text": "x" * 1300})
    assert r.status_code == 400 and r.json()["code"] == "invalid"


def test_voice_endpoint(client, env, monkeypatch):
    env.set_models(FakeGemini(), FakeClaude())
    monkeypatch.setattr(env.speech, "transcribe",
                        lambda data, lang: env.fake_transcribe(data, lang, 6.0,
                                                               "నా ఆరోగ్యం ఎలా ఉంటుంది?"))
    r = client.post("/api/sessions/s1/voice", files={"audio": ("q.ogg", b"OggS....", "audio/ogg")},
                    data={"tts": "true"})
    body = r.json()
    assert r.status_code == 200, body
    assert body["transcript"].startswith("నా") and body["audio_b64"]
    assert body["status"] == "ok" and body["charged_units"] == 1000


# ---------------- report progress & pricing ----------------

@pytest.fixture
def reports_client(client, monkeypatch):
    """routes_ai wired to a stub reports module (the module itself is covered
    by test_reports.py; here we only check the HTTP surface)."""
    import types
    from app.ai.pipeline import AiError
    from app import routes_ai

    state = {"status": "generating", "done": 4}

    def progress(uid, rid):
        if rid != "r1" or uid != UID:
            raise AiError(404, "not_found", "Report not found")
        done = state["done"]
        return {"report_id": rid, "status": state["status"], "percent": int(done * 100 / 18),
                "sections_done": done, "sections_total": 18,
                "current_chapter": {"idx": done + 1, "title": "వృత్తి"},
                "chapters": [{"idx": i, "title": "ch%d" % i, "done": i <= done}
                             for i in range(1, 19)],
                "eta_seconds": 90, "elapsed_seconds": 40, "error": None,
                "refund_pending": False, "fee_units": 40000}

    stub = types.SimpleNamespace(
        progress=progress, REPORT_BUDGET_S=300,
        report_fee_units=lambda lang="": {"te": 40000, "hi": 25000}.get(lang, 45000),
        report_pricing=lambda: {"report_price_units": 45000,
                                "report_price_units_by_lang": {"te": 40000, "hi": 25000},
                                "report_chapters": 18, "report_words": 18000,
                                "report_eta_seconds": 300})
    monkeypatch.setattr(routes_ai, "_reports", lambda: stub)
    monkeypatch.setattr(routes_ai, "REPORT_POLL_S", 0.01)
    client.state = state
    return client


def test_report_progress_endpoint(reports_client):
    r = reports_client.get("/api/reports/r1/progress")
    body = r.json()
    assert r.status_code == 200, body
    assert body["percent"] == 22 and body["sections_total"] == 18
    assert body["current_chapter"]["idx"] == 5 and body["eta_seconds"] == 90
    assert sum(1 for c in body["chapters"] if c["done"]) == 4


def test_report_progress_not_found(reports_client):
    r = reports_client.get("/api/reports/nope/progress")
    assert r.status_code == 404 and r.json()["code"] == "not_found"


def test_report_progress_stream(reports_client):
    reports_client.state["status"] = "ready"
    r = reports_client.get("/api/reports/r1/progress/stream")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    events = [blk for blk in r.text.split("\n\n") if blk.startswith("event:")]
    assert events[0].startswith("event: progress")
    assert events[-1].startswith("event: done")
    assert json.loads(events[-1].split("data: ", 1)[1])["status"] == "ready"


def test_report_pricing_endpoint_uses_the_users_language(reports_client):
    r = reports_client.get("/api/reports/pricing")
    body = r.json()
    assert r.status_code == 200, body
    assert body["lang"] == "te" and body["report_price_units"] == 40000
    assert body["report_price_units_by_lang"]["hi"] == 25000
    assert body["report_chapters"] == 18 and body["report_eta_seconds"] == 300
