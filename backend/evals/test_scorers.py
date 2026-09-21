"""Tests for the deterministic scorers, run with

    cd backend && ../.venv/bin/python -m pytest evals/test_scorers.py

The charts are real engine output, not hand-written fixtures, so a
claim that the checker calls wrong here is wrong against the same engine data
the report quotes. The claim strings are copied verbatim out of
out/answers.jsonl for the same reason.
"""

import json
import pytest
import os

import scorers

HERE = os.path.dirname(os.path.abspath(__file__))
TODAY = "2026-09-20"
# A live run's out/charts.json is gitignored (it can hold private charts), so
# the tests read a committed fixture of the public figures' charts and prefer
# the live file only when it is there. Without this the suite cannot run in a
# fresh clone, which is where most people will first try it.
_LIVE = os.path.join(HERE, "out", "charts.json")
_FIXTURE = os.path.join(HERE, "fixtures", "charts.json")
# The unit tests below always read the committed fixture, so they behave the
# same on a clean checkout as on a machine that has done a live run. Only the
# run-wide re-score reads a live run, and it skips when there is not one.
FIXTURES = json.load(open(_FIXTURE))
CHARTS = json.load(open(_LIVE)) if os.path.exists(_LIVE) else FIXTURES
# A synthetic chart: real engine output, nobody's actual birth.
SYNTH = FIXTURES["synthetic"]["dashas"]
VK = FIXTURES["vk"]["dashas"]
AB = FIXTURES["ab"]["dashas"]


def score(reply, lang, dashas=None):
    return scorers.dasha_grounding(reply, lang, dashas or SYNTH, TODAY)


def test_wrong_antardasha_dates_are_wrong_not_another_system():
    """The defect, on a chart that reproduces it: the reply puts Rahu-Saturn in
    2014-2016; on this chart the engine has it at 2003-01 to 2005-11, and by
    2016 the Rahu mahadasha is over. It used to be filed under other_system."""
    reply = ("**ప్రశ్న**\n\n"
             "ఈ జాతకంలో ఉద్యోగ జీవితం **2014–2015 (వయసు 21–22)** ప్రాంతంలో మొదలైనట్టు కనిపిస్తోంది.\n\n"
             "**కారణాలు:**\n"
             "- **రాహు-శని అంతర్దశ** (2014-02 to 2016-12, వయసు 20–23): "
             "శని 6వ భావంలో ఉండి సేవా/ఉద్యోగ ఫలితాలు ఇచ్చాడు.\n")
    d = score(reply, "te")
    assert d["wrong"] == 1
    assert d["verifiable"] == 1
    assert d["other_system"] == 0
    assert d["errors"][0]["planet"] == "Rahu-Saturn"
    assert d["errors"][0]["years"] == [2014, 2016]


def test_right_antardasha_dates_stay_right():
    """Same chart, same shape of claim, dates the engine agrees with."""
    reply = ("- **రాహు-శుక్ర అంతర్దశ (2009-06 నుండి 2012-06):** "
             "రాహు 3వ భావంలో (ప్రయాణం), శుక్రుడు 7వ భావంలో (విదేశాలు) ఉన్నారు.\n")
    d = score(reply, "te")
    assert (d["verifiable"], d["wrong"]) == (1, 0)


def test_yogini_pair_is_left_unscored():
    """Yogini periods are named after planets too and the free chart endpoint
    does not return them, so a Yogini pair whose dates match no Vimshottari
    period must not be called wrong. Mars-Rahu really is a Vimshottari pair on
    this chart, in 2079 -- the line saying "Yogini" is the only thing that
    stops it being scored."""
    reply = ("విమ్శోత్తరిలో **బుధ–చంద్ర–శుక్ర ప్రత్యంతర్దశ** మరియు "
             "యోగినిలో **మంగళ–సంకట (రాహు) అంతర్దశ** కలిసే సమయం "
             "(2026 అక్టోబర్ – 2027 జనవరి).\n")
    d = score(reply, "te")
    assert (d["verifiable"], d["wrong"]) == (0, 0)
    assert d["other_system"] >= 1


def test_yogini_mahadasha_is_left_unscored():
    reply = ("- **యోగిని దశ** — భద్రికా (బుధ) మహాదశ 2014లో మొదలైంది; "
             "బుధుడు 10వ భావాధిపతి.\n")
    d = score(reply, "te")
    assert (d["verifiable"], d["wrong"]) == (0, 0)
    assert d["other_system"] == 1


def test_chara_names_signs_not_planets():
    """Chara dasha lords are rasis, so there is no planet pair to score even
    before the system name is read."""
    reply = ("- **చర దశ** — వృషభ మహాదశ 2013లో ప్రారంభం; "
             "10మ అధిపతి బుధుడు వృషభంలోనే ఉన్నాడు.\n")
    d = score(reply, "te")
    assert (d["verifiable"], d["wrong"]) == (0, 0)
    assert not scorers.lord_pair_claims(reply, "te")


def test_correct_mahadasha_claim_still_scores_right():
    reply = "గురు మహాదశ 2022 అక్టోబర్ నుండి 2038 వరకు నడుస్తుంది.\n"
    d = score(reply, "te")
    assert (d["verifiable"], d["wrong"]) == (1, 0)


def test_pratyantardasha_is_not_checkable():
    """Three lords in a row is the third level, and the endpoint returns only
    the one running today, so it cannot be matched against a table."""
    reply = ("- **విమ్శోత్తరి దశ:** గురు-శని-రాహు ప్రత్యంతర్ "
             "(సెప్టెంబర్ 2026 – ఫిబ్రవరి 2027) నడుస్తోంది.\n")
    d = score(reply, "te")
    assert (d["verifiable"], d["wrong"]) == (0, 0)
    assert d["other_system"] == 1


def test_conjunction_is_not_a_period():
    """Two planets side by side are only a dasha claim when a dasha word sits
    next to them; Venus-Saturn here is a navamsa conjunction."""
    reply = ("**ராகு-சுக்கிரன் அந்தர்தசை (2021 மே - 2024 மே)** சாத்தியமான காலம்.\n"
             "- நவாம்சத்தில் சுக்கிரன்-சனி 5-ல் இணைவு திருமண யோகம் காட்டுகிறது\n")
    d = score(reply, "ta", VK)
    assert (d["verifiable"], d["wrong"]) == (1, 0)
    assert [c["lords"] for c in scorers.lord_pair_claims(reply, "ta")] \
        == [("Rahu", "Venus")]


def test_tamil_bhukti_is_not_the_planet_mercury():
    """"புத்தி" is bhukti, not புதன். Reading it as Mercury turned every
    "சந்திர புத்தி" into a Moon-Mercury period that no chart can match."""
    reply = ("- **சந்திர புத்தி** — 22-04-2025 முதல் 22-10-2026 வரை\n")
    d = score(reply, "ta", VK)
    assert (d["verifiable"], d["wrong"]) == (0, 0)


def test_antardasha_pair_written_across_two_words():
    """The lords are often split by the word mahadasha and its case ending."""
    reply = ("- **വ്യാഴ മഹാദശ – ശുക്ര അന്തർദശ (1966 നവംബർ – 1969 ജൂലൈ, "
             "പ്രായം 24–26)**: വ്യാഴം പുത്രകാരകനാണ്.\n")
    claims = scorers.lord_pair_claims(reply, "ml")
    assert [c["lords"] for c in claims] == [("Jupiter", "Venus")]
    # two claims: the Jupiter mahadasha and the Jupiter-Venus antardasha
    d = score(reply, "ml", AB)
    assert (d["verifiable"], d["wrong"]) == (2, 0)


def test_pair_with_no_dates_is_unverifiable():
    reply = "గురు-శని అంతర్దశ ఇప్పుడు నడుస్తోంది.\n"
    d = score(reply, "te")
    assert (d["verifiable"], d["wrong"]) == (0, 0)
    assert d["unverifiable"] == 1


def test_the_whole_saved_run_scores_without_false_positives():
    """The whole saved run, so a checker change cannot quietly start calling
    correct answers wrong.

    Pinning exact totals here was tried and is wrong: out/answers.jsonl is
    re-asked whenever a fix lands, so the counts move for reasons that have
    nothing to do with this checker. What must hold is that coverage does not
    collapse and that nothing is flagged wrong unless it has been read against
    the engine by hand and listed below.
    """
    # id -> why it is genuinely wrong (hand-checked against out/charts.json).
    KNOWN_WRONG = {
        # Re-asked on the build that hands the ladder over with closed
        # intervals, and now correct; kept because the row can come back.
        "owner__career_start":
            "claimed Rahu-Saturn 2014-02..2016-12; the engine says that "
            "antardasha ran 2009-11..2012-09",
    }
    answers = os.path.join(HERE, "out", "answers.jsonl")
    if not os.path.exists(answers):
        pytest.skip("no live run on this machine; nothing to re-score")
    rows = [json.loads(l) for l in open(answers)]
    tot = {"verifiable": 0, "wrong": 0, "other_system": 0, "unverifiable": 0}
    wrong_ids = []
    for r in rows:
        d = scorers.dasha_grounding(r["reply"], r["lang"],
                                    CHARTS[r["chart"]]["dashas"], TODAY)
        for k in tot:
            tot[k] += d[k]
        if d["wrong"]:
            wrong_ids.append(r["id"])
    unexpected = [i for i in wrong_ids if i not in KNOWN_WRONG]
    assert not unexpected, (
        "the checker calls these wrong and nobody has hand-checked them: %s"
        % unexpected)
    # Coverage: the antardasha pass roughly doubled what is checkable at all
    # (23 -> 51 when it landed). A collapse means the checker stopped reading
    # claims, which is how the defect it fixes looked in the first place.
    assert tot["verifiable"] >= 40, tot
