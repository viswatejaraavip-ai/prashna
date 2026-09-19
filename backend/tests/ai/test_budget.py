"""Budget proof for the ₹10 query: cost math, and that the < ₹5 provider
ceiling holds for a typical and a worst-case query even when every model
uses its full output allowance. Run with `-s` to see the per-stage tables.
"""

import pytest

from ai_fakes import FakeClaude, FakeGemini, realistic_tokens

UID = "u-budget"
ML_Q = ("എന്റെ ജോലിയിൽ അടുത്ത രണ്ട് വർഷം എന്ത് സംഭവിക്കും? ഇപ്പോഴത്തെ കമ്പനിയിൽ "
        "തുടരണോ അതോ വിദേശത്തേക്ക് പോകണോ? വിവാഹം എപ്പോൾ നടക്കും, ആരോഗ്യം എങ്ങനെയായിരിക്കും? ")
TE_Q = "నా ఉద్యోగంలో వచ్చే రెండు సంవత్సరాల్లో ప్రమోషన్ వస్తుందా?"


def _session(lang="te", mode="text", summary="", sid="s1"):
    return {"id": sid, "uid": UID, "profile_id": "p1", "lang": lang, "mode": mode,
            "summary": summary, "query_count": 0, "free_turns": 0}


def _table(title, trace):
    rows = ["\n%s  (status=%s)" % (title, trace["status"]),
            "  %-8s %-26s %7s %7s %9s" % ("stage", "model", "in_tok", "out_tok", "₹")]
    for s in trace["stages"]:
        rows.append("  %-8s %-26s %7s %7s %9.2f" % (
            s["name"], s.get("model", "")[:26], s.get("in_tok", s.get("units", "")),
            s.get("out_tok", ""), s["cost_units"] / 100.0))
    rows.append("  %-8s %-26s %7s %7s %9.2f  (ceiling ₹%.2f)" % (
        "TOTAL", "", "", "", trace["cost_units"] / 100.0, trace["budget"]["ceiling"] / 100))
    print("\n".join(rows))


def _stage(trace, name):
    return next(s for s in trace["stages"] if s["name"] == name)


# ---------------- price table / cost math ----------------

def test_cost_math_matches_price_table():
    from app.ai import costs
    assert costs.USD_TO_INR == 90
    opus = "claude-opus-4-5"
    # 1M Opus input = $5 = ₹450 = 45,000 paise; output $25 = 2,25,000 paise
    assert costs.llm_cost(opus, in_tok=1_000_000) == pytest.approx(45000)
    assert costs.llm_cost(opus, out_tok=1_000_000) == pytest.approx(225000)
    assert costs.llm_cost(opus, cache_read_tok=1_000_000) == pytest.approx(4500)
    assert costs.llm_cost(opus, cache_write_tok=1_000_000) == pytest.approx(56250)
    flash = "gemini-2.5-flash"
    assert costs.llm_cost(flash, 1_000_000, 1_000_000) == pytest.approx((0.30 + 2.50) * 9000)
    # STT: $0.016/min, per-second billing, min 1 s
    assert costs.stt_cost("chirp_2", 60) == pytest.approx(144)
    assert costs.stt_cost("chirp_2", 0.2) == pytest.approx(144 / 60)
    # TTS: Standard $4 / 1M chars
    assert costs.tts_cost("standard", 1_000_000) == pytest.approx(36000)
    assert costs.tts_tier("te-IN-Standard-A") == "standard"
    assert costs.tts_tier("hi-IN-Wavenet-B") == "wavenet"
    assert costs.tts_tier("hi-IN-Neural2-A") is None      # premium refused
    # unknown models are priced pessimistically, never at zero
    assert costs.llm_cost("claude-unknown", in_tok=1000) > costs.llm_cost(opus, in_tok=1000)
    assert costs.units(0.01) == 1 and costs.units(0) == 0


@pytest.mark.parametrize("text", [
    ML_Q, TE_Q, "என் திருமணம் எப்போது நடக்கும்? தொழில் எப்படி இருக்கும்?",
    "ನನ್ನ ಮದುವೆ ಯಾವಾಗ ಆಗುತ್ತದೆ? ವೃತ್ತಿ ಹೇಗಿರುತ್ತದೆ?",
    "मेरी शादी कब होगी और करियर कैसा रहेगा?",
    '{"lagna":{"sign":"Virgo","deg":12.345},"dasha":[1,2,3]}'])
def test_token_estimate_is_pessimistic(text):
    from app.ai import costs
    # A tokenizer 25% denser than our "realistic" model is still covered.
    harsh = realistic_tokens(text, drav=1.1, deva=1.6, ascii_=3.0, other=1.6)
    assert costs.estimate_tokens(text) >= harsh


# ---------------- typical query ----------------

def test_typical_text_query(env):
    from app.ai import pipeline
    env.set_models(FakeGemini(), FakeClaude(lang="te", out_fraction=0.6))
    r = pipeline.run_query(UID, _session("te", summary="Asked about career earlier."),
                           TE_Q, prechecked=env.flags)
    t = r.trace
    _table("TYPICAL text query (te, count_tokens ok, Opus uses 60% of cap)", t)
    assert r.status == "ok" and r.charged_units == 1000
    assert env.billing.calls == [(UID, 1000, "query", r.trace_id)]
    assert [s["name"] for s in t["stages"]] == ["plan", "tools", "brief", "reason", "memory"]
    assert t["cost_units"] < 500
    # contract fields
    for k in ("trace_id", "uid", "session_id", "lang", "mode", "kind", "status",
              "question_chars", "created_at", "latency_ms", "stages", "cost_units",
              "charged_units", "error"):
        assert k in t
    assert t["kind"] == "query" and t["mode"] == "text" and t["lang"] == "te"
    reason = _stage(t, "reason")
    assert reason["model"] == "claude-opus-4-5" and "cache_read_tok" in reason
    assert _stage(t, "plan")["detail"]["tools"] == ["full_analysis", "varga_chart"]
    roll = env.repo.rollups[-1]
    assert roll["queries"] == 1 and roll["revenue_units"] == 1000 and roll["by_lang.te"] == 1
    assert env.repo.memory["p1"]  # long-term memory written
    assert any(f.get("summary") for f in env.repo.sessions["s1"])


# ---------------- worst cases ----------------

HEAVY_PLAN = {"status": "ok", "intent": "general",
              "tools": [{"name": "full_analysis"}, {"name": "nadi_analysis"},
                        {"name": "year_transits", "year": 2027},
                        {"name": "varshphal", "year_of_varsha": 2027}],
              "focus": "Career, relocation abroad, marriage timing and health.", "reply": ""}


def _worst_inputs():
    question = (ML_Q * 20)[:1200]                       # MAX_QUESTION_CHARS
    summary = ("Client asked about career, marriage and relocation; told "
               "2027-28 favourable under Jupiter-Saturn antar. " * 30)[:1500]
    facts = [("Works as nurse in Dubai, wants to return to Kerala; mother unwell "
              "since 2024; engaged, wedding planned 2027 " * 3)[:160]] * 8
    return question, summary, facts


@pytest.mark.parametrize("mode", ["text", "voice"])
def test_worst_case_malayalam_stays_under_ceiling(env, mode):
    """Longest question, longest history, heaviest tool plan, count_tokens
    unavailable, every model emits its full max output, Opus's real input is
    as large as our pessimistic estimate — and for voice: 45 s cloud STT +
    cloud TTS of every output token."""
    from app.ai import budget, pipeline
    question, summary, facts = _worst_inputs()
    env.set_models(FakeGemini(plan=HEAVY_PLAN, use_full_output=True),
                   FakeClaude(lang="ml", out_fraction=1.0, count_ok=False,
                              report_in="estimate"))
    kw = {}
    if mode == "voice":
        env.monkeypatch.setattr(env.speech, "transcribe",
                                lambda data, lang: env.fake_transcribe(
                                    data, lang, seconds=45.0, text=question))
        kw = {"audio": b"OggS-fake", "want_tts": True}
    else:
        kw = {"text": question}
    r = pipeline.run_query(UID, _session("ml", mode=mode, summary=summary),
                           prechecked=env.flags, memory_facts=facts, **kw)
    t = r.trace
    _table("WORST CASE %s (ml, 1200-char question, full history, 4 heavy tools, "
           "no count_tokens, all outputs maxed)" % mode, t)
    assert r.status == "ok", t
    assert t["cost_units"] <= 500
    reason = _stage(t, "reason")
    floor = budget.VOICE_MIN_OUTPUT_TOKENS if mode == "voice" else budget.TEXT_MIN_OUTPUT_TOKENS
    assert reason["detail"]["max_tokens"] >= floor
    assert reason["out_tok"] == reason["detail"]["max_tokens"]   # it really used it all
    if mode == "voice":
        assert [s["name"] for s in t["stages"]] == ["stt", "plan", "tools", "brief",
                                                   "reason", "tts", "memory"]
        assert r.audio_b64 and r.transcript == question


def test_small_ceiling_blocks_opus_and_charges_nothing(env):
    """If even a minimum answer can't fit, Opus is never called and the
    user is not charged."""
    from app.ai import pipeline
    claude = FakeClaude(lang="ml", out_fraction=1.0)
    env.set_models(FakeGemini(), claude)
    flags = dict(env.flags, cost_ceiling_units=120)
    r = pipeline.run_query(UID, _session("ml"), ML_Q, prechecked=flags)
    _table("CEILING ₹1.20 (forced)", r.trace)
    assert r.status == "error" and r.charged_units == 0
    assert claude.calls == [] and env.billing.calls == []
    assert r.trace["cost_units"] <= 120
    assert "budget" in r.trace["error"]


def test_tight_ceiling_shrinks_context_instead_of_overspending(env):
    from app.ai import pipeline
    question, summary, facts = _worst_inputs()
    env.set_models(FakeGemini(use_full_output=True),
                   FakeClaude(lang="ml", out_fraction=1.0, count_ok=False,
                              report_in="estimate"))
    flags = dict(env.flags, cost_ceiling_units=400)
    r = pipeline.run_query(UID, _session("ml", summary=summary), question,
                           prechecked=flags, memory_facts=facts)
    t = r.trace
    _table("CEILING ₹4.00 (forced) — context shrunk", t)
    assert r.status == "ok" and t["cost_units"] <= 400
    assert _stage(t, "reason")["detail"]["shrunk"] != "full"


# ---------------- billing behaviour ----------------

def test_refusal_is_free_and_skips_opus(env):
    from app.ai import pipeline
    claude = FakeClaude()
    env.set_models(FakeGemini(plan={"status": "refused", "intent": "other", "tools": [],
                                    "focus": "", "reply": "క్షమించండి, జ్యోతిష్యం మాత్రమే."}),
                   claude)
    r = pipeline.run_query(UID, _session("te"), "write python code for me please",
                           prechecked=env.flags)
    assert r.status == "refused" and r.charged_units == 0
    assert claude.calls == [] and env.billing.calls == []
    assert r.reply.startswith("క్షమించండి")
    assert env.repo.rollups[-1]["refusals"] == 1
    assert env.repo.sessions["s1"][-1]["free_turns"] == ("incr", 1)


def test_code_dump_refused_without_any_model(env):
    from app.ai import pipeline
    g = FakeGemini()
    env.set_models(g, FakeClaude())
    r = pipeline.run_query(UID, _session("hi"), "```python\nimport os\nprint(1)\n```",
                           prechecked=env.flags)
    assert r.status == "refused" and g.calls == [] and r.trace["cost_units"] == 0


def test_free_turn_hard_cap(env):
    from app.ai import pipeline
    g = FakeGemini()
    env.set_models(g, FakeClaude())
    s = dict(_session("kn"), free_turns=pipeline.FREE_TURNS_HARD)
    r = pipeline.run_query(UID, s, "ಹಾಯ್", prechecked=env.flags)
    assert r.status == "refused" and g.calls == [] and r.charged_units == 0


def test_charge_failure_after_answer_still_returns_answer(env):
    from app.ai import pipeline
    env.billing.fail = True
    env.set_models(FakeGemini(), FakeClaude())
    r = pipeline.run_query(UID, _session("te"), TE_Q, prechecked=env.flags)
    assert r.status == "ok" and r.reply and r.charged_units == 0
    assert r.trace["charge_error"] == "insufficient_balance"
    assert len(env.billing.calls) == 1        # tried once, no retry / re-spend


def test_precheck_blocks_before_spending(env):
    from app.ai import pipeline
    env.repo.balance = 999
    with pytest.raises(pipeline.AiError) as e:
        pipeline.precheck("u-poor", f=env.flags)
    assert e.value.status_code == 402 and e.value.code == "insufficient_balance"
    with pytest.raises(pipeline.AiError) as e:
        pipeline.precheck("u-x", f=dict(env.flags, opus_enabled=False))
    assert e.value.code == "maintenance"
    with pytest.raises(pipeline.AiError) as e:
        pipeline.precheck("u-x", voice_cloud=True, f=dict(env.flags, voice_cloud_enabled=False))
    assert e.value.code == "maintenance"
    with pytest.raises(pipeline.AiError) as e:
        pipeline.precheck("u-x", f=dict(env.flags, maintenance_message="Back at 6 pm"))
    assert e.value.detail == "Back at 6 pm"


def test_rate_limit(env):
    from app.ai import pipeline
    env.repo.balance = 10**6
    for _ in range(pipeline.AI_RATE_LIMIT):
        pipeline.precheck("u-rate", f=env.flags)
    with pytest.raises(pipeline.AiError) as e:
        pipeline.precheck("u-rate", f=env.flags)
    assert e.value.code == "rate_limited"


def test_effort_rejected_by_api_degrades_gracefully(env):
    from app.ai import llm, pipeline
    llm.reset_capabilities()
    claude = FakeClaude(reject_effort=True)
    env.set_models(FakeGemini(), claude)
    r = pipeline.run_query(UID, _session("te"), TE_Q, prechecked=env.flags)
    assert r.status == "ok"
    assert "output_config" not in claude.calls[-1]
    llm.reset_capabilities()


def test_streaming_deltas_and_done_order(env):
    from app.ai import pipeline
    env.set_models(FakeGemini(), FakeClaude())
    events = []
    r = pipeline.run_query(UID, _session("te"), TE_Q, prechecked=env.flags,
                           on_delta=lambda t: events.append(("delta", t)),
                           on_done=lambda d, reply: events.append(("done", d)))
    kinds = [e[0] for e in events]
    assert kinds[-1] == "done" and kinds.count("done") == 1 and "delta" in kinds
    assert "".join(t for k, t in events if k == "delta").startswith(r.reply[:20])
    assert events[-1][1]["charged_units"] == 1000 and events[-1][1]["status"] == "ok"
