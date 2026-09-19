import pytest

from tests.features.conftest import RAVI, SITA, auth, make_user

LANGS = ("hi", "te", "ta", "kn", "ml", "en")


def _mk(client, db, body=RAVI, uid="u1", **user):
    make_user(db, uid, **user)
    return client.post("/api/profiles", json=body, headers=auth(uid)).json()


@pytest.mark.parametrize("lang", LANGS)
def test_snapshot_all_languages(client, db, lang):
    p = _mk(client, db)
    r = client.get("/api/profiles/%s/snapshot?lang=%s" % (p["id"], lang), headers=auth())
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["lang"] == lang
    assert s["lagna"]["sign"] and s["lagna"]["text"] and s["moon_sign"]["text"]
    assert s["nakshatra"]["name"] and 1 <= s["nakshatra"]["pada"] <= 4
    assert s["dasha"]["maha"]["lord"] and s["dasha"]["antar"]["lord"]
    assert len(s["lines"]) >= 6
    text = " ".join(s["lines"])
    assert "{" not in text and "Ravi" in text
    # Localised names from the engine locale are used, not English
    from jyotish import locale
    expected = (s["lagna"]["sign"] if lang == "en"
                else locale.bundle(lang)["signs"][s["lagna"]["sign"]])
    assert s["lagna"]["name"] == expected


def test_snapshot_time_unknown_notes(client, db):
    body = dict(RAVI, time_known=False, birth={"date": "1990-08-15", "place": "Hyderabad"})
    p = _mk(client, db, body)
    s = client.get("/api/profiles/%s/snapshot?lang=te" % p["id"], headers=auth()).json()
    assert s["approximate"] and s["lagna"]["approximate"]
    assert s["notes"]


def test_snapshot_uses_saved_language(client, db):
    p = _mk(client, db, lang="ml")
    s = client.get("/api/profiles/%s/snapshot" % p["id"], headers=auth()).json()
    assert s["lang"] == "ml"


@pytest.mark.parametrize("lang", ["te", "hi"])
def test_daily(client, db, lang):
    p = _mk(client, db)
    r = client.get("/api/daily?profile_id=%s&date=2026-09-18&lang=%s" % (p["id"], lang),
                   headers=auth())
    assert r.status_code == 200, r.text
    d = r.json()
    pan = d["panchanga"]
    assert pan["tithi"]["local"] and pan["nakshatra"]["local"] and pan["yoga"]["local"]
    tm = pan["timings"]
    assert tm["rahu_kalam"]["start"] < tm["rahu_kalam"]["end"]
    assert tm["yamagandam"] and tm["gulika"]
    fc = d["forecast"]
    assert fc["rating"] in ("good", "mixed", "careful") and 1 <= fc["tara"] <= 9
    assert len(fc["lines"]) == 3
    key = "2026-09-18_%s_%d" % (lang, p["derived"]["moon_sign"])
    assert db.collection("daily_content").document(key).get().exists


def test_daily_without_profile(client, db):
    make_user(db)
    d = client.get("/api/daily?date=2026-09-18", headers=auth()).json()
    assert d["forecast"] is None and d["message"] and d["panchanga"]["timings"]


def test_tarabala_math():
    from app.features import daily
    assert daily.tara_of(0, 0) == 1           # janma
    assert daily.tara_of(0, 1) == 2           # sampat
    assert daily.tara_of(26, 0) == 2          # wraps around
    assert daily.tara_of(0, 9) == 1           # 10th star = anujanma
    assert daily.chandra_house(0, 7) == 8     # chandrashtama
    assert daily.rating_of(2, 8) == "careful"
    assert daily.rating_of(6, 11) == "good"


def test_alerts(client, db):
    p = _mk(client, db)
    r = client.get("/api/profiles/%s/alerts?lang=te" % p["id"], headers=auth())
    assert r.status_code == 200, r.text
    alerts = r.json()["alerts"]
    types = {a["type"] for a in alerts}
    # In any 180-day window there are antardasha changes? Not always, but
    # eclipses always occur (at least two eclipse seasons per year).
    assert "eclipse" in types
    for a in alerts:
        assert 0 <= a["days_away"] <= 180 and a["text"] and "{" not in a["text"]
    assert [a["date"] for a in alerts] == sorted(a["date"] for a in alerts)


def test_alerts_detect_sade_sati_and_dasha():
    """Deterministic check with a fixed 'today': Saturn enters Aries in
    2027 (sidereal). For a Pisces Moon that is the final Sade Sati phase."""
    from datetime import date
    from app.features import alerts
    prof = {"id": "x", "name": "T", "time_known": True,
            "birth": {"date": "1990-03-01", "time": "06:00", "tz": "Asia/Kolkata",
                      "lat": 17.385, "lon": 78.4867, "place": "Hyderabad"},
            "derived": {"moon_sign": 11, "nakshatra": 25, "lagna_sign": 10}}
    res = alerts.compute(prof, "te", days=366, today=date(2027, 1, 1))
    sat = [a for a in res if a["data"].get("planet") == "Saturn"]
    assert sat, res
    assert any(a["data"]["phase"] == "sade_sati_final" for a in sat)
    assert any(a["type"] in ("antar_change", "maha_change") for a in res)


def test_matching(client, db):
    p1 = _mk(client, db)
    p2 = client.post("/api/profiles", json=SITA, headers=auth()).json()
    for lang in LANGS:
        r = client.post("/api/matching?lang=%s" % lang,
                        json={"profile_a": p2["id"], "profile_b": p1["id"]}, headers=auth())
        assert r.status_code == 200, r.text
        m = r.json()
        # gender decides groom/bride regardless of order
        assert m["groom"]["name"] == "Ravi" and m["bride"]["name"] == "Sita"
        assert 0 <= m["guna_milan"]["total"] <= 36 and len(m["guna_milan"]["kootas"]) == 8
        assert m["verdict"]["key"] in ("excellent", "very_good", "acceptable", "not_recommended")
        assert m["verdict"]["text"] and m["manglik"]["text"]
        assert len(m["dashakoot"]["poruthams"]) == 10
    r = client.post("/api/matching", json={"profile_a": p1["id"], "profile_b": p1["id"]},
                    headers=auth())
    assert r.status_code == 400


def test_muhurta(client, db):
    p = _mk(client, db)
    r = client.post("/api/muhurta?lang=kn", json={
        "event": "marriage", "from": "2026-11-01", "to": "2026-12-31",
        "profile_id": p["id"]}, headers=auth())
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["days_checked"] == 61 and res["windows"]
    scores = [w["score"] for w in res["windows"]]
    assert scores == sorted(scores, reverse=True)
    top = res["windows"][0]
    assert top["rank"] == 1 and top["reasons"] and not top["blocked"]
    assert top["window"]["start"] < top["window"]["end"]
    assert top["panchanga"]["tithi"]["number"] != 30
    for w in res["windows"]:
        assert w["panchanga"]["karana"]["name"] != "Vishti"
    bad = client.post("/api/muhurta", json={"event": "picnic", "from": "2026-11-01",
                                            "to": "2026-11-05", "lat": 17.4, "lon": 78.5},
                      headers=auth())
    assert bad.status_code == 400
    too_long = client.post("/api/muhurta", json={"event": "travel", "from": "2026-01-01",
                                                 "to": "2027-06-01", "lat": 17.4, "lon": 78.5},
                           headers=auth())
    assert too_long.status_code == 400


def test_muhurta_best_window_avoids_rahu():
    from app.features.muhurta import best_window
    timings = {"sunrise": "06:00", "sunset": "18:00",
               "inauspicious": {"rahu_kalam": {"start": "07:30", "end": "09:00"},
                                "yamaganda": {"start": "10:30", "end": "12:00"},
                                "gulika_kalam": {"start": "13:30", "end": "15:00"}},
               "auspicious": {"abhijit_muhurta": {"start": "11:36", "end": "12:24"}}}
    w = best_window(timings)
    assert w == {"start": "15:00", "end": "18:00", "abhijit": False}


def test_rectify(client, db):
    p = _mk(client, db)
    r = client.post("/api/profiles/%s/rectify?lang=ta" % p["id"], json={
        "events": [{"date": "2016-02-12", "type": "marriage"},
                   {"date": "2018-07-01", "type": "child_birth"},
                   {"date": "2012-06-15", "type": "career_start"}]}, headers=auth())
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["estimate"] is True and res["disclaimer"]
    assert res["window"]["from"] == "09:30" and res["window"]["to"] == "11:30"
    c = res["candidates"]
    assert 1 <= len(c) <= 5
    assert [x["score"] for x in c] == sorted((x["score"] for x in c), reverse=True)
    assert all(0 <= x["score"] <= 100 for x in c)
    bad = client.post("/api/profiles/%s/rectify" % p["id"],
                      json={"events": [{"date": "1980-01-01", "type": "marriage"}]}, headers=auth())
    assert bad.status_code == 400
