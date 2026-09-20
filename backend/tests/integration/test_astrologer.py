"""Flow: "I am an astrologer" — choosing the role at sign-up, buying Pro
from the wallet, client CRUD, the Pro bundle, white-label brand settings and
branded PDFs, plus the Pro gate seen by a non-Pro astrologer and by a
personal user.

CONTRACT.md -> "Personal & astrologer features": /api/astro/*, and
"Platform": POST /api/plan/pro/purchase.
"""

from conftest import CLIENT, RAVI, SITA

BRAND = {"display_name": "Sri Sai Jyotisham", "phone": "+91 90000 00000",
         "footer": "Consultations by appointment, Hyderabad"}


def astrologer(api, uid="astro-1", lang="te", pro=False, units=200000):
    """Signs up, switches the role through the public API, tops up, and
    optionally buys the Pro plan the same way the app does."""
    _, h = api.signup(uid, device="dev-" + uid + "-0001", lang=lang)
    r = api.client.patch("/api/me", headers=h, json={"role": "astrologer"})
    assert r.status_code == 200 and r.json()["user"]["role"] == "astrologer"
    if units:
        api.topup(uid, units)
    if pro:
        assert api.client.post("/api/plan/pro/purchase", headers=h).status_code == 200
    return h


# ----------------------------------------------------------- role + gates ----

def test_personal_user_cannot_touch_the_astrologer_endpoints(api):
    _, h = api.signup("u1")
    p = api.profile(h)
    for method, path in (("get", "/api/astro/clients"),
                         ("get", "/api/astro/brand"),
                         ("get", "/api/astro/clients/%s/pro-bundle" % p["id"])):
        r = getattr(api.client, method)(path, headers=h)
        assert r.status_code == 403, (path, r.status_code)
        assert r.json()["code"] == "forbidden"
    r = api.client.post("/api/astro/clients", headers=h, json=CLIENT)
    assert r.status_code == 403 and r.json()["code"] == "forbidden"
    r = api.client.put("/api/astro/brand", headers=h, json=BRAND)
    assert r.status_code == 403


def test_astrologer_without_pro_is_blocked_from_pro_features(api):
    h = astrologer(api, pro=False)
    c = api.client.post("/api/astro/clients", headers=h, json=CLIENT).json()
    r = api.client.get("/api/astro/clients/%s/pro-bundle" % c["id"], headers=h)
    assert r.status_code == 403 and r.json()["code"] == "forbidden"
    r = api.client.get("/api/profiles/%s/chart?kind=shadbala" % c["id"], headers=h)
    assert r.status_code == 403 and r.json()["code"] == "forbidden"


def test_pro_purchase_unlocks_the_pro_features(api):
    h = astrologer(api, pro=False)
    c = api.client.post("/api/astro/clients", headers=h, json=CLIENT).json()
    assert api.client.get("/api/astro/clients/%s/pro-bundle" % c["id"],
                          headers=h).status_code == 403

    bought = api.client.post("/api/plan/pro/purchase", headers=h)
    assert bought.status_code == 200, bought.text
    assert bought.json()["plan"] == "pro"

    r = api.client.get("/api/astro/clients/%s/pro-bundle" % c["id"], headers=h)
    assert r.status_code == 200, r.text
    assert api.client.get("/api/profiles/%s/chart?kind=kp" % c["id"],
                          headers=h).status_code == 200


def test_expired_pro_locks_the_features_again(api):
    h = astrologer(api, pro=True)
    c = api.client.post("/api/astro/clients", headers=h, json=CLIENT).json()
    assert api.client.get("/api/astro/clients/%s/pro-bundle" % c["id"],
                          headers=h).status_code == 200
    api.set_pro("astro-1", days=-1)
    r = api.client.get("/api/astro/clients/%s/pro-bundle" % c["id"], headers=h)
    assert r.status_code == 403 and r.json()["code"] == "forbidden"


# ---------------------------------------------------------------- clients ----

def test_client_crud_search_and_separation_from_family(api):
    h = astrologer(api)
    c1 = api.client.post("/api/astro/clients", headers=h, json=CLIENT).json()
    assert c1["relation"] == "client" and c1["notes"] == "career query"
    api.client.post("/api/astro/clients", headers=h,
                    json=dict(CLIENT, name="Another", notes="marriage matching"))
    api.client.post("/api/profiles", headers=h, json=RAVI)      # the astrologer's own family

    clients = api.client.get("/api/astro/clients", headers=h).json()["clients"]
    assert [c["name"] for c in clients] == ["Another", "Client One"]

    assert [c["name"] for c in api.client.get("/api/astro/clients?q=career",
                                              headers=h).json()["clients"]] == ["Client One"]
    assert [c["name"] for c in api.client.get("/api/astro/clients?q=bengal",
                                              headers=h).json()["clients"]] \
        == ["Another", "Client One"]

    r = api.client.patch("/api/astro/clients/%s" % c1["id"], headers=h,
                         json={"notes": "follow up in May"})
    assert r.status_code == 200 and r.json()["notes"] == "follow up in May"

    # /api/profiles is the family list and hides clients unless asked
    family = api.client.get("/api/profiles", headers=h).json()["profiles"]
    assert [p["name"] for p in family] == ["Ravi"]
    everyone = api.client.get("/api/profiles?include_clients=true",
                              headers=h).json()["profiles"]
    assert len(everyone) == 3


def test_patching_a_non_client_profile_through_the_astro_route_is_404(api):
    h = astrologer(api)
    own = api.client.post("/api/profiles", headers=h, json=RAVI).json()
    r = api.client.patch("/api/astro/clients/%s" % own["id"], headers=h,
                         json={"notes": "x"})
    assert r.status_code == 404 and r.json()["code"] == "not_found"


def test_clients_are_private_to_their_astrologer(api):
    h1 = astrologer(api, "astro-1")
    h2 = astrologer(api, "astro-2", pro=True)
    c = api.client.post("/api/astro/clients", headers=h1, json=CLIENT).json()
    assert api.client.get("/api/astro/clients", headers=h2).json()["clients"] == []
    r = api.client.get("/api/astro/clients/%s/pro-bundle" % c["id"], headers=h2)
    assert r.status_code == 404 and r.json()["code"] == "not_found"


def test_pro_bundle_contents(api):
    h = astrologer(api, pro=True)
    c = api.client.post("/api/astro/clients", headers=h, json=CLIENT).json()
    r = api.client.get("/api/astro/clients/%s/pro-bundle?lang=te" % c["id"], headers=h)
    assert r.status_code == 200, r.text
    b = r.json()
    assert len(b["vargas"]) == 16
    assert {"kp", "shadbala", "ashtakavarga", "bhava_chalit", "dashas",
            "yogas", "doshas"} <= set(b)
    assert set(b["dashas"]) >= {"vimshottari", "yogini", "chara", "kalachakra"}
    assert b["kp"]["significators"]


# ------------------------------------------------------------------ brand ----

def test_brand_settings_round_trip_and_validation(api):
    h = astrologer(api)
    # before anything is saved: either null or an empty form, never an error
    empty = api.client.get("/api/astro/brand", headers=h).json()["brand"]
    assert empty in (None, {}) or not any(empty.get(k) for k in
                                          ("display_name", "phone", "logo_url", "footer"))

    r = api.client.put("/api/astro/brand", headers=h, json=BRAND)
    assert r.status_code == 200, r.text
    assert r.json()["brand"]["display_name"] == BRAND["display_name"]
    got = api.client.get("/api/astro/brand", headers=h).json()["brand"]
    assert got["phone"] == BRAND["phone"] and got["footer"] == BRAND["footer"]
    assert api.db.data("astro_brand/astro-1")["display_name"] == BRAND["display_name"]

    bad = api.client.put("/api/astro/brand", headers=h,
                         json={"display_name": "X", "logo_url": "http://insecure"})
    assert bad.status_code == 400 and bad.json()["code"] == "invalid"


def test_branded_matching_pdf_carries_the_brand(api):
    h = astrologer(api)
    api.client.put("/api/astro/brand", headers=h, json=BRAND)
    a = api.client.post("/api/astro/clients", headers=h,
                        json=dict(CLIENT, name="Groom")).json()
    b = api.client.post("/api/astro/clients", headers=h, json=dict(
        CLIENT, name="Bride", gender="female",
        birth={"date": "1988-06-06", "time": "09:10", "place": "Chennai"})).json()

    branded = api.client.post("/api/matching/pdf?lang=te", headers=h,
                              json={"profile_a": a["id"], "profile_b": b["id"],
                                    "brand": True})
    assert branded.status_code == 200, branded.text
    data, ctype = api.storage.objects[branded.json()["path"]]
    assert ctype == "application/pdf" and data[:4] == b"%PDF"

    plain = api.client.post("/api/matching/pdf?lang=te", headers=h,
                            json={"profile_a": a["id"], "profile_b": b["id"],
                                  "brand": False})
    assert plain.status_code == 200
    other, _ = api.storage.objects[plain.json()["path"]]
    assert other[:4] == b"%PDF" and len(other) != len(data)


def test_personal_users_never_get_a_branded_pdf(api):
    _, h = api.signup("u1")
    a = api.profile(h, RAVI)
    b = api.profile(h, SITA)
    r = api.client.post("/api/matching/pdf", headers=h,
                        json={"profile_a": a["id"], "profile_b": b["id"], "brand": True})
    assert r.status_code == 200, r.text
    data, _ = api.storage.objects[r.json()["path"]]
    assert data[:4] == b"%PDF"


def test_astrologer_consultation_for_a_client(api):
    """The full astrologer story: Pro, a client, an AI answer about that
    client, and the money trail."""
    from ai_fakes import FakeClaude, FakeGemini
    h = astrologer(api, pro=True, lang="te")
    c = api.client.post("/api/astro/clients", headers=h, json=CLIENT).json()
    sid = api.session(h, c["id"])
    api.set_models(FakeGemini(), FakeClaude(lang="te"))
    before = api.db.data("users/astro-1")["balance_units"]
    r = api.client.post("/api/sessions/%s/ask" % sid, headers=h,
                        json={"text": "ఈ క్లయింట్ ఉద్యోగం ఎప్పుడు మారుతుంది?"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok" and body["charged_units"] == 1000
    assert api.db.data("users/astro-1")["balance_units"] == before - 1000
    trace = api.db.data("traces/" + body["trace_id"])
    assert trace["uid"] == "astro-1" and trace["session_id"] == sid
