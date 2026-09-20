"""Flow: birth profiles (CRUD, "time unknown"), the free first-reading
snapshot in every language, and the whole chart catalogue including the
Pro-gated deep kinds (allowed and denied).

CONTRACT.md -> "Personal & astrologer features": profiles, free charts,
snapshot.
"""

import pytest

from conftest import LANGS, RAVI, SITA

BASIC_KINDS = [("rasi", None), ("navamsa", None), ("varga", "9"), ("varga", "10"),
               ("bhava", None), ("dashas", None), ("panchanga", None),
               ("yogas", None), ("doshas", None), ("gemstones", None)]
PRO_KINDS = [("kp", None), ("shadbala", None), ("ashtakavarga", None), ("nadi", None),
             ("varshphal", None), ("lalkitab", None), ("varga", "all")]


# -------------------------------------------------------------- profiles ----

def test_profile_crud(api):
    _, h = api.signup("u1")
    p = api.profile(h)
    assert p["name"] == "Ravi" and p["relation"] == "self" and p["id"]
    # the place name was resolved to coordinates + tz by the places dataset
    assert p["birth"]["lat"] and p["birth"]["lon"] and p["birth"]["tz"] == "Asia/Kolkata"
    assert p["birth"]["time"] == "10:30" and p["time_known"] is True
    assert p["derived"]["moon_sign"] in range(12)

    got = api.client.get("/api/profiles/%s" % p["id"], headers=h)
    assert got.status_code == 200 and got.json()["id"] == p["id"]

    lst = api.client.get("/api/profiles", headers=h).json()["profiles"]
    assert [x["name"] for x in lst] == ["Ravi"]

    r = api.client.patch("/api/profiles/%s" % p["id"], headers=h,
                         json={"name": "Ravi K", "notes": "eldest son"})
    assert r.status_code == 200 and r.json()["name"] == "Ravi K"
    assert r.json()["notes"] == "eldest son"

    assert api.client.delete("/api/profiles/%s" % p["id"], headers=h).json() == {"ok": True}
    assert api.client.get("/api/profiles", headers=h).json()["profiles"] == []
    gone = api.client.get("/api/profiles/%s" % p["id"], headers=h)
    assert gone.status_code == 404 and gone.json()["code"] == "not_found"


def test_profile_validation_errors_use_contract_codes(api):
    _, h = api.signup("u1")
    for body, why in [
        (dict(RAVI, birth={"date": "15-08-1990", "time": "10:30", "place": "Hyderabad"}),
         "date format"),
        (dict(RAVI, birth={"date": "2090-08-15", "time": "10:30", "place": "Hyderabad"}),
         "future birth"),
        (dict(RAVI, birth={"date": "1990-08-15", "time": "25:30", "place": "Hyderabad"}),
         "bad time"),
        (dict(RAVI, birth={"date": "1990-08-15", "time": "10:30", "place": "Atlantis"}),
         "unknown place"),
        (dict(RAVI, relation="pet"), "bad relation"),
        (dict(RAVI, name=""), "empty name"),
    ]:
        r = api.client.post("/api/profiles", json=body, headers=h)
        assert r.status_code in (400, 422), (why, r.status_code, r.text)
        assert r.json()["code"] == "invalid", why


def test_time_unknown_profile_is_marked_approximate(api):
    _, h = api.signup("u1")
    p = api.profile(h, time_known=False,
                    birth={"date": "1990-08-15", "place": "Hyderabad"})
    assert p["time_known"] is False
    assert p["birth"]["time"] == "12:00"          # noon is used for the maths

    snap = api.client.get("/api/profiles/%s/snapshot?lang=te" % p["id"], headers=h).json()
    assert snap["approximate"] is True and snap["lagna"]["approximate"] is True
    assert snap["notes"]

    # charts still work, they are just flagged
    r = api.client.get("/api/profiles/%s/chart?kind=rasi" % p["id"], headers=h)
    assert r.status_code == 200, r.text

    # fixing the time clears the flag
    r = api.client.patch("/api/profiles/%s" % p["id"], headers=h,
                         json={"time_known": True, "birth": {"time": "10:30"}})
    assert r.status_code == 200, r.text
    snap = api.client.get("/api/profiles/%s/snapshot" % p["id"], headers=h).json()
    assert snap["approximate"] is False


def test_profiles_are_private_to_their_owner(api):
    _, h1 = api.signup("u1", device="dev-aaaa0001")
    _, h2 = api.signup("u2", device="dev-bbbb0002")
    p = api.profile(h1)
    for call in (lambda: api.client.get("/api/profiles/%s" % p["id"], headers=h2),
                 lambda: api.client.get("/api/profiles/%s/snapshot" % p["id"], headers=h2),
                 lambda: api.client.get("/api/profiles/%s/chart?kind=rasi" % p["id"],
                                        headers=h2)):
        r = call()
        assert r.status_code == 404 and r.json()["code"] == "not_found"


def test_places_lookup(api):
    r = api.client.get("/api/places?q=hyder")
    assert r.status_code == 200
    rows = r.json()
    assert rows and all({"label", "lat", "lon", "tz"} <= set(row) for row in rows)


# -------------------------------------------------------------- snapshot ----

@pytest.mark.parametrize("lang", LANGS)
def test_free_snapshot_in_every_language(api, lang):
    """The first reading is free, uses no LLM and is fully localized."""
    _, h = api.signup("u-" + lang, device="dev-snap-" + lang, lang=lang)
    p = api.profile(h)
    before = api.db.data("users/u-%s" % lang)["balance_units"]

    r = api.client.get("/api/profiles/%s/snapshot" % p["id"], headers=h)
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["lang"] == lang
    assert s["lagna"]["sign"] and s["lagna"]["name"] and s["lagna"]["text"]
    assert s["moon_sign"]["text"] and s["nakshatra"]["name"]
    assert 1 <= s["nakshatra"]["pada"] <= 4
    assert s["dasha"]["maha"]["lord"] and s["dasha"]["antar"]["lord"]
    assert len(s["lines"]) >= 6
    text = " ".join(s["lines"])
    assert "{" not in text and "}" not in text          # no unrendered templates

    # free: no charge, no ledger entry, no trace
    assert api.db.data("users/u-%s" % lang)["balance_units"] == before
    assert api.ledger_types("u-" + lang) == ["trial"]
    assert list(api.db.collection("traces").stream()) == []


def test_snapshot_language_precedence(api):
    """?lang beats Accept-Language beats the saved preference."""
    _, h = api.signup("u1", lang="te")
    p = api.profile(h)
    url = "/api/profiles/%s/snapshot" % p["id"]
    assert api.client.get(url, headers=h).json()["lang"] == "te"
    assert api.client.get(url, headers=dict(h, **{"Accept-Language": "ml"})
                          ).json()["lang"] == "ml"
    assert api.client.get(url + "?lang=ta", headers=dict(h, **{"Accept-Language": "ml"})
                          ).json()["lang"] == "ta"


# ---------------------------------------------------------------- charts ----

@pytest.mark.parametrize("kind,division", BASIC_KINDS)
def test_basic_charts_are_free_for_everyone(api, kind, division):
    _, h = api.signup("u1")
    p = api.profile(h)
    url = "/api/profiles/%s/chart?kind=%s" % (p["id"], kind)
    if division:
        url += "&division=" + division
    r = api.client.get(url + "&lang=te", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == kind and body["profile_id"] == p["id"]
    assert body["data"]


@pytest.mark.parametrize("kind,division", PRO_KINDS)
def test_deep_charts_are_pro_only(api, kind, division):
    _, h = api.signup("u1")
    p = api.profile(h)
    url = "/api/profiles/%s/chart?kind=%s" % (p["id"], kind)
    if division:
        url += "&division=" + division

    denied = api.client.get(url, headers=h)
    assert denied.status_code == 403, denied.text
    assert denied.json()["code"] == "forbidden"

    api.set_role("u1")
    api.set_pro("u1")
    allowed = api.client.get(url, headers=h)
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["data"]


def test_expired_pro_plan_loses_the_deep_charts(api):
    _, h = api.signup("u1")
    p = api.profile(h)
    api.set_role("u1")
    api.set_pro("u1", days=-1)
    r = api.client.get("/api/profiles/%s/chart?kind=kp" % p["id"], headers=h)
    assert r.status_code == 403 and r.json()["code"] == "forbidden"


def test_unknown_chart_kind_is_rejected(api):
    _, h = api.signup("u1")
    p = api.profile(h)
    for url in ("?kind=tarot", "?kind=varga&division=13"):
        r = api.client.get("/api/profiles/%s/chart%s" % (p["id"], url), headers=h)
        assert r.status_code == 400 and r.json()["code"] == "invalid"


def test_matching_two_profiles_and_its_pdf(api):
    _, h = api.signup("u1")
    a = api.profile(h, RAVI)
    b = api.profile(h, SITA)
    r = api.client.post("/api/matching?lang=te",
                        json={"profile_a": a["id"], "profile_b": b["id"]}, headers=h)
    assert r.status_code == 200, r.text
    m = r.json()
    assert m["groom"]["name"] == "Ravi" and m["bride"]["name"] == "Sita"
    assert 0 <= m["guna_milan"]["total"] <= 36 and len(m["guna_milan"]["kootas"]) == 8
    assert m["verdict"]["key"] in ("excellent", "very_good", "acceptable", "not_recommended")
    assert m["verdict"]["text"] and m["manglik"]["text"]

    r = api.client.post("/api/matching/pdf?lang=te",
                        json={"profile_a": a["id"], "profile_b": b["id"]}, headers=h)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["path"].startswith("matching/u1/") and out["path"].endswith(".pdf")
    assert out["url"].startswith("https://signed.example/")
    assert out["expires_in_minutes"] == 60
    data, ctype = api.storage.objects[out["path"]]
    assert ctype == "application/pdf" and data[:4] == b"%PDF"

    same = api.client.post("/api/matching",
                           json={"profile_a": a["id"], "profile_b": a["id"]}, headers=h)
    assert same.status_code == 400 and same.json()["code"] == "invalid"
