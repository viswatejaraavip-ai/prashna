"""Flow: first launch — sign-up (phone OTP and Google), the free trial,
language choice, the terms/disclaimer version gate, profile of the account
itself (/api/me), push tokens, pricing and the legal documents.

CONTRACT.md -> "Platform (auth, wallet, compliance)".
"""

import pytest

from conftest import ADMIN_EMAIL, LANGS


# ---------------------------------------------------------------- sign-up --

def test_phone_signup_creates_user_and_grants_trial(api):
    body, h = api.signup("u-phone", device="pixel-8-abc123", lang="te")
    assert body["created"] is True and body["trial_granted"] is True
    user = body["user"]
    assert user["uid"] == "u-phone"
    assert user["phone"].startswith("+91") and user["email"] == ""
    assert user["lang"] == "te" and user["role"] == "user" and user["plan"] == "free"
    assert user["balance_units"] == 1000          # TRIAL_CREDIT_UNITS
    assert user["trial_claimed"] is True
    # private fields never leave the server
    assert "device_hashes" not in user and "fcm_tokens" not in user

    assert api.ledger_types("u-phone") == ["trial"]
    entry = api.db.data("users/u-phone/ledger/trial")
    assert entry["delta_units"] == 1000 and entry["balance_after"] == 1000
    assert api.rollup()["signups"] == 1 and api.rollup()["trials"] == 1

    me = api.client.get("/api/me", headers=h)
    assert me.status_code == 200
    assert set(me.json()) == {"user", "pricing"}
    assert me.json()["user"]["uid"] == "u-phone"


def test_google_signup_records_the_verified_email(api):
    body, h = api.signup("u-google", device="oneplus-xyz999", lang="hi",
                         email="devotee@gmail.com")
    assert body["created"] and body["user"]["email"] == "devotee@gmail.com"
    assert body["user"]["lang"] == "hi"
    assert api.db.data("users/u-google")["sign_in_provider"] == "google.com"


def test_trial_granted_once_per_account_and_once_per_device(api):
    body, _ = api.signup("u1", device="shared-device-1")
    assert body["trial_granted"] is True
    # same account, second sign-in
    body, _ = api.signup("u1", device="shared-device-1")
    assert body["created"] is False and body["trial_granted"] is False
    assert api.db.data("users/u1")["balance_units"] == 1000
    # different account on the SAME device: device lock denies the trial
    body, _ = api.signup("u2", device="shared-device-1")
    assert body["created"] is True and body["trial_granted"] is False
    assert body["user"]["balance_units"] == 0
    # a fresh device gets it
    body, _ = api.signup("u3", device="another-device-9")
    assert body["trial_granted"] is True


def test_rejected_firebase_token_is_401_forbidden(api):
    r = api.client.post("/api/auth/firebase",
                        json={"id_token": "bad-token", "device_id": "d-1234567", "lang": "te"})
    assert r.status_code == 401
    assert r.json()["code"] == "forbidden"


def test_protected_routes_need_a_token(api):
    assert api.client.get("/api/me").status_code == 401
    assert api.client.get("/api/me",
                          headers={"Authorization": "Bearer nonsense"}).status_code == 401


def test_unknown_account_is_404_not_found(api):
    r = api.client.get("/api/me", headers=api.auth("ghost"))
    assert r.status_code == 404 and r.json()["code"] == "not_found"


# ------------------------------------------------------------------- me ----

@pytest.mark.parametrize("lang", LANGS)
def test_language_choice_is_saved_and_returned(api, lang):
    _, h = api.signup("u-lang-" + lang, device="dev-" + lang + "-0001", lang=lang)
    assert api.client.get("/api/me", headers=h).json()["user"]["lang"] == lang


def test_patch_me_name_lang_role_and_notifications(api):
    _, h = api.signup("u1")
    r = api.client.patch("/api/me", headers=h, json={
        "name": "  Ravi Kumar  ", "lang": "ta", "role": "astrologer",
        "notif_prefs": {"promos": True}})
    assert r.status_code == 200, r.text
    user = r.json()["user"]
    assert user["name"] == "Ravi Kumar" and user["lang"] == "ta"
    assert user["role"] == "astrologer"
    assert user["notif_prefs"] == {"daily": True, "transits": True, "promos": True}

    bad = api.client.patch("/api/me", headers=h, json={"lang": "fr"})
    assert bad.status_code == 400 and bad.json()["code"] == "invalid"
    bad = api.client.patch("/api/me", headers=h, json={"role": "guru"})
    assert bad.status_code == 400 and bad.json()["code"] == "invalid"


def test_fcm_token_registration_is_idempotent(api):
    _, h = api.signup("u1")
    tok = "fcm-token-" + "a" * 40
    assert api.client.post("/api/me/fcm-token", headers=h, json={"token": tok}).json() \
        == {"ok": True, "devices": 1}
    assert api.client.post("/api/me/fcm-token", headers=h, json={"token": tok}).json()["devices"] == 1
    assert api.client.post("/api/me/fcm-token", headers=h,
                           json={"token": tok + "2"}).json()["devices"] == 2
    assert api.db.data("users/u1")["fcm_tokens"] == [tok, tok + "2"]


# ------------------------------------------------- terms / disclaimer gate --

def test_terms_version_gate(api):
    from app.platform_legal import TERMS_VERSION
    body, h = api.signup("u1")
    user = body["user"]
    assert user["terms_version_required"] == TERMS_VERSION
    assert user["terms_accepted"] is False

    # Accepting an OLD version does not satisfy the gate.
    r = api.client.post("/api/me/disclaimer", headers=h, json={"version": "1"})
    assert r.status_code == 200 and r.json()["disclaimer_version"] == "1"
    assert api.client.get("/api/me", headers=h).json()["user"]["terms_accepted"] is False

    # Accepting the current version (empty body = current) does.
    r = api.client.post("/api/me/disclaimer", headers=h, json={})
    assert r.json()["disclaimer_version"] == TERMS_VERSION
    assert r.json()["disclaimer_accepted_at"]
    me = api.client.get("/api/me", headers=h).json()["user"]
    assert me["terms_accepted"] is True


@pytest.mark.parametrize("doc", ["terms", "privacy", "refund", "disclaimer"])
def test_legal_documents_in_every_language(api, doc):
    for lang in LANGS:
        r = api.client.get("/api/legal/%s?lang=%s" % (doc, lang))
        assert r.status_code == 200, r.text
        body = r.json()
        assert set(body) >= {"title", "body_markdown", "lang"}
        assert body["lang"] == lang
        assert body["title"] and len(body["body_markdown"]) > 200
        assert "{{" not in body["body_markdown"]


def test_unknown_legal_document_is_404(api):
    r = api.client.get("/api/legal/eula")
    assert r.status_code == 404 and r.json()["code"] == "not_found"


def test_public_policy_pages_render_html(api):
    r = api.client.get("/legal/privacy")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert "<h1" in r.text or "<h2" in r.text


# --------------------------------------------------------------- pricing ----

def test_pricing_matches_the_contract(api):
    from app import platform_wallet
    r = api.client.get("/api/pricing")
    assert r.status_code == 200
    p = r.json()
    assert p["query_price_units"] == 1000              # flat Rs 10 per answer
    from app import reports
    # The advertised price must be the price the wallet debits, in the caller's language.
    assert p["report_price_units"] == reports.report_fee_units("te") > 0
    assert p["pro_plan_units"] == 49900 and p["pro_plan_days"] == 30
    assert [o["amount_rupees"] for o in p["topup_options"]] == [100, 200, 500, 1000]
    assert {pp["product_id"] for pp in p["play_products"]} == {
        "wallet_100", "wallet_200", "wallet_500", "wallet_1000"}
    for opt in p["topup_options"]:
        assert opt["amount_units"] == opt["amount_rupees"] * 100
    assert p["currency"] == "INR"


def test_healthz_and_firebase_config(api):
    assert api.client.get("/healthz").json() == {"ok": True}
    cfg = api.client.get("/api/firebase-config").json()
    assert set(cfg) >= {"apiKey", "authDomain", "projectId", "appId"}


def test_admin_login_rejects_non_operator_google_account(api):
    r = api.client.post("/api/admin/login", json={"id_token": "x:stranger@gmail.com"})
    assert r.status_code == 403 and r.json()["code"] == "forbidden"
    r = api.client.post("/api/admin/login", json={"id_token": "adm:" + ADMIN_EMAIL})
    assert r.status_code == 200 and r.json()["email"] == ADMIN_EMAIL


def test_me_quotes_the_report_price_in_the_users_language(api):
    """Regression: /api/me fed the app a language-less price, so the app
    showed the most expensive language's report price to everyone."""
    from app import reports
    for lang in ("en", "te", "kn"):
        _, h = api.signup("u-price-" + lang, device="dev-price-" + lang, lang=lang)
        me = api.client.get("/api/me", headers=h).json()
        assert me["pricing"]["report_price_units"] == reports.report_fee_units(lang), lang
