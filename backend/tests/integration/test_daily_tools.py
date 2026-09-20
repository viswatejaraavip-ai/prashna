"""Flow: the daily screen (panchanga + personal forecast), transit alerts,
the muhurta finder, the birth-time helper and share cards.

CONTRACT.md -> "Personal & astrologer features": daily, alerts, muhurta,
rectify, share-card.
"""

import io

import pytest

from conftest import LANGS, RAVI


# ----------------------------------------------------------------- daily ----

@pytest.mark.parametrize("lang", LANGS)
def test_daily_panchanga_and_personal_forecast(api, lang):
    _, h = api.signup("u-" + lang, device="dev-daily-" + lang, lang=lang)
    p = api.profile(h)
    r = api.client.get("/api/daily?profile_id=%s&date=2026-09-18" % p["id"], headers=h)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["date"] == "2026-09-18" and d["lang"] == lang
    assert d["profile_id"] == p["id"]
    assert d["place"]["lat"] and d["place"]["tz"]

    pan = d["panchanga"]
    for key in ("tithi", "nakshatra", "yoga", "karana"):
        assert pan[key]["local"], key
    tm = pan["timings"]
    assert tm["sunrise"] < tm["sunset"]
    rahu = tm["rahu_kalam"]
    assert rahu["start"] < rahu["end"]
    assert tm["yamagandam"] and tm["gulika"]

    fc = d["forecast"]
    assert fc["rating"] in ("good", "mixed", "careful")
    assert 1 <= fc["tara"] <= 9 and len(fc["lines"]) == 3
    assert "{" not in " ".join(fc["lines"])
    assert d["labels"]

    # cached per date + lang + moon rasi (CONTRACT: daily_content)
    key = "2026-09-18_%s_%d" % (lang, p["derived"]["moon_sign"])
    assert api.db.data("daily_content/" + key)


def test_daily_without_a_profile_still_gives_panchanga(api):
    _, h = api.signup("u1")
    d = api.client.get("/api/daily?date=2026-09-18", headers=h).json()
    assert d["forecast"] is None and d["message"]
    assert d["panchanga"]["timings"]["rahu_kalam"]


def test_daily_rejects_a_bad_date(api):
    _, h = api.signup("u1")
    r = api.client.get("/api/daily?date=18-09-2026", headers=h)
    assert r.status_code == 400 and r.json()["code"] == "invalid"


# ---------------------------------------------------------------- alerts ----

def test_transit_alerts(api):
    _, h = api.signup("u1")
    p = api.profile(h)
    r = api.client.get("/api/profiles/%s/alerts?lang=te" % p["id"], headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["profile_id"] == p["id"] and body["days"] == 180
    alerts = body["alerts"]
    assert alerts, "180 days always contain at least one eclipse"
    assert "eclipse" in {a["type"] for a in alerts}
    for a in alerts:
        assert 0 <= a["days_away"] <= 180
        assert a["text"] and "{" not in a["text"]
    assert [a["date"] for a in alerts] == sorted(a["date"] for a in alerts)

    assert api.client.get("/api/profiles/%s/alerts?days=400" % p["id"],
                          headers=h).status_code == 422


# --------------------------------------------------------------- muhurta ----

@pytest.mark.parametrize("event", ["marriage", "griha_pravesam", "vehicle",
                                   "business", "travel", "naming"])
def test_muhurta_events(api, event):
    _, h = api.signup("u1")
    p = api.profile(h)
    r = api.client.post("/api/muhurta?lang=kn", headers=h, json={
        "event": event, "from": "2026-11-01", "to": "2026-12-15",
        "profile_id": p["id"]})
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["days_checked"] == 45
    scores = [w["score"] for w in res["windows"]]
    assert scores == sorted(scores, reverse=True)
    if res["windows"]:
        top = res["windows"][0]
        assert top["rank"] == 1 and top["reasons"]
        assert top["window"]["start"] < top["window"]["end"]


def test_muhurta_validation(api):
    _, h = api.signup("u1")
    bad = api.client.post("/api/muhurta", headers=h, json={
        "event": "picnic", "from": "2026-11-01", "to": "2026-11-05",
        "lat": 17.4, "lon": 78.5})
    assert bad.status_code == 400 and bad.json()["code"] == "invalid"

    no_place = api.client.post("/api/muhurta", headers=h, json={
        "event": "travel", "from": "2026-11-01", "to": "2026-11-05"})
    assert no_place.status_code == 400 and no_place.json()["code"] == "invalid"

    bad_range = api.client.post("/api/muhurta", headers=h, json={
        "event": "travel", "from": "01-11-2026", "to": "2026-11-05",
        "lat": 17.4, "lon": 78.5})
    assert bad_range.status_code == 400


# -------------------------------------------------------- birth-time help --

def test_birth_time_helper(api):
    _, h = api.signup("u1")
    p = api.profile(h)
    r = api.client.post("/api/profiles/%s/rectify?lang=ta" % p["id"], headers=h, json={
        "events": [{"date": "2016-02-12", "type": "marriage"},
                   {"date": "2018-07-01", "type": "child_birth"},
                   {"date": "2012-06-15", "type": "career_start"}]})
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["estimate"] is True and res["disclaimer"]
    cands = res["candidates"]
    assert 1 <= len(cands) <= 5
    assert [c["score"] for c in cands] == sorted((c["score"] for c in cands), reverse=True)
    assert all(0 <= c["score"] <= 100 for c in cands)
    assert res["window"]["from"] < res["window"]["to"]

    bad = api.client.post("/api/profiles/%s/rectify" % p["id"], headers=h,
                          json={"events": [{"date": "1980-01-01", "type": "marriage"}]})
    assert bad.status_code == 400 and bad.json()["code"] == "invalid"


# ------------------------------------------------------------ share cards --

@pytest.mark.parametrize("kind", ["chart", "daily"])
def test_share_card_upload_and_signed_url(api, kind):
    from PIL import Image
    _, h = api.signup("u1", lang="ml")
    p = api.profile(h)
    r = api.client.post("/api/share-card", headers=h,
                        json={"profile_id": p["id"], "kind": kind})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["path"].startswith("share/u1/") and out["path"].endswith(".png")
    assert out["url"].startswith("https://signed.example/")
    data, ctype = api.storage.objects[out["path"]]
    assert ctype == "image/png"
    assert Image.open(io.BytesIO(data)).size == (1080, 1350)


def test_share_card_bad_kind(api):
    _, h = api.signup("u1")
    p = api.profile(h)
    r = api.client.post("/api/share-card", headers=h,
                        json={"profile_id": p["id"], "kind": "poster"})
    assert r.status_code == 400 and r.json()["code"] == "invalid"


# -------------------------------------------------------------- cron jobs --

def test_cron_endpoints_require_the_scheduler_identity(api, monkeypatch):
    """Without CRON_INSECURE_DEV and without an OIDC token: 401."""
    monkeypatch.delenv("CRON_INSECURE_DEV", raising=False)
    for path in ("/internal/cron/daily-push", "/internal/cron/transit-alerts",
                 "/internal/cron/purge-deleted", "/internal/cron/cost-watch"):
        r = api.client.post(path)
        assert r.status_code == 401, (path, r.status_code, r.text)


def test_daily_push_cron_sends_to_opted_in_users(api, monkeypatch):
    monkeypatch.setenv("CRON_INSECURE_DEV", "1")
    _, h = api.signup("u1", lang="te")
    api.profile(h)
    api.client.post("/api/me/fcm-token", headers=h, json={"token": "fcm-" + "a" * 40})

    # a user who opted out of the daily push
    _, h2 = api.signup("u2", device="dev-2222aaaa", lang="hi")
    api.profile(h2, RAVI)
    api.client.post("/api/me/fcm-token", headers=h2, json={"token": "fcm-" + "b" * 40})
    api.client.patch("/api/me", headers=h2, json={"notif_prefs": {"daily": False}})

    r = api.client.post("/internal/cron/daily-push")
    assert r.status_code == 200, r.text
    assert r.json()["sent"] >= 1
    assert len(api.pushes) == 1
    assert api.pushes[0]["tokens"] == ["fcm-" + "a" * 40]

    # the marker makes a retry a no-op
    before = len(api.pushes)
    api.client.post("/internal/cron/daily-push")
    assert len(api.pushes) == before


def test_transit_alerts_cron(api, monkeypatch):
    monkeypatch.setenv("CRON_INSECURE_DEV", "1")
    _, h = api.signup("u1", lang="te")
    api.profile(h)
    api.client.post("/api/me/fcm-token", headers=h, json={"token": "fcm-" + "c" * 40})
    r = api.client.post("/internal/cron/transit-alerts")
    assert r.status_code == 200, r.text
    assert set(r.json()) >= {"considered", "sent", "skipped"}
