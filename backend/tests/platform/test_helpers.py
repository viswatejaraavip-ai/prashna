import pytest
from fastapi import HTTPException


def test_verify_cron(monkeypatch):
    from app import platform_cron
    monkeypatch.delenv("CRON_INSECURE_DEV", raising=False)
    monkeypatch.setenv("CRON_AUDIENCES", "https://udhyath-123.asia-south1.run.app,https://x.com")
    monkeypatch.setenv("CRON_SA_EMAIL", "sched@p.iam.gserviceaccount.com")
    good = {"aud": "https://udhyath-123.asia-south1.run.app",
            "email": "sched@p.iam.gserviceaccount.com", "email_verified": True}
    monkeypatch.setattr(platform_cron, "_verify_token", lambda t: dict(good))
    assert platform_cron.verify_cron("Bearer abc")["email"] == good["email"]
    with pytest.raises(HTTPException) as e:
        platform_cron.verify_cron(None)
    assert e.value.status_code == 401
    monkeypatch.setattr(platform_cron, "_verify_token", lambda t: dict(good, aud="https://evil"))
    with pytest.raises(HTTPException) as e:
        platform_cron.verify_cron("Bearer abc")
    assert e.value.status_code == 403
    monkeypatch.setattr(platform_cron, "_verify_token", lambda t: dict(good, email="x@y.z"))
    with pytest.raises(HTTPException):
        platform_cron.verify_cron("Bearer abc")

    def boom(t):
        raise ValueError("bad sig")
    monkeypatch.setattr(platform_cron, "_verify_token", boom)
    with pytest.raises(HTTPException) as e:
        platform_cron.verify_cron("Bearer abc")
    assert e.value.status_code == 401
    monkeypatch.setenv("CRON_INSECURE_DEV", "1")
    monkeypatch.delenv("K_SERVICE", raising=False)
    assert platform_cron.verify_cron(None)["insecure"]
    monkeypatch.setenv("K_SERVICE", "udhyath")
    with pytest.raises(HTTPException):
        platform_cron.verify_cron(None)


def test_send_push_prunes_dead_tokens_and_honours_prefs(fake, monkeypatch):
    from app import platform_push

    class UnregisteredError(Exception):
        pass

    fake.collection("users").document("u1").set({
        "uid": "u1", "deleted_at": None, "fcm_tokens": ["good", "dead"],
        "notif_prefs": {"daily": True, "promos": False}})
    sent = {}

    def fake_send(tokens, title, body, data):
        sent.update(tokens=tokens, data=data)
        return [None if t == "good" else UnregisteredError() for t in tokens]

    monkeypatch.setattr(platform_push, "_send", fake_send)
    assert platform_push.send_push("u1", "T", "B", {"n": 1}, category="daily") == 1
    assert sent["data"] == {"n": "1"}
    assert fake.data("users/u1")["fcm_tokens"] == ["good"]
    assert platform_push.send_push("u1", "T", "B", category="promos") == 0
    assert platform_push.send_push("missing", "T", "B") == 0


def test_storage_paths(monkeypatch):
    from app import platform_storage
    monkeypatch.setattr(platform_storage, "GCS_BUCKET", "bkt")
    assert platform_storage._split("users/u1/a.pdf") == ("bkt", "users/u1/a.pdf")
    assert platform_storage._split("gs://other/x/y.png") == ("other", "x/y.png")

    class Blob:
        def __init__(self, name):
            self.name = name

        def upload_from_string(self, data, content_type):
            self.data = (data, content_type)

    class Bucket:
        def blob(self, name):
            return Blob(name)

    class Client:
        def bucket(self, name):
            assert name == "bkt"
            return Bucket()

    monkeypatch.setattr(platform_storage, "_client", Client())
    assert platform_storage.upload_bytes("/users/u1/a.pdf", b"%PDF", "application/pdf") \
        == "gs://bkt/users/u1/a.pdf"


def test_error_body_has_code(fake):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app import billing, store
    app = FastAPI()
    store.install_error_handlers(app)

    @app.get("/x")
    def x():
        raise billing.InsufficientBalance(1000, 5)

    @app.get("/y")
    def y():
        raise HTTPException(404, "nope")

    c = TestClient(app)
    assert c.get("/x").json() == {"detail": "Insufficient balance: need 1000 paise, have 5",
                                  "code": "insufficient_balance", "needed_units": 1000,
                                  "balance_units": 5}
    assert c.get("/y").json() == {"detail": "nope", "code": "not_found"}


def test_legacy_modules_still_import():
    import importlib
    for mod in ("app.billing", "app.auth", "app.db", "app.config"):
        importlib.import_module(mod)
    from app import billing
    assert billing.question_fee_units(True) > 0 and callable(billing.record_usage)
