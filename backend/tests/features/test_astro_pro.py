import pytest

from tests.features.conftest import RAVI, auth, make_user

CLIENT = {"name": "Client One", "birth": {"date": "1985-01-20", "time": "05:15",
                                          "place": "Bengaluru"}, "notes": "career query"}


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
    assert client.get("/api/astro/brand", headers=h).json() == {"brand": None}
    r = client.put("/api/astro/brand", json={"display_name": "Sri Sai Jyotisham",
                                             "phone": "+91 90000 00000",
                                             "footer": "Consultations by appointment"}, headers=h)
    assert r.status_code == 200
    assert client.get("/api/astro/brand", headers=h).json()["brand"]["display_name"] == "Sri Sai Jyotisham"
    bad = client.put("/api/astro/brand", json={"display_name": "X", "logo_url": "http://x"}, headers=h)
    assert bad.status_code == 400
