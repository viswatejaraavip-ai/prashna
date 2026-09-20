import pytest

from app.features.common import templates
from tests.features.conftest import RAVI, auth, make_user

CLIENT = {"name": "Client One", "birth": {"date": "1985-01-20", "time": "05:15",
                                          "place": "Bengaluru"}, "notes": "career query"}
TE, EN = templates("te"), templates("en")


@pytest.mark.parametrize("kind,division", [("kp", None), ("shadbala", None),
                                           ("ashtakavarga", None), ("varga", "all"),
                                           ("nadi", None), ("varshphal", None),
                                           ("lalkitab", None), ("varga", "kp")])
def test_deep_kinds_need_pro(client, db, kind, division):
    make_user(db)
    p = client.post("/api/profiles", json=RAVI, headers=auth()).json()
    url = "/api/profiles/%s/chart?kind=%s" % (p["id"], kind)
    if division:
        url += "&division=" + division
    r = client.get(url, headers=auth())
    assert r.status_code == 403 and r.json()["code"] == "forbidden"
    make_user(db, plan="pro", expires_days=10, role="astrologer")
    r = client.get(url, headers=auth())
    assert r.status_code == 200, r.text
    assert r.json()["data"]


@pytest.mark.parametrize("kind,division", [("rasi", None), ("navamsa", None), ("varga", "10"),
                                           ("bhava", None), ("dashas", None), ("panchanga", None),
                                           ("yogas", None), ("doshas", None), ("gemstones", None)])
def test_basic_kinds_are_free(client, db, kind, division):
    make_user(db)
    p = client.post("/api/profiles", json=RAVI, headers=auth()).json()
    url = "/api/profiles/%s/chart?kind=%s" % (p["id"], kind) + ("&division=" + division if division else "")
    r = client.get(url, headers=auth())
    assert r.status_code == 200, r.text


def test_expired_pro_is_not_pro(client, db):
    make_user(db, plan="pro", expires_days=-1, role="astrologer")
    p = client.post("/api/profiles", json=RAVI, headers=auth()).json()
    assert client.get("/api/profiles/%s/chart?kind=kp" % p["id"], headers=auth()).status_code == 403
    make_user(db, plan="pro", role="astrologer")  # no expiry recorded
    assert client.get("/api/profiles/%s/chart?kind=kp" % p["id"], headers=auth()).status_code == 403


def test_bad_kind(client, db):
    make_user(db)
    p = client.post("/api/profiles", json=RAVI, headers=auth()).json()
    assert client.get("/api/profiles/%s/chart?kind=tarot" % p["id"], headers=auth()).status_code == 400
    assert client.get("/api/profiles/%s/chart?kind=varga&division=13" % p["id"],
                      headers=auth()).status_code == 400


def test_astro_endpoints_need_astrologer_role(client, db):
    make_user(db)
    assert client.get("/api/astro/clients", headers=auth()).status_code == 403
    assert client.get("/api/astro/brand", headers=auth()).status_code == 403


def test_clients_notes_search_and_bundle(client, db):
    make_user(db, role="astrologer")
    h = auth()
    c1 = client.post("/api/astro/clients", json=CLIENT, headers=h).json()
    assert c1["relation"] == "client"
    client.post("/api/astro/clients", json=dict(CLIENT, name="Another", notes="marriage"), headers=h)
    client.post("/api/profiles", json=RAVI, headers=h)  # own profile, not a client
    lst = client.get("/api/astro/clients", headers=h).json()["clients"]
    assert [c["name"] for c in lst] == ["Another", "Client One"]
    assert [c["name"] for c in client.get("/api/astro/clients?q=career", headers=h).json()["clients"]] \
        == ["Client One"]
    assert [c["name"] for c in client.get("/api/astro/clients?q=bengal", headers=h).json()["clients"]] \
        == ["Another", "Client One"]
    r = client.patch("/api/astro/clients/%s" % c1["id"], json={"notes": "follow up in May"}, headers=h)
    assert r.json()["notes"] == "follow up in May"
    # family profiles list hides clients by default
    fam = client.get("/api/profiles", headers=h).json()["profiles"]
    assert [p["name"] for p in fam] == ["Ravi"]

    # Pro bundle gated by plan
    r = client.get("/api/astro/clients/%s/pro-bundle" % c1["id"], headers=h)
    assert r.status_code == 403
    make_user(db, role="astrologer", plan="pro", expires_days=30)
    r = client.get("/api/astro/clients/%s/pro-bundle" % c1["id"], headers=h)
    assert r.status_code == 200, r.text
    b = r.json()
    assert len(b["vargas"]) == 16
    assert {"kp", "shadbala", "ashtakavarga", "bhava_chalit", "dashas", "yogas", "doshas"} <= set(b)
    assert set(b["dashas"]) >= {"vimshottari", "yogini", "chara", "kalachakra"}
    assert b["kp"]["significators"]


def test_brand(client, db):
    make_user(db, role="astrologer")
    h = auth()
    r = client.put("/api/astro/brand", json={"display_name": "Sri Sai Jyotisham",
                                             "phone": "+91 90000 00000",
                                             "footer": "Consultations by appointment"}, headers=h)
    assert r.status_code == 200
    assert r.json()["brand"]["display_name"] == "Sri Sai Jyotisham"
    assert client.get("/api/astro/brand", headers=h).json()["brand"]["display_name"] == "Sri Sai Jyotisham"
    bad = client.put("/api/astro/brand", json={"display_name": "X", "logo_url": "http://x"}, headers=h)
    assert bad.status_code == 400


def test_brand_unset_is_an_empty_object_not_null(client, db):
    """Regression: the app decoded `{"brand": null}` into its Brand DTO and the
    settings screen died with an API error before it ever drew the form."""
    make_user(db, role="astrologer")
    body = client.get("/api/astro/brand", headers=auth()).json()
    assert body["brand"] == {"display_name": "", "phone": "", "logo_url": "", "footer": ""}


def test_brand_errors_are_localized_and_never_name_a_field(client, db):
    """Validation text reaches the user verbatim, so it must be in their
    language and must not leak `display_name`-style field names."""
    make_user(db, role="astrologer", lang="te")
    h = auth()
    for body in ({}, {"phone": "+91 90000 00000"}, {"display_name": "   "}):
        r = client.put("/api/astro/brand", json=body, headers=h)
        assert r.status_code == 400, (body, r.text)
        detail = r.json()["detail"]
        assert r.json()["code"] == "invalid"
        assert "display_name" not in detail and detail == TE["errors"]["brand_name_required"]
    checks = [({"display_name": "X", "logo_url": "http://x"}, "brand_logo_https"),
              ({"display_name": "X", "phone": "call me!"}, "brand_phone_invalid")]
    for body, key in checks:
        r = client.put("/api/astro/brand", json=body, headers=h)
        assert r.status_code == 400 and r.json()["detail"] == TE["errors"][key], body
    r = client.put("/api/astro/brand", json={"display_name": "X" * 81}, headers=h)
    assert r.status_code == 400
    assert r.json()["detail"] == TE["errors"]["brand_too_long"].format(
        field=TE["brand_fields"]["display_name"], limit=80)


def test_brand_round_trips_every_field(client, db):
    make_user(db, role="astrologer")
    h = auth()
    brand = {"display_name": "Sri Sai Jyotisham", "phone": "+91 90000 00000",
             "logo_url": "https://example.com/logo.png", "footer": "By appointment"}
    assert client.put("/api/astro/brand", json=brand, headers=h).status_code == 200
    saved = client.get("/api/astro/brand", headers=h).json()["brand"]
    assert {k: saved[k] for k in brand} == brand
    # A second save overwrites cleared fields instead of keeping the old value.
    client.put("/api/astro/brand", json={"display_name": "Only Name"}, headers=h)
    saved = client.get("/api/astro/brand", headers=h).json()["brand"]
    assert saved == {"display_name": "Only Name", "phone": "", "logo_url": "", "footer": "",
                     "updated_at": saved["updated_at"]}


def test_astro_gate_messages_are_localized(client, db):
    make_user(db, lang="te")  # role=user
    r = client.get("/api/astro/clients", headers=auth())
    assert r.status_code == 403 and r.json()["detail"] == TE["errors"]["astrologer_only"]
    make_user(db, role="astrologer", lang="te")
    p = client.post("/api/astro/clients", json=CLIENT, headers=auth()).json()
    r = client.get("/api/astro/clients/%s/pro-bundle" % p["id"], headers=auth())
    assert r.status_code == 403 and r.json()["detail"] == TE["errors"]["pro_needed"]
    r = client.get("/api/profiles/%s/chart?kind=shadbala" % p["id"], headers=auth())
    assert r.status_code == 403
    assert r.json()["detail"] == TE["errors"]["pro_needed_chart"].format(
        chart=TE["chart_kinds"]["shadbala"])
    # `lang` on the request wins over the saved language.
    r = client.get("/api/profiles/%s/chart?kind=shadbala&lang=en" % p["id"], headers=auth())
    assert r.json()["detail"].startswith(EN["chart_kinds"]["shadbala"])


def test_client_crud_and_not_found(client, db):
    make_user(db, role="astrologer", lang="te")
    h = auth()
    c1 = client.post("/api/astro/clients", json=CLIENT, headers=h).json()
    assert c1["birth"]["place_local"], "the app shows place_local straight after adding"
    got = client.get("/api/astro/clients/%s" % c1["id"], headers=h)
    assert got.status_code == 200 and got.json()["name"] == "Client One"
    # A family profile is not reachable through the client routes.
    fam = client.post("/api/profiles", json=RAVI, headers=h).json()
    for path in ("/api/astro/clients/%s", "/api/astro/clients/%s/pro-bundle"):
        r = client.get(path % fam["id"], headers=h)
        assert r.status_code in (403, 404)
        if r.status_code == 404:
            assert r.json()["detail"] == TE["errors"]["client_not_found"]
    assert client.delete("/api/astro/clients/%s" % fam["id"], headers=h).status_code == 404
    # Editing a client keeps it a client even if the app echoes a relation back.
    r = client.patch("/api/astro/clients/%s" % c1["id"],
                     json={"name": "Renamed", "relation": "spouse"}, headers=h)
    assert r.status_code == 200 and r.json()["relation"] == "client"
    assert r.json()["name"] == "Renamed"
    assert client.delete("/api/astro/clients/%s" % c1["id"], headers=h).status_code == 200
    assert client.get("/api/astro/clients", headers=h).json()["clients"] == []
    assert client.delete("/api/astro/clients/%s" % c1["id"], headers=h).status_code == 404
