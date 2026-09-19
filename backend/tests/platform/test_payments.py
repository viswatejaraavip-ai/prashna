import pytest

from conftest import login

TOKEN = "play-token-abcdefghijklmnop.1234"


@pytest.fixture
def play(monkeypatch):
    from app import platform_wallet
    state = {"purchase": {"purchaseState": 0, "consumptionState": 0, "orderId": "GPA.1",
                          "purchaseType": 0}, "consumed": 0, "fail_consume": False}

    def get(pid, token):
        return dict(state["purchase"])

    def consume(pid, token):
        if state["fail_consume"]:
            raise RuntimeError("boom")
        state["consumed"] += 1
        state["purchase"]["consumptionState"] = 1

    monkeypatch.setattr(platform_wallet, "play_get_purchase", get)
    monkeypatch.setattr(platform_wallet, "play_consume", consume)
    return state


def test_play_verify_credits_once_and_consumes(client, fake, play):
    _, h = login(client)
    r = client.post("/api/wallet/play/verify", headers=h,
                    json={"product_id": "wallet_200", "purchase_token": TOKEN})
    assert r.status_code == 200, r.text
    assert r.json()["credited"] and r.json()["balance_units"] == 1000 + 20000
    assert play["consumed"] == 1
    assert fake.data("payments/" + TOKEN)["status"] == "consumed"
    r = client.post("/api/wallet/play/verify", headers=h,
                    json={"product_id": "wallet_200", "purchase_token": TOKEN})
    assert r.json()["already_processed"] and r.json()["balance_units"] == 21000
    topups = [e for e in fake.children("users/u1/ledger") if e["type"] == "topup"]
    assert len(topups) == 1


def test_play_consume_retry(client, fake, play):
    _, h = login(client)
    play["fail_consume"] = True
    client.post("/api/wallet/play/verify", headers=h,
                json={"product_id": "wallet_100", "purchase_token": TOKEN})
    assert fake.data("payments/" + TOKEN)["status"] == "credited"
    play["fail_consume"] = False
    r = client.post("/api/wallet/play/verify", headers=h,
                    json={"product_id": "wallet_100", "purchase_token": TOKEN})
    assert r.json()["already_processed"] and play["consumed"] == 1
    assert fake.data("payments/" + TOKEN)["status"] == "consumed"
    assert fake.data("users/u1")["balance_units"] == 1000 + 10000


def test_play_rejections(client, play):
    from app import platform_wallet
    _, h = login(client)
    _, h2 = login(client, "u2", "device-2222")
    r = client.post("/api/wallet/play/verify", headers=h,
                    json={"product_id": "wallet_999", "purchase_token": TOKEN})
    assert r.status_code == 400
    play["purchase"]["obfuscatedExternalAccountId"] = platform_wallet.account_hash("u1")
    r = client.post("/api/wallet/play/verify", headers=h2,
                    json={"product_id": "wallet_100", "purchase_token": TOKEN})
    assert r.status_code == 409
    play["purchase"]["purchaseState"] = 2
    r = client.post("/api/wallet/play/verify", headers=h,
                    json={"product_id": "wallet_100", "purchase_token": TOKEN})
    assert r.status_code == 409
    play["purchase"]["purchaseState"] = 0
    assert client.post("/api/wallet/play/verify", headers=h, json={
        "product_id": "wallet_100", "purchase_token": TOKEN}).status_code == 200
    # the same token can't be replayed by another account
    r = client.post("/api/wallet/play/verify", headers=h2,
                    json={"product_id": "wallet_100", "purchase_token": TOKEN})
    assert r.status_code == 409


class _FakeRzp:
    class errors:
        class SignatureVerificationError(Exception):
            pass

    def __init__(self):
        outer = self

        class Order:
            def create(self, data):
                outer.last = data
                return {"id": "order_1"}

        class Utility:
            def verify_payment_signature(self, d):
                if d["razorpay_signature"] != "good":
                    raise _FakeRzp.errors.SignatureVerificationError()

            def verify_webhook_signature(self, payload, sig, secret):
                if sig != "good":
                    raise _FakeRzp.errors.SignatureVerificationError()

        self.order = Order()
        self.utility = Utility()


def test_razorpay_flow(client, fake, monkeypatch):
    import sys
    import json
    from app import platform_wallet
    rzp = _FakeRzp()
    monkeypatch.setattr(platform_wallet, "RAZORPAY_KEY_ID", "rzp_test")
    monkeypatch.setattr(platform_wallet, "RAZORPAY_WEBHOOK_SECRET", "whsec")
    monkeypatch.setattr(platform_wallet, "_razorpay", lambda: rzp)
    monkeypatch.setitem(sys.modules, "razorpay", _FakeRzp)
    _, h = login(client)
    assert client.post("/api/wallet/razorpay/order", headers=h,
                       json={"amount_rupees": 150}).status_code == 400
    r = client.post("/api/wallet/razorpay/order", headers=h, json={"amount_rupees": 500})
    assert r.json() == {"order_id": "order_1", "key_id": "rzp_test", "amount_units": 50000,
                        "currency": "INR"}
    bad = client.post("/api/wallet/razorpay/verify", headers=h,
                      json={"order_id": "order_1", "payment_id": "pay_1", "signature": "bad"})
    assert bad.status_code == 400
    ok = client.post("/api/wallet/razorpay/verify", headers=h,
                     json={"order_id": "order_1", "payment_id": "pay_1", "signature": "good"})
    assert ok.json()["balance_units"] == 51000
    event = {"event": "payment.captured",
             "payload": {"payment": {"entity": {"order_id": "order_1", "id": "pay_1"}}}}
    r = client.post("/api/billing/webhook", content=json.dumps(event),
                    headers={"x-razorpay-signature": "good"})
    assert r.status_code == 200
    assert fake.data("users/u1")["balance_units"] == 51000  # no double credit
    # unknown (legacy) orders are acknowledged, not errors
    event["payload"]["payment"]["entity"]["order_id"] = "order_legacy"
    assert client.post("/api/billing/webhook", content=json.dumps(event),
                       headers={"x-razorpay-signature": "good"}).status_code == 200


def test_pricing(client):
    p = client.get("/api/pricing").json()
    assert [x["product_id"] for x in p["play_products"]] == [
        "wallet_100", "wallet_200", "wallet_500", "wallet_1000"]
    assert p["play_products"][0]["amount_units"] == 10000
    assert p["pro_plan_units"] == 49900 and p["pro_plan_days"] == 30
