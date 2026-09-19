from tests.features.conftest import RAVI, SITA, auth, make_user


def test_profile_crud(client, db):
    make_user(db)
    h = auth()
    r = client.post("/api/profiles", json=RAVI, headers=h)
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["birth"]["tz"] == "Asia/Kolkata"
    assert abs(p["birth"]["lat"] - 17.384) < 0.1 and p["birth"]["place"].startswith("Hyderabad")
    assert p["derived"]["moon_sign"] in range(12)
    pid = p["id"]

    assert client.get("/api/profiles/%s" % pid, headers=h).json()["name"] == "Ravi"
    r = client.patch("/api/profiles/%s" % pid, json={"notes": "eldest son", "name": "Ravi K"},
                     headers=h)
    assert r.status_code == 200 and r.json()["notes"] == "eldest son"
    # Changing birth time recomputes the derived summary
    r = client.patch("/api/profiles/%s" % pid, json={"birth": {"time": "22:10"}}, headers=h)
    assert r.json()["birth"]["time"] == "22:10" and r.json()["birth"]["place"].startswith("Hyderabad")

    r = client.post("/api/profiles", json=SITA, headers=h)
    assert r.status_code == 200
    lst = client.get("/api/profiles", headers=h).json()["profiles"]
    assert [x["relation"] for x in lst] == ["self", "spouse"]

    assert client.delete("/api/profiles/%s" % pid, headers=h).json() == {"ok": True}
    r = client.get("/api/profiles/%s" % pid, headers=h)
    assert r.status_code == 404 and r.json()["code"] == "not_found"


def test_profile_validation(client, db):
    make_user(db)
    h = auth()
    bad = dict(RAVI, birth={"date": "1990-13-45", "time": "10:30", "place": "Hyderabad"})
    r = client.post("/api/profiles", json=bad, headers=h)
    assert r.status_code == 400 and r.json()["code"] == "invalid"
    bad = dict(RAVI, birth={"date": "1990-01-01", "time": "25:00", "place": "Hyderabad"})
    assert client.post("/api/profiles", json=bad, headers=h).status_code == 400
    bad = dict(RAVI, birth={"date": "1990-01-01", "time": "10:00", "place": "Nowhereville Xyz"})
    assert client.post("/api/profiles", json=bad, headers=h).status_code == 400
    bad = dict(RAVI, relation="cousin")
    assert client.post("/api/profiles", json=bad, headers=h).status_code == 400
    # only one self profile
    assert client.post("/api/profiles", json=RAVI, headers=h).status_code == 200
    assert client.post("/api/profiles", json=RAVI, headers=h).status_code == 400


def test_time_unknown_uses_noon_and_flags_approx(client, db):
    make_user(db)
    h = auth()
    body = dict(RAVI, time_known=False, birth={"date": "1990-08-15", "place": "Hyderabad"})
    p = client.post("/api/profiles", json=body, headers=h).json()
    assert p["time_known"] is False and p["birth"]["time"] == "12:00"
    chart = client.get("/api/profiles/%s/chart?kind=rasi" % p["id"], headers=h).json()
    assert chart["approximate"] is True
    dashas = client.get("/api/profiles/%s/chart?kind=dashas" % p["id"], headers=h).json()
    assert dashas["approximate"] is False


def test_profiles_are_per_user(client, db):
    make_user(db, "u1")
    make_user(db, "u2")
    p = client.post("/api/profiles", json=RAVI, headers=auth("u1")).json()
    assert client.get("/api/profiles/%s" % p["id"], headers=auth("u2")).status_code == 404
    assert client.get("/api/profiles", headers={}).status_code == 401


def test_places(client, db):
    res = client.get("/api/places?q=vijayaw").json()
    assert res and res[0]["name"].lower().startswith("vijayawada")
    assert {"lat", "lon", "tz", "label"} <= set(res[0])


def test_place_search_in_indic_scripts():
    from app.features import places
    cases = {"హైదరాబాద్": "Hyderabad", "తిరుపతి": "Tirupati", "मुंबई": "Mumbai",
             "दिल्ली": "Delhi", "சென்னை": "Chennai", "ಬೆಂಗಳೂರು": "Bengaluru",
             "തിരുവനന്തപുരം": "Thiruvananthapuram", "लखनऊ": "Lucknow", "Hyder": "Hyderabad"}
    for q, want in cases.items():
        assert places.search(q, 3)[0]["name"] == want, q
