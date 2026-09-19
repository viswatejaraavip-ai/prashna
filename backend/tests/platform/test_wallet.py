import pytest

from conftest import login


def _user(fake, uid="u1", balance=0, **extra):
    fake.collection("users").document(uid).set(
        dict({"uid": uid, "balance_units": balance, "deleted_at": None}, **extra))


def test_charge_credit_refund_and_ledger(fake):
    from app import billing
    _user(fake, balance=500)
    assert billing.credit("u1", 1000, "topup", "pay1") == 1500
    assert billing.charge("u1", 1000, "query", "trace1") == 500
    assert billing.refund("u1", 1000, "trace1", "failed") == 1500
    ledger = sorted(fake.children("users/u1/ledger"), key=lambda e: e["created_at"])
    assert [e["type"] for e in ledger] == ["topup", "query", "refund"]
    assert [e["delta_units"] for e in ledger] == [1000, -1000, 1000]
    assert ledger[-1]["balance_after"] == 1500
    assert fake.data("users/u1")["balance_units"] == 1500


def test_charge_refuses_to_go_negative(fake):
    from app import billing
    _user(fake, balance=999)
    with pytest.raises(billing.InsufficientBalance) as exc:
        billing.charge("u1", 1000, "query", "t")
    assert exc.value.status_code == 402 and exc.value.needed_units == 1000
    assert fake.data("users/u1")["balance_units"] == 999
    assert fake.children("users/u1/ledger") == []


def test_idempotency_key(fake):
    from app import billing
    _user(fake, balance=0)
    assert billing.credit("u1", 500, "topup", "x", idem_key="pay:1") == 500
    assert billing.credit("u1", 500, "topup", "x", idem_key="pay:1") == 500
    assert len(fake.children("users/u1/ledger")) == 1


def test_validation_and_deleted_accounts(fake):
    from app import billing
    _user(fake, balance=100)
    with pytest.raises(ValueError):
        billing.charge("u1", 0, "query")
    with pytest.raises(ValueError):
        billing.charge("u1", 10, "bogus")
    with pytest.raises(TypeError):  # new-path callers must pass a ledger type
        billing.charge("u1", 10)
    _user(fake, uid="gone", balance=100, deleted_at="2026-01-01T00:00:00+00:00")
    with pytest.raises(billing.AccountNotFound):
        billing.credit("gone", 10, "refund")


def test_adjust_admin(fake):
    from app import billing
    _user(fake, balance=100)
    assert billing.adjust("u1", -100, "chargeback", "boss@example.com") == 0
    with pytest.raises(billing.InsufficientBalance):
        billing.adjust("u1", -1, "x", "boss@example.com")


def test_effective_plan():
    from app import billing
    assert billing.effective_plan({"plan": "pro", "plan_expires_at": "2999-01-01"}) == "pro"
    assert billing.effective_plan({"plan": "pro", "plan_expires_at": "2000-01-01"}) == "free"
    assert billing.effective_plan({}) == "free"


def test_pro_plan_purchase_stacks(client, fake):
    _, h = login(client)
    fake.document("users/u1").update({"balance_units": 49900 * 2 + 5})
    r1 = client.post("/api/plan/pro/purchase", headers=h).json()
    r2 = client.post("/api/plan/pro/purchase", headers=h).json()
    assert r2["balance_units"] == 5
    assert r2["plan_expires_at"] > r1["plan_expires_at"]
    r3 = client.post("/api/plan/pro/purchase", headers=h)
    assert r3.status_code == 402 and r3.json()["code"] == "insufficient_balance"
    me = client.get("/api/me", headers=h).json()["user"]
    assert me["plan"] == "pro"
    types = sorted(e["type"] for e in fake.children("users/u1/ledger"))
    assert types == ["subscription", "subscription", "trial"]
