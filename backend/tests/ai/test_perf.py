"""Latency work (docs/launch/AGENT_BENCH.md) and the budget rules it touched.

Every optimisation here is allowed to make the query faster or cheaper; none
of them may weaken the < ₹5 ceiling, lose a trace stage, or drop the current
date out of the models' context. That is what these tests pin down.
"""

from datetime import datetime

import pytest

from ai_fakes import FakeClaude, FakeGemini

UID = "u-perf"
TE_Q = "నా ఉద్యోగంలో వచ్చే రెండు సంవత్సరాల్లో ప్రమోషన్ వస్తుందా?"
FROZEN = datetime.fromisoformat("2026-09-20T14:35:00+05:30")

NARROW_PLAN = {"status": "ok", "intent": "panchanga", "tools": [{"name": "current_dasha"}],
               "focus": "Running dasha with dates.", "reply": ""}


def _session(lang="te", mode="text", summary="", sid="s1"):
    return {"id": sid, "uid": UID, "profile_id": "p1", "lang": lang, "mode": mode,
            "summary": summary, "query_count": 0, "free_turns": 0}


def _stage(trace, name):
    return next(s for s in trace["stages"] if s["name"] == name)


@pytest.fixture
def frozen():
    from app.ai import clock
    clock.freeze(FROZEN)
    yield clock
    clock.freeze(None)


# ---------------- the agent knows what day it is ----------------

def test_reasoner_request_carries_the_current_date(frozen):
    from app.ai import reasoner
    plan = reasoner.fit(lang="te", mode="text", question=TE_Q, brief="- Lagna Virgo.",
                        summary="", memory=[], profile={"name": "Ravi", "relation": "self"},
                        remaining_paise=400.0, tts_tier=None)
    user = plan["messages"][0]["content"]
    assert user.startswith("Now: ")
    # Both the human form and the machine form, so the model can do date maths.
    assert "20 September 2026" in user and "2026-09-20" in user
    assert "IST" in user and "Sunday" in user
    # ...and it is told to trust that over its own sense of the date.
    assert "never use it" in reasoner.SYSTEM_PROMPT


def test_every_model_stage_gets_the_same_now(frozen, env):
    """plan, brief and memory must agree with the reasoner about today."""
    from app.ai import pipeline
    gem = FakeGemini()
    env.set_models(gem, FakeClaude())
    pipeline.run_query(UID, _session("te"), TE_Q, prechecked=env.flags)
    sent = [c for c in gem.calls]
    assert {c["name"] for c in sent} >= {"plan", "brief", "memory"}
    stamp = frozen.stamp()
    for call in gem.sent_text:
        assert stamp in call, "a Flash stage was not told the current date"


def test_clock_is_ist_not_utc(frozen):
    """22:00 UTC is already tomorrow in India; the app must say tomorrow."""
    from app.ai import clock
    clock.freeze(datetime.fromisoformat("2026-09-20T22:30:00+00:00"))
    assert clock.today_iso() == "2026-09-21"
    assert "21 September 2026" in clock.stamp()


# ---------------- deterministic pruning keeps the facts ----------------

def test_prune_shrinks_without_changing_facts(frozen):
    from app.ai import executor
    raw = ('{"dashas":{"vimshottari":{"running":{"lord":"Jupiter",'
           '"start":"2013-05-27T20:33:51.328760+00:00",'
           '"end":"2029-05-27T20:33:51.328760+00:00"},'
           '"mahadashas":[{"lord":"Mars","start":"1988-05-27T14:33:51+00:00",'
           '"end":"1995-05-28T08:33:51+00:00"},'
           '{"lord":"Rahu","start":"1995-05-28T08:33:51+00:00",'
           '"end":"2013-05-27T20:33:51+00:00"},'
           '{"lord":"Jupiter","start":"2013-05-27T20:33:51+00:00",'
           '"end":"2029-05-27T20:33:51+00:00"},'
           '{"lord":"Saturn","start":"2029-05-27T20:33:51+00:00",'
           '"end":"2048-05-27T20:33:51+00:00"}]}},'
           '"kp":{"cusps":[{"cusp":1,"longitude":154.730909123}]}}')
    out = executor.prune(raw)
    assert len(out) < len(raw) * 0.8
    # timestamps collapse to dates, degrees to 2dp
    assert '"end":"2029-05-27"' in out and '"longitude":154.73' in out
    assert "T20:33:51" not in out
    # the running period and its neighbours survive
    assert out.count('"Jupiter"') >= 2 and "Saturn" in out and "Rahu" in out


def test_prune_keeps_recent_history_for_past_questions(frozen):
    """'Why did I lose my job in 2019?' still needs the period that was
    running then, so pruning keeps a couple of expired entries."""
    from app.ai import executor
    periods = ",".join(
        '{"lord":"L%d","start":"%d-01-01","end":"%d-01-01"}' % (i, 1990 + i, 1991 + i)
        for i in range(40))
    out = executor.prune('{"mahadashas":[%s]}' % periods)
    assert '"L35"' in out and '"L36"' in out      # 2025/2026: recent past + running
    assert '"L0"' not in out                      # 1990: dropped


def test_prune_is_a_no_op_on_non_json():
    from app.ai import executor
    assert executor.prune("not json at all") == "not json at all"


# ---------------- skipping the brief on small engine output ----------------

def test_small_engine_output_skips_the_flash_brief(env, frozen):
    from app.ai import pipeline
    gem = FakeGemini(plan=NARROW_PLAN)
    env.set_models(gem, FakeClaude())
    r = pipeline.run_query(UID, _session("te"), TE_Q, prechecked=env.flags)
    assert r.status == "ok"
    # No Flash brief call was made...
    assert [c["name"] for c in gem.calls] == ["plan", "memory"]
    # ...but the stage is still in the trace, with zero cost, as the contract
    # requires the stage list to be complete.
    brief = _stage(r.trace, "brief")
    assert brief["cost_units"] == 0
    assert brief["detail"]["skipped"] == "small_engine_output"
    assert r.trace["cost_units"] < 500


def test_wide_reading_still_condenses_through_flash(env, frozen):
    from app.ai import pipeline
    gem = FakeGemini()          # default plan: full_analysis + varga
    env.set_models(gem, FakeClaude())
    r = pipeline.run_query(UID, _session("te"), TE_Q, prechecked=env.flags)
    assert "brief" in [c["name"] for c in gem.calls]
    assert _stage(r.trace, "brief")["cost_units"] > 0


def test_brief_skip_respects_the_ceiling(env, frozen):
    """Handing Opus raw JSON must be budgeted on the raw JSON, not on the
    brief it replaced — otherwise the ceiling could be blown by the swap."""
    from app.ai import pipeline
    env.set_models(FakeGemini(plan=NARROW_PLAN, use_full_output=True),
                   FakeClaude(out_fraction=1.0, count_ok=False, report_in="estimate"))
    r = pipeline.run_query(UID, _session("te"), TE_Q,
                           prechecked=dict(env.flags, cost_ceiling_units=500))
    assert r.trace["cost_units"] <= 500
    assert r.status in ("ok", "over_ceiling")
    assert r.status == "ok", "worst case must still fit under the ceiling"


# ---------------- the exact token count is only paid for when it matters ----

def test_count_tokens_skipped_when_the_estimate_already_affords_the_cap(frozen):
    from app.ai import llm, reasoner
    calls = []

    def spy(system, messages, model=None):
        calls.append(1)
        return 100

    old, llm.count_tokens = llm.count_tokens, spy
    try:
        loose = reasoner.fit(lang="en", mode="voice", question="hi", brief="b",
                             summary="", memory=[], profile={},
                             remaining_paise=480.0, tts_tier=None)
        assert calls == [], "no round trip needed: the worst case already fits"
        assert loose["exact"] is False
        tight = reasoner.fit(lang="en", mode="text", question="hi", brief="b" * 4000,
                             summary="", memory=[], profile={},
                             remaining_paise=90.0, tts_tier=None)
        assert calls, "when the budget binds, pay for the exact count"
        assert tight["exact"] is True
    finally:
        llm.count_tokens = old


def test_the_estimate_is_an_upper_bound_so_skipping_cannot_overspend():
    """The whole safety argument for skipping count-tokens."""
    from app.ai import costs
    from ai_fakes import realistic_tokens
    for text in ("Career prospects for the next two years, in detail.",
                 "నా ఉద్యోగంలో వచ్చే రెండు సంవత్సరాలు ఎలా ఉంటాయి?",
                 "मेरा विवाह कब तक होगा?", '{"lord":"Jupiter","end":"2029-05-27"}'):
        assert costs.estimate_tokens(text) >= realistic_tokens(text)


# ---------------- a thinking reasoning model (Opus 5) ----------------

def test_non_thinking_model_budget_is_unchanged():
    from app.ai import budget
    assert budget.mode_max_tokens("text") == budget.TEXT_MAX_OUTPUT_TOKENS
    assert budget.mode_min_tokens("voice") == budget.VOICE_MIN_OUTPUT_TOKENS
    assert budget.answer_tokens(1000) == 1000


def test_thinking_model_reserves_output_room_for_its_reasoning(monkeypatch):
    """Opus 5 spends thinking tokens inside max_tokens and bills them as
    output, so the cap widens, the minimum we insist on widens with it, and
    the length target we ask for does NOT."""
    from app.ai import budget, llm
    monkeypatch.setattr(llm, "CLAUDE_MODEL", "claude-opus-5")
    assert budget.mode_max_tokens("text") > budget.TEXT_MAX_OUTPUT_TOKENS
    assert budget.mode_min_tokens("text") > budget.TEXT_MIN_OUTPUT_TOKENS
    # the visible answer stays the same length
    assert budget.answer_tokens(budget.mode_max_tokens("text")) == \
        pytest.approx(budget.TEXT_MAX_OUTPUT_TOKENS, rel=0.02)


def test_thinking_model_still_cannot_exceed_the_ceiling(monkeypatch):
    from app.ai import budget, llm
    monkeypatch.setattr(llm, "CLAUDE_MODEL", "claude-opus-5")
    cap = budget.opus_output_cap(300.0, in_tokens=2000, tts_tier=None,
                                 mode_max=budget.mode_max_tokens("text"),
                                 model="claude-opus-5")
    from app.ai import costs
    spend = (costs.llm_cost("claude-opus-5", in_tok=2000)
             + costs.llm_cost("claude-opus-5", out_tok=cap))
    assert spend <= 300.0 + 1e-6


def test_opus_5_is_priced_and_not_guessed():
    from app.ai import costs
    assert costs.price("claude-opus-5")["in"] == 5.00
    assert costs.price("claude-opus-5")["out"] == 25.00
    assert costs.llm_cost("claude-opus-5", 1_000_000) == pytest.approx(45000)


def test_thinking_default_follows_the_model(monkeypatch):
    from app.ai import llm
    assert llm.thinks_by_default("claude-opus-4-5") is False
    assert llm.thinks_by_default("claude-opus-5") is True
    monkeypatch.setattr(llm, "CLAUDE_THINKING", "disabled")
    assert llm.thinks_by_default("claude-opus-5") is False


# ---------------- the answer comes back before the bookkeeping ----------

def test_bookkeeping_runs_after_the_answer_is_delivered(env, frozen):
    from app.ai import pipeline
    gem = FakeGemini()
    env.set_models(gem, FakeClaude())
    seen = {}

    def on_done(done, reply):
        # At SSE `done` time the memory update has not run yet...
        seen["flash_calls"] = [c["name"] for c in gem.calls]
        seen["traces"] = len(env.repo.traces)

    r = pipeline.run_query_nowait(UID, _session("te"), TE_Q,
                                  prechecked=env.flags, on_done=on_done)
    assert "memory" not in seen["flash_calls"]
    assert seen["traces"] == 0
    # ...and afterwards it has.
    r.wait(timeout=10)
    assert "memory" in [c["name"] for c in gem.calls]
    assert len(env.repo.traces) == 1
    assert _stage(r.trace, "memory")["cost_units"] > 0


def test_trace_latency_excludes_the_background_tail(env, frozen, monkeypatch):
    """A slow memory update must not show up as user-visible latency."""
    import time as _time

    from app.ai import memory, pipeline
    env.set_models(FakeGemini(), FakeClaude())
    real = memory.update

    def slow(**kw):
        _time.sleep(0.5)
        return real(**kw)

    monkeypatch.setattr(memory, "update", slow)
    t0 = _time.time()
    # `run_query` here is the conftest wrapper, which joins the tail.
    r = pipeline.run_query(UID, _session("te"), TE_Q, prechecked=env.flags)
    including_tail_ms = (_time.time() - t0) * 1000
    assert including_tail_ms >= 500          # the slow memory update did run
    assert r.trace["latency_ms"] < 400       # but the user never waited for it
    assert _stage(r.trace, "memory")         # and it is still in the trace


def test_tail_failure_never_loses_the_answer(env, frozen, monkeypatch):
    from app.ai import memory, pipeline
    env.set_models(FakeGemini(), FakeClaude())

    def boom(**kw):
        raise RuntimeError("firestore down")

    monkeypatch.setattr(memory, "update", boom)
    r = pipeline.run_query(UID, _session("te"), TE_Q, prechecked=env.flags)
    assert r.status == "ok" and r.reply
    assert r.charged_units == 1000


# ---------------- trace shape is still the contract's ----------------

def test_trace_still_matches_the_contract(env, frozen):
    from app.ai import pipeline
    env.set_models(FakeGemini(), FakeClaude())
    t = pipeline.run_query(UID, _session("te"), TE_Q, prechecked=env.flags).trace
    for key in ("trace_id", "uid", "session_id", "lang", "mode", "kind", "status",
                "question_chars", "created_at", "latency_ms", "stages",
                "cost_units", "charged_units", "error"):
        assert key in t, key
    assert [s["name"] for s in t["stages"]] == ["plan", "tools", "brief", "reason",
                                                "memory"]
    for s in t["stages"]:
        assert "latency_ms" in s and "cost_units" in s
    assert _stage(t, "reason")["cache_read_tok"] == 0
    assert "ttft_ms" in _stage(t, "reason")["detail"]


# ---------------- the stream must actually stream ----------------

def test_sse_is_not_gzipped_by_the_app_middleware(env, monkeypatch):
    """main.py wraps the app in GZipMiddleware. Starlette excludes
    text/event-stream, but a downgrade of that middleware would buffer the
    whole answer and destroy time-to-first-token — so pin the behaviour."""
    from fastapi import FastAPI
    from fastapi.middleware.gzip import GZipMiddleware
    from fastapi.testclient import TestClient

    from app import routes_ai, store
    from app.ai import repo

    env.set_models(FakeGemini(), FakeClaude())
    sessions = {"s1": {"id": "s1", "uid": UID, "profile_id": "p1", "lang": "te",
                       "mode": "text", "summary": "", "free_turns": 0}}
    monkeypatch.setattr(repo, "get_session", lambda sid: sessions.get(sid))
    monkeypatch.setattr(store, "get_user",
                        lambda uid: {"uid": uid, "lang": "te", "balance_units": 5000})
    monkeypatch.setattr(store, "get_flags", lambda: dict(__import__(
        "ai_fakes").FLAGS))
    app = FastAPI()
    app.add_middleware(GZipMiddleware, minimum_size=1024)   # as in main.py
    app.include_router(routes_ai.router)
    c = TestClient(app)
    c.headers.update({"Authorization": "Bearer " + store.issue_token(UID)})

    with c.stream("POST", "/api/sessions/s1/ask/stream",
                  json={"text": TE_Q},
                  headers={"Accept-Encoding": "gzip"}) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        assert "gzip" not in r.headers.get("content-encoding", "")
        chunks = [line for line in r.iter_lines() if line]
    deltas = [l for l in chunks if l.startswith("event: delta")]
    assert len(deltas) > 1, "the answer arrived in one piece, not as a stream"
    assert chunks[-2].startswith("event: done") or "done" in chunks[-2]


@pytest.mark.parametrize("lang,text", [
    ("en", "I don't want to live anymore"),
    ("en", "I am going to kill myself tonight"),
    ("te", "నాకు బతకాలని లేదు, చనిపోతే బాగుంటుంది"),
    ("hi", "मैं मरना चाहता हूँ, जीना नहीं चाहता"),
    ("ta", "எனக்கு தற்கொலை எண்ணம் வருகிறது"),
    ("kn", "ನನಗೆ ಸಾಯಬೇಕು ಅನಿಸುತ್ತದೆ"),
    ("ml", "എനിക്ക് ജീവിക്കാൻ തോന്നുന്നില്ല"),
])
def test_distress_gets_a_helpline_free_and_without_a_model_call(env, lang, text):
    """A person in crisis must get Tele-MANAS 14416, in their language, with
    nothing charged and no model asked to handle it."""
    from app.ai import pipeline
    r = pipeline.run_query("u-distress", _session(lang), text, prechecked=env.flags)
    assert r.status == "refused" and r.charged_units == 0
    assert "14416" in r.reply and "112" in r.reply
    assert r.trace["cost_units"] == 0, "no model call may happen on this path"


def test_ordinary_questions_are_not_treated_as_distress():
    from app import guard
    for ok in ["When will I marry?", "నా ఉద్యోగం ఎప్పుడు మారుతుంది?",
               "Will my father's health improve?", "मेरी शादी कब होगी?",
               "Is there any danger to my career?"]:
        assert not guard.looks_like_distress(ok), ok
