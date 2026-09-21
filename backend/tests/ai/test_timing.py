"""Dating a past event from the chart, not from today.

The live evaluation (backend/evals/RESULTS.md) found two accuracy defects
that share a root: the agent was never given the client's birth date, and
`executor.prune()` windowed every dated period list around *today*, so a
question about 2015 arrived with no 2015 in it. Twelve of the twenty-three
past events it dated landed within five years of today although only one
truly did; a client born in 1993 was told his career began in 2004 (age 11),
and answers invented mahadashas to fill the gaps the window had made.

What these tests pin down:

* the client's date of birth and age today reach BOTH models;
* a past-tense question is given the whole vimshottari ladder — mahadashas
  AND their antardashas — including the years the question is about;
* nothing about that path breaks the ₹5 per-query ceiling;
* an answer that dates something before birth, or at an age nobody reaches,
  is detected for free and recorded in the trace.
"""

from datetime import date, datetime

import pytest

from ai_fakes import FakeClaude, FakeGemini

UID = "u-timing"
FROZEN = datetime.fromisoformat("2026-09-20T14:35:00+05:30")

# ai_fakes.PROFILE is born 1990-05-17, so "today" above makes the client 36.
BORN_YEAR, AGE_TODAY = 1990, 36

TE_PAST_Q = "నేను మొదటిసారి విదేశాలకు ఎప్పుడు వెళ్ళాను? సంవత్సరం చెప్పండి."

PAST_PLAN = {"status": "ok", "intent": "travel", "timeframe": "past",
             "tools": [{"name": "full_analysis"}],
             "focus": "The year the client first travelled abroad.", "reply": ""}
FUTURE_PLAN = dict(PAST_PLAN, timeframe="future",
                   focus="When the client will marry.")


def _session(lang="te", mode="text", sid="s1"):
    return {"id": sid, "uid": UID, "profile_id": "p1", "lang": lang, "mode": mode,
            "summary": "", "query_count": 0, "free_turns": 0}


def _profile(born="1991-08-14", **kw):
    p = {"name": "Client A", "relation": "other", "time_known": True,
         "birth": {"date": born, "time": "15:45", "tz": "Asia/Kolkata",
                   "lat": 17.3850, "lon": 78.4867, "place": "Hyderabad"}}
    p.update(kw)
    return p


@pytest.fixture
def frozen():
    from app.ai import clock
    clock.freeze(FROZEN)
    yield clock
    clock.freeze(None)


def _brief_call(gem):
    """The system+user text of the Flash brief call."""
    return next(t for t in gem.sent_text if "FACTS BRIEF PROTOCOL" in t)


# ---------------- the models are told who they are reading for ----------

def test_age_arithmetic_is_the_one_a_person_uses(frozen):
    from app.ai import dates
    born = date(1991, 8, 14)
    assert dates.age_on(born, date(2026, 9, 20)) == 35
    assert dates.age_on(born, date(2026, 8, 13)) == 34     # birthday not reached
    assert dates.age_on(born, date(2026, 8, 14)) == 35
    assert dates.age_today(_profile()) == 35


def test_reasoner_is_given_the_birth_date_and_the_age_today(frozen):
    """The system prompt promises this fact; the user block must carry it."""
    from app.ai import reasoner
    plan = reasoner.fit(lang="te", mode="text", question=TE_PAST_Q,
                        brief="- Lagna Virgo.", summary="", memory=[],
                        profile=_profile(), remaining_paise=400.0, tts_tier=None)
    user = plan["messages"][0]["content"]
    assert "Client born: 14 August 1991 (1991-08-14); age today 35." in user
    # ...right next to "Now:", because the pair is what makes an age computable.
    assert user.index("Client born:") < user.index("Answer language:")
    assert user.startswith("Now: ")


def test_reasoner_is_told_to_state_the_age_with_every_date(frozen):
    from app.ai import reasoner
    p = reasoner.SYSTEM_PROMPT
    assert "Client born:" in p
    assert "age" in p and "(age" in p
    # and that a past question is not answered from the period running now
    assert "PAST TENSE" in p and "running now" in p


def test_a_profile_without_a_birth_date_simply_omits_the_line(frozen):
    from app.ai import dates, reasoner
    blank = {"name": "X", "relation": "self", "birth": {}}
    assert dates.born_line(blank) == ""
    plan = reasoner.fit(lang="en", mode="text", question="When?", brief="-",
                        summary="", memory=[], profile=blank,
                        remaining_paise=400.0, tts_tier=None)
    assert "Client born:" not in plan["messages"][0]["content"]


def test_the_brief_is_given_the_birth_date_and_the_timeframe(frozen, env):
    from app.ai import pipeline
    gem = FakeGemini(plan=PAST_PLAN)
    env.set_models(gem, FakeClaude())
    pipeline.run_query(UID, _session("te"), TE_PAST_Q, prechecked=env.flags)
    sent = _brief_call(gem)
    assert "Client born: 17 May 1990 (1990-05-17); age today 36." in sent
    assert "Timeframe: past" in sent
    # and the brief protocol asks for the age beside every period it lists
    assert "age range" in sent


# ---------------- a past question gets the whole ladder -----------------

def test_a_past_question_is_planned_with_the_life_dasha_ladder():
    """`full_analysis` only carries the CURRENT mahadasha's antardashas, so a
    past-tense plan is deterministically given `dasha_periods` as well."""
    from app.ai import planner
    p = planner.validate(dict(PAST_PLAN))
    assert {"name": "dasha_periods", "levels": 2, "system": "vimshottari"} in p["tools"]
    # ...and it is not added twice, nor to questions that are not about the past
    again = planner.validate(dict(PAST_PLAN, tools=p["tools"]))
    assert [t["name"] for t in again["tools"]].count("dasha_periods") == 1
    # A ladder the planner asked for itself is upgraded to sub-periods: a
    # mahadasha alone is an eighteen-year window, which dates nothing.
    shallow = planner.validate(dict(PAST_PLAN, tools=[
        {"name": "dasha_periods", "levels": 1, "system": "yogini"}]))
    assert shallow["tools"] == [{"name": "dasha_periods", "levels": 2,
                                 "system": "yogini"}]
    assert "dasha_periods" not in [t["name"]
                                   for t in planner.validate(dict(FUTURE_PLAN))["tools"]]


def test_the_ladder_is_not_forced_on_a_plan_with_no_natal_chart_in_it():
    from app.ai import planner
    p = planner.validate(dict(PAST_PLAN, intent="festival",
                              tools=[{"name": "festival_calendar", "year": 2020}]))
    assert [t["name"] for t in p["tools"]] == ["festival_calendar"]


def test_past_pruning_keeps_the_period_the_question_is_about(frozen):
    """The regression from RESULTS.md: asked in 2026 about a year in the
    1990s, the default window keeps two expired periods, so the period that
    was actually running then is simply absent from the brief."""
    from app.ai import executor
    # A real vimshottari ladder: nine mahadashas, birth to death.
    bounds = [1987, 1997, 2004, 2022, 2038, 2057, 2074, 2081, 2101, 2107]
    raw = '{"mahadashas":[%s]}' % ",".join(
        '{"lord":"L%d","start":"%d-01-01","end":"%d-01-01"}' % (i, a, b)
        for i, (a, b) in enumerate(zip(bounds, bounds[1:])))
    # Default: two expired periods, so the first decade of the life is gone.
    assert '"L0"' not in executor.prune(raw)                  # 1987-97: dropped
    kept = executor.prune(raw, timeframe="past")
    assert '"L0"' in kept and '"L1"' in kept and '"L2"' in kept


def test_the_real_engine_gives_a_past_question_the_antardasha_it_needs(frozen):
    """End to end on the evaluation's own chart (14 August 1991, Hyderabad): the
    answer to "when did my career start" is inside Rahu-Venus 2016-04 ..
    2019-04, and nothing but the whole ladder contains it."""
    import json

    from app import agent
    from app.ai import executor
    birth = {"year": 1993, "month": 5, "day": 22, "hour": 15, "minute": 45,
             "latitude": 17.3850, "longitude": 78.4867, "tz_name": "Asia/Kolkata"}
    raw = executor._compact(agent.execute_tool(
        "dasha_periods", dict(birth, levels=2, system="vimshottari")))

    def covers(pruned, when):
        for md in json.loads(pruned)["mahadashas"]:
            for ad in md.get("antardashas", []):
                if ad["start"][:10] <= when <= ad["end"][:10]:
                    return "%s-%s" % (md["lord"], ad["lord"])
        return None

    assert covers(executor.prune(raw), "2017-06-15") is None
    assert covers(executor.prune(raw, timeframe="past"), "2017-06-15") == "Rahu-Venus"
    assert covers(executor.prune(raw, timeframe="past"), "2015-06-15") == "Rahu-Ketu"


def test_the_ladder_is_handed_over_verbatim_with_ages(frozen):
    """Flash was measured cutting a ninety-year ladder off in the 2000s, and
    the astrologer then correctly reported it had no data for the years
    asked about. So the ladder is formatted here, not summarised."""
    from app.ai import executor
    raw = ('{"system":"Vimshottari","mahadashas":['
           '{"lord":"Mars","start":"1997-10-04","end":"2004-10-04",'
           ' "antardashas":[{"lord":"Mars","start":"1997-10-04"},'
           '                {"lord":"Rahu","start":"1998-03-01"}]},'
           '{"lord":"Rahu","start":"2004-10-04","end":"2022-10-04",'
           ' "antardashas":[{"lord":"Ketu","start":"2015-04-01"},'
           '                {"lord":"Venus","start":"2016-04-01"}]}]}')
    out = executor.life_ladder(raw, _profile())
    assert "Rahu 2004-10..2022-10 [age 13..31]" in out
    assert "Ketu 2015-04 [23]" in out and "Venus 2016-04 [24]" in out
    # and it says what its own silence means, so a gap is not filled in
    assert "no period for" in out
    assert executor.life_ladder("not json", _profile()) == ""
    assert executor.life_ladder('{"mahadashas":[]}', _profile()) == ""


def test_periods_that_start_before_the_client_did_are_labelled(frozen):
    """Vimshottari starts at the balance of the birth nakshatra, so the first
    mahadasha opens before the birth. An age of -6 would be nonsense."""
    from app.ai import executor
    raw = ('{"mahadashas":[{"lord":"Moon","start":"1987-10-05","end":"1997-10-04",'
           '"antardashas":[{"lord":"Moon","start":"1987-10-05"}]}]}')
    out = executor.life_ladder(raw, _profile())
    assert "before birth" in out and "-6" not in out


def test_the_ladder_does_not_go_through_flash(frozen, env):
    from app.ai import pipeline
    gem, claude = FakeGemini(plan=PAST_PLAN), FakeClaude()
    env.set_models(gem, claude)
    r = pipeline.run_query(UID, _session("te"), TE_PAST_Q, prechecked=env.flags)
    assert r.status == "ok"
    # Flash condenses everything EXCEPT the ladder...
    assert '"antardashas"' not in _brief_call(gem)
    # ...which reaches Opus verbatim, as text, with the ages worked out here.
    opus = claude.calls[0]["messages"][0]["content"]
    assert "LIFE DASHA LADDER" in opus and "[age " in opus
    brief = next(s for s in r.trace["stages"] if s["name"] == "brief")
    assert brief["detail"]["ladder_chars"] > 0


def test_the_ladder_alone_is_still_a_usable_brief(frozen, env):
    """A narrow question the planner answers with dasha_periods and nothing
    else leaves the Flash bundle empty once the ladder is taken out."""
    from app.ai import pipeline
    only = dict(PAST_PLAN, tools=[{"name": "dasha_periods", "levels": 2,
                                   "system": "vimshottari"}])
    gem, claude = FakeGemini(plan=only), FakeClaude()
    env.set_models(gem, claude)
    r = pipeline.run_query(UID, _session("te"), TE_PAST_Q, prechecked=env.flags)
    assert r.status == "ok"
    assert "LIFE DASHA LADDER" in claude.calls[0]["messages"][0]["content"]


def test_a_past_question_reaches_the_engine_with_the_ladder(frozen, env):
    from app.ai import pipeline
    gem = FakeGemini(plan=PAST_PLAN)
    env.set_models(gem, FakeClaude())
    r = pipeline.run_query(UID, _session("te"), TE_PAST_Q, prechecked=env.flags)
    assert r.status == "ok"
    tools = next(s for s in r.trace["stages"] if s["name"] == "tools")
    assert "dasha_periods" in tools["detail"]["tools"]
    assert not tools["detail"]["errors"]
    assert r.trace["timeframe"] == "past"


# ---------------- and it still fits under the ₹5 ceiling ----------------

def test_the_life_ladder_does_not_break_the_cost_ceiling(frozen, env):
    """Worst case on the widest past-tense plan: every model call spends its
    whole output cap and the input is as large as our pessimistic estimate."""
    from app.ai import pipeline
    wide = dict(PAST_PLAN, tools=[{"name": "full_analysis"},
                                  {"name": "varga_chart", "varga": "D10"}])
    env.set_models(FakeGemini(plan=wide, use_full_output=True),
                   FakeClaude(out_fraction=1.0, count_ok=False, report_in="estimate"))
    r = pipeline.run_query(UID, _session("te"), TE_PAST_Q,
                           prechecked=dict(env.flags, cost_ceiling_units=500))
    assert r.trace["cost_units"] <= 500
    assert r.status == "ok", "the widest past-tense query must still fit"


# ---------------- the answer is checked against the client's life -------

CLEAN = "మీ ఉద్యోగ జీవితం 2017 (వయస్సు 24) లో ప్రారంభమైంది."
BEFORE_BIRTH = "ఈ జాతకంలో వివాహం 1985 లో జరిగింది."
TOO_OLD = "This native married in 2021, in the Venus mahadasha."


def test_a_year_before_birth_is_caught():
    from app.ai import dates
    bad = dates.implausible_dates(BEFORE_BIRTH, _profile())
    assert [(b["year"], b["why"]) for b in bad] == [(1985, "before_birth")]


def test_an_impossible_age_is_caught():
    """The Indira Gandhi case: born 1917, told she married in 2021."""
    from app.ai import dates
    bad = dates.implausible_dates(TOO_OLD, _profile(born="1917-11-19"))
    assert [(b["year"], b["age"], b["why"]) for b in bad] == [
        (2021, 104, "implausible_age")]


def test_a_period_that_legitimately_starts_before_birth_is_not_a_defect():
    """Vimshottari opens at the balance of the birth nakshatra and Kalachakra
    earlier still, so quoting "Kalachakra 1985-2006" for a 1993 chart is the
    engine's own fact. Dating the marriage itself to 1985 is not."""
    from app.ai import dates
    period = "కాలచక్ర దశ కర్కాటక మహాదశ (1985-2006) నడిచింది."
    assert dates.implausible_dates(period, _profile()) == []
    assert dates.implausible_dates("వివాహం 1985 లో జరిగింది.", _profile())


def test_a_plausible_answer_is_not_flagged():
    from app.ai import dates
    assert dates.implausible_dates(CLEAN, _profile()) == []
    assert dates.implausible_dates(TOO_OLD, _profile(born="1988-11-05")) == []
    assert dates.implausible_dates("no dates here at all", _profile()) == []
    assert dates.implausible_dates(CLEAN, {"birth": {}}) == []


def test_years_are_found_in_every_script_the_app_speaks():
    from app.ai import dates
    assert dates.years_in("विवाह २०२१ में हुआ") == [2021]        # Devanagari
    assert dates.years_in("౨౦౧౭ సంవత్సరం") == [2017]             # Telugu
    assert dates.years_in("2017 (వయస్సు 24), 2017 మళ్ళీ") == [2017]
    assert dates.years_in("D-10, 24, 1.5") == []                 # not years


class _ClaudeSaying(FakeClaude):
    """Opus with the words put in its mouth, so a defective answer can be
    driven through the pipeline exactly as a real one would be."""

    def __init__(self, text, **kw):
        super().__init__(**kw)
        self.text = text

    def _stream(self, kw):
        import ai_fakes
        return ai_fakes._Stream(self.text, ai_fakes._Final(
            self.text, self._in(kw["system"], kw["messages"]),
            max(1, len(self.text) // 3), "end_turn"))


def test_the_pipeline_flags_a_reply_that_predates_the_client(frozen, env):
    """ai_fakes.PROFILE was born in 1990, so an answer dating his career to
    1974 is impossible whatever the chart says."""
    from app.ai import pipeline
    bad = "ఈ జాతకంలో ఉద్యోగ జీవితం 1974 లో మొదలైంది. " * 20
    env.set_models(FakeGemini(plan=PAST_PLAN), _ClaudeSaying(bad))
    r = pipeline.run_query(UID, _session("te"), TE_PAST_Q, prechecked=env.flags)
    assert r.status == "ok"                      # detected, never withheld
    assert r.trace["date_check"]["bad"] == [{"year": 1974, "age": -16,
                                             "why": "before_birth"}]
    assert r.trace["date_check"]["born"] == "1990-05-17"
    assert any(roll.get("impossible_dates") for roll in env.repo.rollups)


def test_a_sound_reply_leaves_no_date_check_in_the_trace(frozen, env):
    from app.ai import pipeline
    good = "ఈ జాతకంలో ఉద్యోగ జీవితం 2017 (వయస్సు 27) లో మొదలైంది. " * 20
    env.set_models(FakeGemini(plan=PAST_PLAN), _ClaudeSaying(good))
    r = pipeline.run_query(UID, _session("te"), TE_PAST_Q, prechecked=env.flags)
    assert r.status == "ok"
    assert "date_check" not in r.trace
    assert not any(roll.get("impossible_dates") for roll in env.repo.rollups)


# ---------------- nothing may be asserted beyond the brief --------------

def test_the_reasoner_may_not_fill_a_gap_from_memory():
    """Defect 2: a third of answers carried a placement or dasha the engine
    disagrees with, including mahadashas invented for years the brief did not
    cover. The prompt has to make the honest answer the easy one."""
    from app.ai import reasoner
    p = reasoner.SYSTEM_PROMPT
    assert "not cover those years" in p          # the honest-gap sentence
    assert "never recompute a period" in p
    assert "invented mahadasha" in p


def test_the_brief_may_not_invent_a_period_either():
    from app.ai import executor
    s = executor.BRIEF_SYSTEM
    assert "not in the raw JSON" in s
    assert "no data for" in s
    assert "Timeframe: past" in s


def test_a_ladder_we_cannot_format_is_left_in_the_brief(frozen, env, monkeypatch):
    """The ladder is pulled out of the Flash bundle before the bundle is
    condensed. If it then turns out not to be formattable — an engine error
    string, a system whose output has another shape — the tool's output must
    go back, not vanish from the brief entirely."""
    from app.ai import executor, pipeline
    only = dict(PAST_PLAN, tools=[{"name": "dasha_periods", "levels": 2,
                                   "system": "vimshottari"},
                                  {"name": "full_analysis"}])
    monkeypatch.setattr(executor, "life_ladder", lambda *a, **k: "")
    gem, claude = FakeGemini(plan=only), FakeClaude()
    env.set_models(gem, claude)
    r = pipeline.run_query(UID, _session("te"), TE_PAST_Q, prechecked=env.flags)
    assert r.status == "ok"
    sent = _brief_call(gem)
    assert "LIFE DASHA LADDER" not in sent
    assert '"mahadashas"' in sent          # the periods are still in front of Flash
