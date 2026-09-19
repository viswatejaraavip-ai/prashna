"""Every chart kind yields a display-ready view; no engine English leaks
when a language other than English is requested."""

import pytest

from app.features import common, views

BIRTH = {"birth": {"date": "1990-01-15", "time": "06:00", "lat": 17.38, "lon": 78.46,
                   "tz": "Asia/Kolkata"}, "time_known": True}


def _data(kind):
    b = common.birth_dict(BIRTH, "te")
    j = common.japi
    return {
        "rasi": lambda: j.birth_chart(b), "navamsa": lambda: j.varga_chart(b, "D9"),
        "bhava": lambda: j.bhava_chart(b), "yogas": lambda: j.yoga_analysis(b),
        "doshas": lambda: j.dosha_analysis(b), "panchanga": lambda: j.panchanga_for(b),
        "gemstones": lambda: j.gemstone_recommendations(b), "kp": lambda: j.kp_chart(b),
        "shadbala": lambda: j.shadbala_chart(b), "ashtakavarga": lambda: j.ashtakavarga_chart(b),
        "nadi": lambda: j.nadi_analysis(b), "lalkitab": lambda: j.lal_kitab(b),
        "varshphal": lambda: j.varshphal(b, 2026),
        "dashas": lambda: dict(j.dasha_periods(b, 2, "vimshottari"), current=j.current_dasha(b)),
        "varga": lambda: j.all_vargas(b),
    }[kind]()


KINDS = ["rasi", "navamsa", "bhava", "yogas", "doshas", "panchanga", "gemstones", "kp",
         "shadbala", "ashtakavarga", "nadi", "lalkitab", "varshphal", "dashas", "varga"]


@pytest.mark.parametrize("kind", KINDS)
def test_view_builds(kind):
    div = "all" if kind == "varga" else None
    v = views.build(kind, div, _data(kind), "en")
    assert v.get("sections") or v.get("charts")
    if kind in ("rasi", "navamsa"):
        assert v["chart"]["lagna"] in range(12) and len(v["chart"]["planets"]) == 9
    if kind == "varga":
        assert len(v["charts"]) == 16


@pytest.mark.parametrize("kind", KINDS)
def test_all_english_goes_through_translation(kind, monkeypatch):
    """With a fake translator that tags strings, no untagged English words
    remain outside planet/sign/nakshatra names, numbers and dates."""
    from app.features import translate
    monkeypatch.setattr(translate, "translate_many", lambda texts, lang: ["⟦%s⟧" % t for t in texts])
    div = "all" if kind == "varga" else None
    v = views.build(kind, div, _data(kind), "te")

    import re
    def strings(x):
        if isinstance(x, str):
            yield x
        elif isinstance(x, dict):
            for k, val in x.items():
                if k not in ("key", "tone"):
                    yield from strings(val)
        elif isinstance(x, list):
            for val in x:
                yield from strings(val)
    for s in strings(v):
        leftover = re.sub(r"⟦[^⟧]*⟧", "", s)
        leftover = re.sub(r"\bD\d+\b", "", leftover)  # varga codes
        assert not re.search(r"[A-Za-z]{3,}", leftover), (kind, s)


@pytest.mark.parametrize("kind", ["matching", "muhurta", "rectify"])
def test_tool_views_translate_everything(kind, monkeypatch):
    from datetime import date
    import re
    from app.features import matching, muhurta, rectify, translate
    other = dict(BIRTH, name="B", birth=dict(BIRTH["birth"], date="1992-03-10"), gender="female")
    res = {"matching": lambda: matching.match(dict(BIRTH, name="A", gender="male"), other, "te"),
           "muhurta": lambda: muhurta.find("marriage", date(2026, 10, 1), date(2026, 10, 31),
                                           17.38, 78.46, "Asia/Kolkata", "te", None, 5),
           "rectify": lambda: rectify.rectify(dict(BIRTH, id="p1"),
                                              [{"date": "2015-06-01", "type": "marriage"},
                                               {"date": "2012-01-10", "type": "career_start"}], "te")}[kind]()
    calls = []
    monkeypatch.setattr(translate, "translate_many",
                        lambda texts, lang: calls.append(1) or ["⟦%s⟧" % t for t in texts])
    v = views.tool_view(kind, res, "te")
    assert v["sections"] and calls, "builder failed or nothing was translated"
    flat = str(v)
    leftover = re.sub(r"⟦[^⟧]*⟧", "", flat)
    for word in ("Days checked", "Event name", "Window text", "Blocked", "'Score"):
        assert word not in leftover, (kind, word)
