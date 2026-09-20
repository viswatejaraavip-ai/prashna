"""Flow: money — Google Play top-ups (Android Publisher verification mocked
at the API-client boundary), Razorpay orders/verification/webhook, the
ledger, refund requests and the astrologer Pro plan purchase.

CONTRACT.md -> "Platform (auth, wallet, compliance)".
"""

import json

from conftest import FakeRazorpay

PLAY_TOKEN = "play-token-abcdefghijklmnopqrst.0001"


# ------------------------------------------------------------ Google Play ----

def test_play_purchase_credits_once_and_is_consumed(api):
    _, h = api.signup("u1")
    r = api.client.post("/api/wallet/play/verify", headers=h,
                        json={"product_id": "wallet_200", "purchase_token": PLAY_TOKEN})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["credited"] is True and body["amount_units"] == 20000
    assert body["balance_units"] == 1000 + 20000

    # the Android Publisher call was made for the right package/product/token
    assert api.play.last_get == {"package": "com.prashna.app",
                                 "product": "wallet_200", "token": PLAY_TOKEN}
    assert api.play.consumed == [("wallet_200", PLAY_TOKEN)]

    pay = api.db.data("payments/" + PLAY_TOKEN)
    assert pay["uid"] == "u1" and pay["provider"] == "play"
    assert pay["amount_units"] == 20000 and pay["status"] == "consumed"

    # replaying the same token never credits twice
    again = api.client.post("/api/wallet/play/verify", headers=h,
                            json={"product_id": "wallet_200", "purchase_token": PLAY_TOKEN})
    assert again.json()["already_processed"] is True
    assert again.json()["balance_units"] == 21000
    assert [e for e in api.db.children("users/u1/ledger")
            if e["type"] == "topup"].__len__() == 1


def test_play_consume_failure_is_retried_on_the_next_verify(api):
    _, h = api.signup("u1")
    api.play.fail_consume = True
    api.client.post("/api/wallet/play/verify", headers=h,
                    json={"product_id": "wallet_100", "purchase_token": PLAY_TOKEN})
    assert api.db.data("payments/" + PLAY_TOKEN)["status"] == "credited"
    api.play.fail_consume = False
    r = api.client.post("/api/wallet/play/verify", headers=h,
                        json={"product_id": "wallet_100", "purchase_token": PLAY_TOKEN})
    assert r.json()["already_processed"] is True
    assert api.db.data("payments/" + PLAY_TOKEN)["status"] == "consumed"
    assert api.db.data("users/u1")["balance_units"] == 1000 + 10000


def test_play_rejections(api):
    from app import platform_wallet
    _, h1 = api.signup("u1", device="dev-a0000001")
    _, h2 = api.signup("u2", device="dev-b0000002")

    bad_product = api.client.post("/api/wallet/play/verify", headers=h1,
                                  json={"product_id": "wallet_9999",
                                        "purchase_token": PLAY_TOKEN})
    assert bad_product.status_code == 400 and bad_product.json()["code"] == "invalid"

    short_token = api.client.post("/api/wallet/play/verify", headers=h1,
                                  json={"product_id": "wallet_100",
                                        "purchase_token": "short"})
    assert short_token.status_code == 422

    # a purchase bound to u1's obfuscated account id cannot be claimed by u2
    api.play.purchase["obfuscatedExternalAccountId"] = platform_wallet.account_hash("u1")
    r = api.client.post("/api/wallet/play/verify", headers=h2,
                        json={"product_id": "wallet_100", "purchase_token": PLAY_TOKEN})
    assert r.status_code == 409 and r.json()["code"] == "invalid"

    # pending payment
    api.play.purchase["purchaseState"] = 2
    r = api.client.post("/api/wallet/play/verify", headers=h1,
                        json={"product_id": "wallet_100", "purchase_token": PLAY_TOKEN})
    assert r.status_code == 409

    # cancelled purchase
    api.play.purchase["purchaseState"] = 1
    r = api.client.post("/api/wallet/play/verify", headers=h1,
                        json={"product_id": "wallet_100", "purchase_token": PLAY_TOKEN})
    assert r.status_code == 400

    # Google says the token is unknown
    api.play.purchase["purchaseState"] = 0
    api.play.unknown_token = True
    r = api.client.post("/api/wallet/play/verify", headers=h1,
                        json={"product_id": "wallet_100", "purchase_token": PLAY_TOKEN})
    assert r.status_code == 400 and r.json()["code"] == "invalid"
    assert api.db.data("users/u1")["balance_units"] == 1000     # nothing credited


# -------------------------------------------------------------- Razorpay ----

def test_razorpay_order_then_verify(api):
    _, h = api.signup("u1")
    r = api.client.post("/api/wallet/razorpay/order", headers=h,
                        json={"amount_rupees": 500})
    assert r.status_code == 200, r.text
    order = r.json()
    assert order["amount_units"] == 50000 and order["key_id"] == "rzp_test_key"
    oid = order["order_id"]
    assert api.db.data("payments/" + oid)["status"] == "created"

    bad = api.client.post("/api/wallet/razorpay/verify", headers=h,
                          json={"order_id": oid, "payment_id": "pay_1",
                                "signature": "forged"})
    assert bad.status_code == 400 and bad.json()["code"] == "invalid"
    assert api.db.data("users/u1")["balance_units"] == 1000

    ok = api.client.post("/api/wallet/razorpay/verify", headers=h,
                         json={"order_id": oid, "payment_id": "pay_1",
                               "signature": FakeRazorpay.signature(oid, "pay_1")})
    assert ok.status_code == 200, ok.text
    assert ok.json()["balance_units"] == 51000
    assert api.db.data("payments/" + oid)["status"] == "credited"

    # verify is idempotent (the webhook may also arrive)
    again = api.client.post("/api/wallet/razorpay/verify", headers=h,
                            json={"order_id": oid, "payment_id": "pay_1",
                                  "signature": FakeRazorpay.signature(oid, "pay_1")})
    assert again.json()["balance_units"] == 51000
    assert [e["type"] for e in api.db.children("users/u1/ledger")].count("topup") == 1


def test_razorpay_order_amount_must_be_a_listed_option(api):
    _, h = api.signup("u1")
    r = api.client.post("/api/wallet/razorpay/order", headers=h, json={"amount_rupees": 137})
    assert r.status_code == 400 and r.json()["code"] == "invalid"


def test_razorpay_order_belongs_to_its_buyer(api):
    _, h1 = api.signup("u1", device="dev-a1111111")
    _, h2 = api.signup("u2", device="dev-b2222222")
    oid = api.client.post("/api/wallet/razorpay/order", headers=h1,
                          json={"amount_rupees": 100}).json()["order_id"]
    r = api.client.post("/api/wallet/razorpay/verify", headers=h2,
                        json={"order_id": oid, "payment_id": "pay_x",
                              "signature": FakeRazorpay.signature(oid, "pay_x")})
    assert r.status_code == 403 and r.json()["code"] == "forbidden"


def test_razorpay_webhook_credits_the_order(api):
    _, h = api.signup("u1")
    oid = api.client.post("/api/wallet/razorpay/order", headers=h,
                          json={"amount_rupees": 100}).json()["order_id"]
    payload = json.dumps({"event": "payment.captured",
                          "payload": {"payment": {"entity": {"id": "pay_9",
                                                             "order_id": oid}}}})
    sig = FakeRazorpay.webhook_signature(payload, "rzp_hook_secret")
    r = api.client.post("/api/billing/webhook", content=payload,
                        headers={"x-razorpay-signature": sig,
                                 "content-type": "application/json"})
    assert r.status_code == 200 and r.json() == {"received": True}
    assert api.db.data("users/u1")["balance_units"] == 1000 + 10000

    bad = api.client.post("/api/billing/webhook", content=payload,
                          headers={"x-razorpay-signature": "nope",
                                   "content-type": "application/json"})
    assert bad.status_code == 400 and bad.json()["code"] == "invalid"


# ---------------------------------------------------------------- ledger ----

def test_ledger_lists_every_movement_newest_first(api):
    _, h = api.signup("u1")
    api.topup("u1", 50000, "manual")
    api.client.post("/api/wallet/play/verify", headers=h,
                    json={"product_id": "wallet_100", "purchase_token": PLAY_TOKEN})
    r = api.client.get("/api/wallet/ledger?limit=10", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["balance_units"] == 1000 + 50000 + 10000
    types = [e["type"] for e in body["entries"]]
    assert set(types) == {"trial", "topup"}
    for e in body["entries"]:
        assert {"type", "delta_units", "balance_after", "ref", "created_at", "id"} <= set(e)
    created = [e["created_at"] for e in body["entries"]]
    assert created == sorted(created, reverse=True)
    assert api.client.get("/api/wallet/ledger?limit=0", headers=h).status_code == 422


# --------------------------------------------------------------- refunds ----

def test_refund_request_for_a_real_charge(api):
    from ai_fakes import FakeClaude, FakeGemini
    _, h = api.signup("u1")
    api.topup("u1", 5000)
    p = api.profile(h)
    sid = api.session(h, p["id"])
    api.set_models(FakeGemini(), FakeClaude())
    trace_id = api.client.post("/api/sessions/%s/ask" % sid, headers=h,
                               json={"text": "career?"}).json()["trace_id"]

    r = api.client.post("/api/refunds", headers=h,
                        json={"ref": trace_id, "reason": "answer was not relevant"})
    assert r.status_code == 200, r.text
    ref = r.json()
    assert ref["status"] == "requested" and ref["amount_units"] == 1000
    assert ref["uid"] == "u1" and ref["id"]

    mine = api.client.get("/api/refunds", headers=h).json()["refunds"]
    assert [x["id"] for x in mine] == [ref["id"]]

    dup = api.client.post("/api/refunds", headers=h, json={"ref": trace_id, "reason": "again"})
    assert dup.status_code == 409 and dup.json()["code"] == "invalid"


def test_refund_for_an_unknown_charge_is_404(api):
    _, h = api.signup("u1")
    r = api.client.post("/api/refunds", headers=h, json={"ref": "no-such-charge"})
    assert r.status_code == 404 and r.json()["code"] == "not_found"


def test_too_many_open_refunds_is_rate_limited(api):
    from app import billing
    _, h = api.signup("u1")
    api.topup("u1", 100000)
    refs = []
    for i in range(6):
        billing.charge("u1", 1000, "query", "trace-%d" % i)
        refs.append("trace-%d" % i)
    for ref in refs[:5]:
        assert api.client.post("/api/refunds", headers=h,
                               json={"ref": ref}).status_code == 200
    r = api.client.post("/api/refunds", headers=h, json={"ref": refs[5]})
    assert r.status_code == 429 and r.json()["code"] == "rate_limited"


# ------------------------------------------------------- astrologer Pro -----

def test_pro_plan_purchase_from_the_wallet(api):
    _, h = api.signup("u1")
    api.set_role("u1")

    poor = api.client.post("/api/plan/pro/purchase", headers=h)
    assert poor.status_code == 402 and poor.json()["code"] == "insufficient_balance"

    api.topup("u1", 100000)
    r = api.client.post("/api/plan/pro/purchase", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["plan"] == "pro" and body["plan_expires_at"]
    assert body["balance_units"] == 1000 + 100000 - 49900

    user = api.client.get("/api/me", headers=h).json()["user"]
    assert user["plan"] == "pro" and user["plan_expires_at"] == body["plan_expires_at"]
    assert [e["type"] for e in api.db.children("users/u1/ledger")].count("subscription") == 1

    # buying again stacks on the unexpired plan
    first_expiry = body["plan_expires_at"]
    api.topup("u1", 60000)
    second = api.client.post("/api/plan/pro/purchase", headers=h).json()
    assert second["plan_expires_at"] > first_expiry
