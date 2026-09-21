"""The chart reaches the astrologer as engine values, not as a paraphrase.

The evaluation (backend/evals/RESULTS.md) fixed one half of the grounding
defect and left the other: dasha periods were handed over verbatim, but where
the planets ARE still reached the reasoner only inside Flash's prose summary,
and answers kept contradicting the engine about it — Mercury placed in the
2nd when the engine says the 3rd, Mars in the 5th vs the 9th.

It also found the model constructing a dasha range wrongly when it was given
only the start of each sub-period: "Rahu-Saturn 2014-02 to 2016-12" for a
period the engine puts at 2009-11..2012-09, with the ladder in the same
prompt. Both are now copied rather than computed.
"""

import json

import pytest

from ai_fakes import FakeClaude, FakeGemini

UID = "u-ground"

RASI = {
    "ascendant": {"sign": "Virgo", "dms": "29°20'02\""},
    "planets": {
        "Sun": {"sign": "Taurus", "house_whole_sign": 9,
                "nakshatra": {"name": "Krittika", "pada": 4}, "retrograde": False},
        "Moon": {"sign": "Taurus", "house_whole_sign": 9,
                 "nakshatra": {"name": "Rohini", "pada": 3}, "retrograde": False},
        "Jupiter": {"sign": "Virgo", "house_whole_sign": 1,
                    "nakshatra": {"name": "Hasta", "pada": 1}, "retrograde": True},
    },
}


def _session(lang="te", sid="s1"):
    return {"id": sid, "uid": UID, "profile_id": "p1", "lang": lang, "mode": "text",
            "summary": "", "query_count": 0, "free_turns": 0}


# ---------------- the rasi table ----------------

def test_every_planet_is_listed_with_its_sign_house_and_nakshatra():
    from app.ai import executor
    out = executor.planet_table({"full_analysis": json.dumps({"rasi": RASI})})
    assert "Lagna: Virgo" in out
    assert "Sun: Taurus, house 9, Krittika-4" in out
    assert "Moon: Taurus, house 9, Rohini-3" in out
    assert "Jupiter: Virgo, house 1, Hasta-1, retrograde" in out


def test_the_table_is_found_whether_rasi_is_nested_or_not():
    from app.ai import executor
    nested = executor.planet_table({"full_analysis": json.dumps({"rasi": RASI})})
    flat = executor.planet_table({"birth_chart": json.dumps(RASI)})
    assert nested == flat and "Sun: Taurus" in flat


def test_planets_are_listed_in_the_traditional_order():
    from app.ai import executor
    out = executor.planet_table({"x": json.dumps(RASI)})
    names = [ln.split(":")[0] for ln in out.splitlines()[2:]]
    assert names == ["Sun", "Moon", "Jupiter"]      # Sun before Moon before Jupiter


def test_no_chart_in_the_bundle_yields_nothing_rather_than_a_guess():
    from app.ai import executor
    assert executor.planet_table({"transits": json.dumps({"planets": "x"})}) == ""
    assert executor.planet_table({"festival_calendar": "not json"}) == ""
    assert executor.planet_table({}) == ""


def test_the_table_is_small_enough_to_send_every_time():
    from app.ai import executor
    from app.ai import costs
    full = dict(RASI, planets={p: dict(RASI["planets"]["Sun"], sign="Leo")
                               for p in executor.PLANET_ORDER})
    out = executor.planet_table({"full_analysis": json.dumps(full)})
    assert costs.estimate_tokens(out) < 300


# ---------------- it actually reaches the model ----------------

def test_the_chart_table_reaches_opus_verbatim(env):
    from app.ai import pipeline
    gem, claude = FakeGemini(), FakeClaude()
    env.set_models(gem, claude)
    r = pipeline.run_query(UID, _session(), "నా కెరీర్ ఎలా ఉంటుంది?", prechecked=env.flags)
    assert r.status == "ok"
    sent = claude.calls[0]["messages"][0]["content"]
    assert "BIRTH CHART (rasi" in sent and "house" in sent
    brief = next(s for s in r.trace["stages"] if s["name"] == "brief")
    assert brief["detail"]["chart_chars"] > 0


def test_flash_is_told_not_to_restate_what_is_handed_over(env):
    from app.ai import pipeline
    gem = FakeGemini()
    env.set_models(gem, FakeClaude())
    pipeline.run_query(UID, _session(), "నా కెరీర్ ఎలా ఉంటుంది?", prechecked=env.flags)
    system = next(t for t in gem.sent_text if "FACTS BRIEF PROTOCOL" in t)
    assert "handed, verbatim, the rasi table" in system
    assert "restating either" in system


# ---------------- closed dasha intervals ----------------

def test_each_sub_period_carries_its_own_end_date():
    from app.ai import executor
    raw = json.dumps({"system": "Vimshottari", "mahadashas": [
        {"lord": "Rahu", "start": "2004-10-01", "end": "2022-10-01", "antardashas": [
            {"lord": "Saturn", "start": "2009-11-01", "end": "2012-09-01"},
            {"lord": "Mercury", "start": "2012-09-01", "end": "2015-04-01"}]}]})
    out = executor.life_ladder(raw, {"birth": {"date": "1991-08-14"}})
    # the range is given, not left to be inferred from the next entry
    assert "Saturn 2009-11..2012-09" in out
    assert "Mercury 2012-09..2015-04" in out
    # and the ages that go with it
    assert "[18..21]" in out and "[21..23]" in out


# ---------------- what gets given up when money runs short ----------------

def test_a_tight_ceiling_drops_the_verbatim_blocks_rather_than_the_answer(env):
    """The blocks are prepended, so fit() can never trim them; without this
    they turned a query that would have fitted into an outage."""
    from test_budget import _worst_inputs, _session as _budget_session
    from app.ai import pipeline
    question, summary, facts = _worst_inputs()
    env.set_models(FakeGemini(use_full_output=True),
                   FakeClaude(lang="ml", out_fraction=1.0, count_ok=False,
                              report_in="estimate"))
    r = pipeline.run_query(UID, _budget_session("ml", summary=summary), question,
                           prechecked=dict(env.flags, cost_ceiling_units=400),
                           memory_facts=facts)
    assert r.status == "ok" and r.trace["cost_units"] <= 400
    brief = next(s for s in r.trace["stages"] if s["name"] == "brief")
    # the ladder is given up before the rasi table
    assert brief["detail"]["ladder_chars"] == 0


def test_an_impossible_ceiling_still_fails_closed(env):
    from app.ai import pipeline
    claude = FakeClaude(lang="ml", out_fraction=1.0)
    env.set_models(FakeGemini(), claude)
    r = pipeline.run_query(UID, _session("ml"), "నా కెరీర్?",
                           prechecked=dict(env.flags, cost_ceiling_units=120))
    assert r.status == "error" and r.charged_units == 0
    assert claude.calls == [], "no answer may be attempted below the floor"
