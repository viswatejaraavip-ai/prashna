"""Flow: paid consultation — sessions, ask (ok / refused / clarify /
insufficient balance / rate limited), the SSE stream and cloud voice.

Asserts the money rules and the trace shape from CONTRACT.md ("AI pipeline"
and the `traces` document), not just HTTP 200.
"""

import json

import pytest

from ai_fakes import FakeClaude, FakeGemini

PLAN_OK = {"status": "ok", "intent": "career",
           "tools": [{"name": "full_analysis"}], "focus": "Career", "reply": ""}
PLAN_REFUSED = {"status": "refused", "intent": "off_topic", "tools": [], "focus": "",
                "reply": "🙏 నేను జ్యోతిషానికి సంబంధించిన ప్రశ్నలకే సమాధానం ఇవ్వగలను."}
PLAN_CLARIFY = {"status": "clarify", "intent": "greeting", "tools": [], "focus": "",
                "reply": "నమస్తే! మీ ప్రశ్న అడగండి."}


def ready(api, uid="u1", lang="te", units=5000, mode="text"):
    """A signed-in user with a profile, a topped-up wallet and a session."""
    _, h = api.signup(uid, device="dev-" + uid + "-0001", lang=lang)
    p = api.profile(h)
    if units:
        api.topup(uid, units)
    return h, p, api.session(h, p["id"], mode)


# -------------------------------------------------------------- sessions ----

def test_session_lifecycle(api):
    h, p, sid = ready(api)
    rows = api.client.get("/api/sessions", headers=h).json()
    assert len(rows) == 1
    assert rows[0]["session_id"] == sid and rows[0]["profile_id"] == p["id"]
    assert rows[0]["lang"] == "te" and rows[0]["mode"] == "text"
    assert "summary" not in rows[0]          # internal English memory, never shown

    assert api.client.get("/api/sessions/%s/messages" % sid, headers=h).json() == []

    missing = api.client.post("/api/sessions", headers=h,
                              json={"profile_id": "nope", "mode": "text"})
    assert missing.status_code == 404 and missing.json()["code"] == "not_found"

    bad_mode = api.client.post("/api/sessions", headers=h,
                               json={"profile_id": p["id"], "mode": "telepathy"})
    assert bad_mode.status_code == 422


def test_sessions_are_private(api):
    h, _, sid = ready(api, "u1")
    _, h2 = api.signup("u2", device="dev-u2-0002")
    r = api.client.post("/api/sessions/%s/ask" % sid, headers=h2, json={"text": "career?"})
    assert r.status_code == 404 and r.json()["code"] == "not_found"
    assert api.client.get("/api/sessions/%s/messages" % sid,
                          headers=h2).status_code == 404


# ------------------------------------------------------------------- ask ----

def test_ask_ok_charges_ten_rupees_and_writes_a_contract_trace(api):
    h, p, sid = ready(api)
    api.set_models(FakeGemini(plan=PLAN_OK), FakeClaude(lang="te"))
    r = api.client.post("/api/sessions/%s/ask" % sid, headers=h,
                        json={"text": "నా ఉద్యోగం ఎప్పుడు మారుతుంది?"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"reply", "charged_units", "balance_units", "status", "trace_id"}
    assert body["status"] == "ok"
    assert body["charged_units"] == 1000                      # flat Rs 10
    assert body["balance_units"] == 1000 + 5000 - 1000        # trial + topup - fee
    assert body["reply"]

    trace = api.db.data("traces/" + body["trace_id"])
    assert trace["uid"] == "u1" and trace["session_id"] == sid
    assert trace["lang"] == "te" and trace["mode"] == "text" and trace["kind"] == "query"
    assert trace["status"] == "ok" and trace["charged_units"] == 1000
    assert trace["question_chars"] > 0 and trace["latency_ms"] >= 0
    assert trace["error"] is None
    names = [s["name"] for s in trace["stages"]]
    assert names[:3] == ["plan", "tools", "brief"] and "reason" in names
    assert trace["cost_units"] == sum(s["cost_units"] for s in trace["stages"])
    # the Rs 5 provider-cost ceiling (CONTRACT: QUERY_COST_CEILING_UNITS)
    assert 0 < trace["cost_units"] < 500
    reason = [s for s in trace["stages"] if s["name"] == "reason"][0]
    assert reason["model"].startswith("claude")
    assert [s for s in trace["stages"] if s["name"] == "plan"][0]["model"].startswith("gemini")

    # wallet + ledger
    assert api.ledger_types("u1") == ["trial", "topup", "query"]
    ledger = [e for e in api.db.children("users/u1/ledger") if e["type"] == "query"][0]
    assert ledger["delta_units"] == -1000 and ledger["ref"] == body["trace_id"]
    assert ledger["balance_after"] == body["balance_units"]

    # session transcript
    msgs = api.client.get("/api/sessions/%s/messages" % sid, headers=h).json()
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[1]["charged_units"] == 1000 and msgs[1]["trace_id"] == body["trace_id"]
    assert all(set(m) == {"role", "text", "charged_units", "trace_id", "created_at"}
               for m in msgs)

    # rollups
    roll = api.rollup()
    assert roll["queries"] == 1 and roll["revenue_units"] == 1000
    assert roll["by_lang"]["te"] == 1 and roll["cost_units"] > 0


@pytest.mark.parametrize("lang", ["hi", "te", "ta", "kn", "ml"])
def test_ask_answers_in_the_users_language(api, lang):
    h, p, sid = ready(api, "u-" + lang, lang=lang)
    api.set_models(FakeGemini(plan=PLAN_OK), FakeClaude(lang=lang))
    r = api.client.post("/api/sessions/%s/ask" % sid, headers=h, json={"text": "career?"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ok"
    trace = api.db.data("traces/" + r.json()["trace_id"])
    assert trace["lang"] == lang
    assert api.rollup()["by_lang"][lang] == 1


def test_refused_turn_is_free(api):
    h, p, sid = ready(api)
    api.set_models(FakeGemini(plan=PLAN_REFUSED), FakeClaude())
    r = api.client.post("/api/sessions/%s/ask" % sid, headers=h,
                        json={"text": "ఈ రోజు క్రికెట్ స్కోరు ఎంత?"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "refused" and body["charged_units"] == 0
    assert body["balance_units"] == 6000 and body["reply"]
    assert api.ledger_types("u1") == ["trial", "topup"]       # nothing debited
    assert api.db.data("traces/" + body["trace_id"])["status"] == "refused"
    assert api.rollup()["refusals"] == 1 and "queries" not in api.rollup()
    # a free turn was counted against the session
    assert api.db.data("sessions/" + sid)["free_turns"] == 1


def test_clarify_turn_is_free(api):
    h, p, sid = ready(api)
    api.set_models(FakeGemini(plan=PLAN_CLARIFY), FakeClaude())
    r = api.client.post("/api/sessions/%s/ask" % sid, headers=h, json={"text": "namaste"})
    body = r.json()
    assert body["status"] == "clarify" and body["charged_units"] == 0
    assert body["reply"]
    assert api.db.data("traces/" + body["trace_id"])["status"] == "clarify"


def test_off_topic_dump_is_refused_before_any_model_call(api):
    h, p, sid = ready(api)
    gemini = FakeGemini(plan=PLAN_OK)
    api.set_models(gemini, FakeClaude())
    r = api.client.post("/api/sessions/%s/ask" % sid, headers=h,
                        json={"text": "<html><body><script>alert(1)</script></body></html>"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "refused" and r.json()["charged_units"] == 0
    assert gemini.calls == []                       # no tokens were spent
    assert api.db.data("traces/" + r.json()["trace_id"])["cost_units"] == 0


def test_free_turns_are_capped_per_session(api, monkeypatch):
    from app.ai import pipeline
    monkeypatch.setattr(pipeline, "FREE_TURNS_HARD", 2)
    h, p, sid = ready(api)
    api.set_models(FakeGemini(plan=PLAN_CLARIFY), FakeClaude())
    for _ in range(2):
        assert api.client.post("/api/sessions/%s/ask" % sid, headers=h,
                               json={"text": "hi"}).json()["charged_units"] == 0
    gemini = FakeGemini(plan=PLAN_CLARIFY)
    api.set_models(gemini, FakeClaude())
    r = api.client.post("/api/sessions/%s/ask" % sid, headers=h, json={"text": "hi again"})
    assert r.json()["status"] == "refused" and r.json()["charged_units"] == 0
    assert gemini.calls == []                       # capped without a model call


def test_insufficient_balance_is_402(api):
    h, p, sid = ready(api, units=0)
    api.db.collection("users").document("u1").update({"balance_units": 999})
    r = api.client.post("/api/sessions/%s/ask" % sid, headers=h, json={"text": "career?"})
    assert r.status_code == 402
    assert r.json()["code"] == "insufficient_balance"
    assert list(api.db.collection("traces").stream()) == []   # nothing was spent


def test_rate_limited_is_429(api, monkeypatch):
    from app.ai import pipeline
    monkeypatch.setattr(pipeline, "AI_RATE_LIMIT", 2)
    h, p, sid = ready(api, units=50000)
    api.set_models(FakeGemini(plan=PLAN_OK), FakeClaude())
    for _ in range(2):
        assert api.client.post("/api/sessions/%s/ask" % sid, headers=h,
                               json={"text": "career?"}).status_code == 200
    r = api.client.post("/api/sessions/%s/ask" % sid, headers=h, json={"text": "career?"})
    assert r.status_code == 429 and r.json()["code"] == "rate_limited"


def test_empty_and_overlong_questions_are_rejected(api):
    h, p, sid = ready(api)
    assert api.client.post("/api/sessions/%s/ask" % sid, headers=h,
                           json={"text": ""}).status_code == 422
    r = api.client.post("/api/sessions/%s/ask" % sid, headers=h, json={"text": "x" * 1300})
    assert r.status_code == 400 and r.json()["code"] == "invalid"


def test_maintenance_flag_pauses_consultations(api):
    from app import store
    h, p, sid = ready(api)
    api.db.collection("config_flags").document("global").set(
        {"maintenance_message": "Pooja in progress, back at 6pm"})
    store.clear_flags_cache()
    r = api.client.post("/api/sessions/%s/ask" % sid, headers=h, json={"text": "career?"})
    assert r.status_code == 503 and r.json()["code"] == "maintenance"
    store.clear_flags_cache()


def test_opus_kill_switch(api):
    from app import store
    h, p, sid = ready(api)
    api.db.collection("config_flags").document("global").set({"opus_enabled": False})
    store.clear_flags_cache()
    r = api.client.post("/api/sessions/%s/ask" % sid, headers=h, json={"text": "career?"})
    assert r.status_code == 503 and r.json()["code"] == "maintenance"
    store.clear_flags_cache()


# ------------------------------------------------------------- SSE stream ----

def _events(text):
    return [blk for blk in text.split("\n\n") if blk.startswith("event:")]


def test_ask_stream_sse_frames(api):
    h, p, sid = ready(api)
    api.set_models(FakeGemini(plan=PLAN_OK), FakeClaude(lang="te"))
    r = api.client.post("/api/sessions/%s/ask/stream" % sid, headers=h,
                        json={"text": "నా వివాహం ఎప్పుడు?"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    events = _events(r.text)
    assert events[0].startswith("event: delta")
    assert events[-1].startswith("event: done")
    deltas = "".join(json.loads(e.split("data: ", 1)[1])["text"]
                     for e in events if e.startswith("event: delta"))
    assert deltas
    done = json.loads(events[-1].split("data: ", 1)[1])
    assert set(done) == {"charged_units", "balance_units", "status", "trace_id"}
    assert done["status"] == "ok" and done["charged_units"] == 1000
    assert done["balance_units"] == 5000
    assert api.db.data("traces/" + done["trace_id"])["status"] == "ok"


def test_stream_sends_a_refusal_as_one_delta(api):
    h, p, sid = ready(api)
    api.set_models(FakeGemini(plan=PLAN_REFUSED), FakeClaude())
    r = api.client.post("/api/sessions/%s/ask/stream" % sid, headers=h,
                        json={"text": "cricket score?"})
    events = _events(r.text)
    assert len(events) == 2
    assert json.loads(events[0].split("data: ", 1)[1])["text"]
    done = json.loads(events[1].split("data: ", 1)[1])
    assert done["status"] == "refused" and done["charged_units"] == 0


def test_stream_reports_http_errors_before_it_opens(api):
    h, p, sid = ready(api, units=0)
    api.db.collection("users").document("u1").update({"balance_units": 0})
    r = api.client.post("/api/sessions/%s/ask/stream" % sid, headers=h,
                        json={"text": "career?"})
    assert r.status_code == 402 and r.json()["code"] == "insufficient_balance"


# ------------------------------------------------------------------ voice ----

def test_voice_query_transcribes_charges_and_speaks(api):
    h, p, sid = ready(api, mode="voice")
    api.set_models(FakeGemini(plan=PLAN_OK), FakeClaude(lang="te"))
    r = api.client.post("/api/sessions/%s/voice" % sid, headers=h,
                        files={"audio": ("q.ogg", b"OggS" + b"\0" * 2048, "audio/ogg")},
                        data={"tts": "true"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["transcript"] == api.heard["text"]
    assert body["status"] == "ok" and body["charged_units"] == 1000
    assert body["audio_b64"]

    trace = api.db.data("traces/" + body["trace_id"])
    assert trace["mode"] == "voice"
    names = [s["name"] for s in trace["stages"]]
    assert names[0] == "stt" and "tts" in names
    assert trace["cost_units"] < 500           # speech counts toward the ceiling
    assert api.rollup()["voice_queries"] == 1


def test_voice_without_tts_returns_no_audio(api):
    h, p, sid = ready(api, mode="voice")
    api.set_models(FakeGemini(plan=PLAN_OK), FakeClaude(lang="te"))
    r = api.client.post("/api/sessions/%s/voice" % sid, headers=h,
                        files={"audio": ("q.ogg", b"OggS" + b"\0" * 1024, "audio/ogg")},
                        data={"tts": "false"})
    assert r.status_code == 200 and "audio_b64" not in r.json()


def test_voice_rejects_empty_or_huge_audio(api):
    from app import routes_ai
    h, p, sid = ready(api, mode="voice")
    r = api.client.post("/api/sessions/%s/voice" % sid, headers=h,
                        files={"audio": ("q.ogg", b"", "audio/ogg")})
    assert r.status_code == 400 and r.json()["code"] == "invalid"
    big = b"\0" * (routes_ai.MAX_AUDIO_BYTES + 10)
    r = api.client.post("/api/sessions/%s/voice" % sid, headers=h,
                        files={"audio": ("q.ogg", big, "audio/ogg")})
    assert r.status_code == 400 and r.json()["code"] == "invalid"


def test_cloud_voice_kill_switch(api):
    from app import store
    h, p, sid = ready(api, mode="voice")
    api.db.collection("config_flags").document("global").set({"voice_cloud_enabled": False})
    store.clear_flags_cache()
    r = api.client.post("/api/sessions/%s/voice" % sid, headers=h,
                        files={"audio": ("q.ogg", b"OggS" + b"\0" * 512, "audio/ogg")})
    assert r.status_code == 503 and r.json()["code"] == "maintenance"
    store.clear_flags_cache()


# --------------------------------------------------- memory provenance ----

def test_memory_written_before_grounding_is_retired_not_believed(api):
    """Regression (backend/evals/RESULTS.md): the agent stored its own
    predictions as the client's biography, then read them back as history —
    "based on ... your session memory noting marriage occurred between late
    2021 and mid-2022", to a client who never said it. Facts written before
    memory.grounded() existed carry no provenance, so they are not used, and
    they are retired out of the way instead of sitting in the profile."""
    from app.ai import repo
    h, p, sid = ready(api)
    poisoned = ["Marriage occurred between February and October 2021",
                "Ascendant is Virgo (Kanya)"]
    api.db.collection("users").document("u1").collection("ai_memory") \
       .document(p["id"]).set({"facts": poisoned})          # no "v": legacy

    assert repo.get_memory("u1", p["id"]) == []             # not believed
    doc = api.db.data("users/u1/ai_memory/" + p["id"])
    assert doc["facts"] == [] and doc["legacy_facts"] == poisoned
    assert doc["v"] == repo.MEMORY_VERSION and doc["retired_at"]

    # and nothing the astrologer said gets written back in its place
    api.set_models(g=FakeGemini(plan=PLAN_OK), c=FakeClaude(lang="te"))
    r = api.client.post("/api/sessions/%s/ask" % sid, headers=h,
                        json={"text": "నా ఉద్యోగం ఎప్పుడు మారుతుంది?"})
    assert r.status_code == 200, r.text
    after = api.db.data("users/u1/ai_memory/" + p["id"])
    assert all(f not in (after.get("facts") or []) for f in poisoned)
