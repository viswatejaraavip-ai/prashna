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
