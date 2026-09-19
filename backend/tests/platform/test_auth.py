from conftest import login


def test_signup_grants_trial_once_per_account(client, fake):
    body, h = login(client, "u1", "device-aaaa", "ta")
    assert body["created"] and body["trial_granted"]
    assert body["user"]["balance_units"] == 1000 and body["user"]["lang"] == "ta"
    assert "device_hashes" not in body["user"]
    body2, _ = login(client, "u1", "device-bbbb", "kn")
    assert not body2["created"] and not body2["trial_granted"]
    assert body2["user"]["balance_units"] == 1000 and body2["user"]["lang"] == "kn"
    ledger = fake.children("users/u1/ledger")
    assert [e["type"] for e in ledger] == ["trial"]
    assert fake.data("rollups_daily/" + __import__("app.store").store.today_key())["signups"] == 1


def test_trial_once_per_device(client, fake):
    login(client, "u1", "shared-device-1")
    body, _ = login(client, "u2", "shared-device-1")
    assert body["created"] and not body["trial_granted"]
    assert body["user"]["balance_units"] == 0
    # raw device id never stored
    assert all("shared-device-1" not in str(d) for d in fake.docs.values())


def test_no_device_no_trial(client):
    body, _ = login(client, "u3", "")
    assert not body["trial_granted"]


def test_invalid_token_and_lang(client):
    r = client.post("/api/auth/firebase", json={"id_token": "garbage-token-xx"})
    assert r.status_code == 401 and r.json()["code"] == "forbidden"
    body, _ = login(client, "u4", "dev-12345678", "xx")
    assert body["user"]["lang"] == "te"  # DEFAULT_LANG


def test_me_and_patch(client):
    _, h = login(client)
    r = client.get("/api/me", headers=h)
    assert r.status_code == 200 and r.json()["pricing"]["query_price_units"] == 1000
    r = client.patch("/api/me", headers=h, json={"name": "Ravi", "lang": "hi", "role": "astrologer",
                                                 "notif_prefs": {"promos": True}})
    u = r.json()["user"]
    assert u["name"] == "Ravi" and u["lang"] == "hi" and u["role"] == "astrologer"
    assert u["notif_prefs"] == {"daily": True, "transits": True, "promos": True}
    assert client.patch("/api/me", headers=h, json={"lang": "fr"}).status_code == 400
    assert client.get("/api/me").status_code == 401


def test_fcm_token_dedup_and_cap(client, fake):
    _, h = login(client)
    for i in range(12):
        client.post("/api/me/fcm-token", headers=h, json={"token": "token-%02d-xxxxxx" % i})
    client.post("/api/me/fcm-token", headers=h, json={"token": "token-11-xxxxxx"})
    toks = fake.data("users/u1")["fcm_tokens"]
    assert len(toks) == 10 and toks[-1] == "token-11-xxxxxx" and len(set(toks)) == 10


def test_admin_login(client):
    r = client.post("/api/admin/login", json={"id_token": "tok:a1:boss@example.com"})
    assert r.status_code == 200
    from app import store
    assert store.require_admin("Bearer " + r.json()["token"]) == "boss@example.com"
    r = client.post("/api/admin/login", json={"id_token": "tok:a2:nobody@example.com"})
    assert r.status_code == 403


def test_signin_restores_soft_deleted_account(client, fake):
    _, h = login(client)
    assert client.delete("/api/me", headers=h).status_code == 200
    assert client.get("/api/me", headers=h).status_code == 404
    body, h2 = login(client)
    assert body["user"]["deleted_at"] is None
    assert client.get("/api/me", headers=h2).status_code == 200
