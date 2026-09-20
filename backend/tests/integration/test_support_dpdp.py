"""Flow: support tickets and the DPDP rights — data export, account
deletion (soft delete now, hard purge after 30 days by the cron job) and
sign-in during the grace period.

CONTRACT.md -> "Platform": /api/support, /api/me/export, DELETE /api/me,
/internal/cron/purge-deleted.
"""



def busy_user(api, uid="u1"):
    """A user with everything the export has to contain."""
    from ai_fakes import FakeClaude, FakeGemini
    _, h = api.signup(uid, device="dev-" + uid + "-dpdp", lang="te")
    api.topup(uid, 50000)
    p = api.profile(h)
    sid = api.session(h, p["id"])
    api.set_models(FakeGemini(), FakeClaude(lang="te"))
    trace_id = api.client.post("/api/sessions/%s/ask" % sid, headers=h,
                               json={"text": "నా ఉద్యోగం?"}).json()["trace_id"]
    api.client.post("/api/support", headers=h,
                    json={"category": "payment", "message": "Wallet did not update"})
    api.client.post("/api/refunds", headers=h, json={"ref": trace_id, "reason": "off topic"})
    api.client.post("/api/wallet/play/verify", headers=h, json={
        "product_id": "wallet_100", "purchase_token": "play-token-" + "z" * 20})
    return h, p, sid, trace_id


# --------------------------------------------------------------- support ----

def test_support_ticket_round_trip(api):
    _, h = api.signup("u1")
    r = api.client.post("/api/support", headers=h,
                        json={"category": "answer_quality",
                              "message": "The answer was in the wrong language"})
    assert r.status_code == 200, r.text
    t = r.json()
    assert t["status"] == "open" and t["category"] == "answer_quality"
    assert t["replies"] == [] and t["uid"] == "u1" and t["id"]

    mine = api.client.get("/api/support", headers=h).json()["tickets"]
    assert [x["id"] for x in mine] == [t["id"]]

    # an unknown category falls back to "other"
    other = api.client.post("/api/support", headers=h,
                            json={"category": "aliens", "message": "hello there"})
    assert other.json()["category"] == "other"

    short = api.client.post("/api/support", headers=h,
                            json={"category": "other", "message": "x"})
    assert short.status_code == 422


def test_operator_reply_and_resolve(api):
    _, h = api.signup("u1")
    api.client.post("/api/me/fcm-token", headers=h, json={"token": "fcm-" + "d" * 40})
    tid = api.client.post("/api/support", headers=h,
                          json={"category": "payment", "message": "Where is my money"}
                          ).json()["id"]
    ah = api.admin()
    listed = api.client.get("/api/admin/support", headers=ah).json()["tickets"]
    assert [x["id"] for x in listed] == [tid]

    # a reply alone leaves the ticket open
    r = api.client.post("/api/admin/support/%s/reply" % tid, headers=ah,
                        json={"message": "Looking into it"})
    assert r.status_code == 200, r.text
    assert api.client.get("/api/support", headers=h).json()["tickets"][0]["status"] == "open"

    r = api.client.post("/api/admin/support/%s/reply" % tid, headers=ah,
                        json={"message": "Credited, sorry for the delay", "resolve": True})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "resolved"
    mine = api.client.get("/api/support", headers=h).json()["tickets"][0]
    assert mine["status"] == "resolved"
    # the user can read both replies back (see TESTING.md on the two reply shapes)
    texts = [x.get("message") or x.get("text") for x in mine["replies"]]
    assert texts == ["Looking into it", "Credited, sorry for the delay"]

    assert api.client.post("/api/admin/support/nope/reply", headers=ah,
                           json={"message": "hi"}).status_code == 404


# ---------------------------------------------------------------- export ----

def test_dpdp_export_contains_everything_and_no_secrets(api):
    h, p, sid, trace_id = busy_user(api)
    r = api.client.get("/api/me/export", headers=h)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["exported_at"]
    assert data["user"]["uid"] == "u1"
    # private columns are stripped
    assert "device_hashes" not in data["user"] and "fcm_tokens" not in data["user"]

    assert [x["id"] for x in data["profiles"]] == [p["id"]]
    assert [x["id"] for x in data["sessions"]] == [sid]
    assert len(data["sessions"][0]["messages"]) == 2
    assert {"trial", "topup", "query"} <= {e["type"] for e in data["ledger"]}
    assert data["support_tickets"] and data["refunds"]
    assert data["payments"] and all("raw" not in pay for pay in data["payments"])
    assert "ai_memory" in data and "astro_brand" in data


# -------------------------------------------------------------- deletion ----

def test_soft_delete_hides_the_account_and_sign_in_restores_it(api):
    h, p, sid, _ = busy_user(api)
    r = api.client.delete("/api/me", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] is True and r.json()["purge_after"]
    assert api.revoked == [("u1", False)]
    assert api.db.data("users/u1")["fcm_tokens"] == []

    # the account is invisible while soft-deleted
    assert api.client.get("/api/me", headers=h).status_code == 404
    assert api.client.get("/api/profiles", headers=h).status_code == 401

    # signing in again inside the 30-day grace period cancels the deletion
    body, h2 = api.signup("u1", device="dev-u1-dpdp")
    assert body["created"] is False
    assert api.client.get("/api/me", headers=h2).status_code == 200
    assert api.db.data("users/u1")["deleted_at"] is None
    assert [x["id"] for x in api.client.get("/api/profiles",
                                            headers=h2).json()["profiles"]] == [p["id"]]


def test_purge_cron_erases_only_accounts_past_the_grace_period(api, monkeypatch):
    from datetime import datetime, timedelta, timezone
    monkeypatch.setenv("CRON_INSECURE_DEV", "1")
    h, p, sid, _ = busy_user(api, "u1")
    h2, _, _, _ = busy_user(api, "u2")
    api.client.delete("/api/me", headers=h)
    api.client.delete("/api/me", headers=h2)

    # u1 asked 31 days ago, u2 yesterday
    old = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
    api.db.collection("users").document("u1").update({"deleted_at": old})

    r = api.client.post("/internal/cron/purge-deleted")
    assert r.status_code == 200, r.text
    assert r.json()["purged"] == 1

    assert api.db.data("users/u1") is None
    assert api.db.data("users/u1/profiles/" + p["id"]) is None
    assert api.db.data("sessions/" + sid) is None
    assert [d.to_dict()["uid"] for d in api.db.collection("traces").stream()
            if d.to_dict().get("uid") == "u1"] == []
    # payments are kept for tax law but pseudonymised
    pays = [d.to_dict() for d in api.db.collection("payments").stream()]
    erased = [x for x in pays if str(x["uid"]).startswith("erased:")]
    assert len(erased) == 1 and erased[0]["raw"] is None
    assert api.revoked[-1] == ("u1", True)

    # u2 is untouched
    assert api.db.data("users/u2") is not None


def test_purge_cron_also_downgrades_expired_pro_plans(api, monkeypatch):
    monkeypatch.setenv("CRON_INSECURE_DEV", "1")
    _, h = api.signup("u1")
    api.set_role("u1")
    api.set_pro("u1", days=-2)
    r = api.client.post("/internal/cron/purge-deleted")
    assert r.status_code == 200 and r.json()["plans_expired"] == 1
    assert api.db.data("users/u1")["plan"] == "free"
