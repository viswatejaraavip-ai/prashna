"""Integration-test harness: the real Prashna app (``app.main_gcp``) wired to
an in-memory Firestore and fake model / cloud clients.

Everything below the HTTP layer is the production code path — routers,
middleware, JWT auth, wallet, Firestore data layer, the Jyotish engine, the
PDF and share-card renderers, the guard and the AI pipeline. Only the things
that would leave the machine are faked:

    Firestore            tests/platform/platform_fakefs.py
    Gemini / Claude      tests/ai/ai_fakes.py
    Firebase Auth        verify_firebase_token below ("<uid>[:<email>]")
    Cloud Speech         transcribe / synthesize stubs, priced by ai/costs.py
    Cloud Storage        in-memory bucket (app.platform_storage)
    FCM                  platform_push._send
    Android Publisher    platform_wallet._publisher (googleapiclient shape)
    Razorpay             platform_wallet._razorpay

No network, no cloud credentials, no emulator. See docs/launch/TESTING.md.
"""

import hashlib
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
BACKEND = os.path.dirname(TESTS)
for _p in (BACKEND, os.path.join(TESTS, "platform"), os.path.join(TESTS, "ai")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

os.environ.setdefault("JWT_SECRET", "integration-test-secret-0123456789abcdef")
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "test-project")
os.environ.setdefault("TRIAL_CREDIT_UNITS", "1000")
os.environ.setdefault("DEFAULT_LANG", "te")
os.environ.pop("K_SERVICE", None)          # never look like Cloud Run

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from ai_fakes import FakeClaude, FakeGemini  # noqa: E402
from platform_fakefs import FakeFirestore  # noqa: E402

ADMIN_EMAIL = "owner@example.com"
LANGS = ("hi", "te", "ta", "kn", "ml", "en")

RAVI = {"name": "Ravi", "relation": "self", "gender": "male", "time_known": True,
        "birth": {"date": "1990-08-15", "time": "10:30", "place": "Hyderabad"}}
SITA = {"name": "Sita", "relation": "spouse", "gender": "female", "time_known": True,
        "birth": {"date": "1993-03-02", "time": "18:45", "lat": 13.0878, "lon": 80.2785,
                  "tz": "Asia/Kolkata", "place": "Chennai"}}
CLIENT = {"name": "Client One", "gender": "male", "notes": "career query",
          "birth": {"date": "1985-01-20", "time": "05:15", "place": "Bengaluru"}}


# ---------------------------------------------------------------- fakes ----

def make_verify(store):
    """Firebase ID token stand-in.

    ``"<uid>"``               phone OTP sign-in
    ``"<uid>:<email>"``       Google sign-in (verified email)
    ``"bad..."``              rejected, like an expired/forged token
    """

    def verify(id_token: str):
        if not id_token or id_token.startswith("bad"):
            raise store.ApiError(401, "Sign-in failed, please try again", "forbidden")
        parts = id_token.split(":")
        uid = parts[0]
        digits = int(hashlib.sha256(uid.encode()).hexdigest()[:6], 16) % 100000
        if len(parts) > 1 and "@" in parts[1]:
            return {"uid": uid, "email": parts[1].lower(), "email_verified": True,
                    "name": "Google User",
                    "firebase": {"sign_in_provider": "google.com"}}
        return {"uid": uid, "phone_number": "+9199%08d" % digits,
                "firebase": {"sign_in_provider": "phone"}}

    return verify


class FakeStorage:
    """In-memory stand-in for app.platform_storage."""

    GCS_BUCKET = "test-bucket"
    USER_PREFIXES = ("reports", "matching", "share", "users")

    def __init__(self):
        self.objects = {}

    def upload_bytes(self, path, data, content_type="application/octet-stream"):
        self.objects[path] = (data, content_type)
        return "gs://%s/%s" % (self.GCS_BUCKET, path)

    def signed_url(self, path, minutes=60):
        return "https://signed.example/%s?m=%d" % (path.replace("gs://%s/" % self.GCS_BUCKET, ""),
                                                   minutes)

    def delete_prefix(self, prefix):
        gone = [k for k in self.objects if k.startswith(prefix)]
        for k in gone:
            del self.objects[k]
        return len(gone)

    def as_module(self):
        mod = types.ModuleType("app.platform_storage")
        mod.GCS_BUCKET = self.GCS_BUCKET
        mod.USER_PREFIXES = self.USER_PREFIXES
        mod.upload_bytes = self.upload_bytes
        mod.signed_url = self.signed_url
        mod.delete_prefix = self.delete_prefix
        return mod


class FakePlay:
    """Android Publisher v3 stand-in with the googleapiclient call shape:
    ``_publisher().purchases().products().get(...).execute()``."""

    def __init__(self):
        self.purchase = {"purchaseState": 0, "consumptionState": 0,
                         "orderId": "GPA.3311-0000-0000-00001", "purchaseType": 0,
                         "purchaseTimeMillis": "1758000000000", "regionCode": "IN",
                         "acknowledgementState": 1}
        self.consumed = []
        self.fail_consume = False
        self.unknown_token = False

    # -- googleapiclient shape --
    def purchases(self):
        return self

    def products(self):
        return self

    def get(self, packageName, productId, token):
        outer = self

        class _Req:
            def execute(self):
                if outer.unknown_token:
                    raise RuntimeError("404 purchaseTokenNotFound")
                outer.last_get = {"package": packageName, "product": productId,
                                  "token": token}
                return dict(outer.purchase)
        return _Req()

    def consume(self, packageName, productId, token):
        outer = self

        class _Req:
            def execute(self):
                if outer.fail_consume:
                    raise RuntimeError("503 backendError")
                outer.consumed.append((productId, token))
                outer.purchase["consumptionState"] = 1
                return {}
        return _Req()


def _rzp_error(msg):
    import razorpay
    return razorpay.errors.SignatureVerificationError(msg)


class FakeRazorpay:
    """razorpay.Client stand-in: orders + signature verification.

    Raises the real ``razorpay.errors.SignatureVerificationError`` so the
    app's own except clause is the one under test."""

    def __init__(self):
        self.orders = {}
        self.n = 0
        outer = self

        class _Order:
            def create(self, data):
                outer.n += 1
                oid = "order_TEST%04d" % outer.n
                doc = dict(data, id=oid)
                outer.orders[oid] = doc
                return doc

        class _Utility:
            def verify_payment_signature(self, params):
                want = outer.signature(params["razorpay_order_id"],
                                       params["razorpay_payment_id"])
                if params.get("razorpay_signature") != want:
                    raise _rzp_error("bad signature")

            def verify_webhook_signature(self, payload, signature, secret):
                want = hashlib.sha256((secret + payload).encode()).hexdigest()
                if signature != want:
                    raise _rzp_error("bad signature")

        self.order = _Order()
        self.utility = _Utility()

    @staticmethod
    def signature(order_id, payment_id):
        return hashlib.sha256(("%s|%s" % (order_id, payment_id)).encode()).hexdigest()

    @staticmethod
    def webhook_signature(payload, secret):
        return hashlib.sha256((secret + payload).encode()).hexdigest()


# ------------------------------------------------------------- the app ----

class Api:
    """Handle returned by the ``api`` fixture."""

    def __init__(self, client, db, **kw):
        self.client = client
        self.db = db
        self.__dict__.update(kw)

    # -- auth helpers --
    def signup(self, uid="u1", device="device-00000001", lang="te", email=None):
        token = uid + (":" + email if email else "")
        r = self.client.post("/api/auth/firebase",
                             json={"id_token": token, "device_id": device, "lang": lang})
        assert r.status_code == 200, r.text
        return r.json(), self.headers(r.json()["token"])

    @staticmethod
    def headers(token):
        return {"Authorization": "Bearer " + token}

    def auth(self, uid="u1"):
        from app import store
        return self.headers(store.issue_token(uid))

    def admin(self, email=ADMIN_EMAIL, uid="admin-uid"):
        r = self.client.post("/api/admin/login", json={"id_token": uid + ":" + email})
        assert r.status_code == 200, r.text
        return self.headers(r.json()["token"])

    # -- data helpers --
    def topup(self, uid, units, ref="test-topup"):
        from app import billing
        return billing.credit(uid, units, "topup", ref)

    def set_role(self, uid, role="astrologer"):
        self.db.collection("users").document(uid).update({"role": role})

    def set_pro(self, uid, days=30):
        from datetime import datetime, timedelta, timezone
        self.db.collection("users").document(uid).update(
            {"plan": "pro",
             "plan_expires_at": (datetime.now(timezone.utc)
                                 + timedelta(days=days)).isoformat()})

    def profile(self, headers, body=None, **over):
        body = dict(body or RAVI, **over)
        r = self.client.post("/api/profiles", json=body, headers=headers)
        assert r.status_code == 200, r.text
        return r.json()

    def session(self, headers, profile_id, mode="text"):
        r = self.client.post("/api/sessions", headers=headers,
                             json={"profile_id": profile_id, "mode": mode})
        assert r.status_code == 200, r.text
        return r.json()["session_id"]

    def ledger_types(self, uid):
        return [d.to_dict()["type"] for d in
                self.db.collection("users").document(uid).collection("ledger").stream()]

    def rollup(self, day=None):
        from app import store
        return self.db.data("rollups_daily/" + (day or store.today_key())) or {}


@pytest.fixture
def api(monkeypatch):
    import app
    from app import (main_gcp, platform_auth, platform_push, platform_wallet,
                     reports, store)
    from app import guard
    from app.ai import costs, llm, speech
    from app.features import daily as daily_mod
    from app.features import translate as translate_mod

    # ---- Firestore ----
    db = FakeFirestore()
    monkeypatch.setattr(store, "_fs", db)
    monkeypatch.setattr(store, "run_transaction", db.run_transaction)
    monkeypatch.setattr(store, "ADMIN_EMAILS", {ADMIN_EMAIL})
    store.clear_flags_cache()

    # ---- process-global caches other suites may have warmed ----
    guard._hits.clear()
    daily_mod._MEM.clear()
    translate_mod._MEM.clear()

    # ---- Firebase Auth ----
    monkeypatch.setattr(platform_auth, "verify_firebase_token", make_verify(store))
    revoked = []
    monkeypatch.setattr(platform_auth, "revoke_and_delete_firebase_user",
                        lambda uid, hard=False: revoked.append((uid, hard)))

    # ---- models ----
    llm.reset_capabilities()
    gemini, claude = FakeGemini(), FakeClaude()
    monkeypatch.setattr(llm, "_gemini", gemini)
    monkeypatch.setattr(llm, "_claude", claude)

    def set_models(g=None, c=None):
        if g is not None:
            monkeypatch.setattr(llm, "_gemini", g)
        if c is not None:
            monkeypatch.setattr(llm, "_claude", c)

    # ---- cloud speech ----
    heard = {"text": "నా ఉద్యోగం ఎప్పుడు మారుతుంది?", "seconds": 8.0}

    def transcribe(data, lang):
        return heard["text"], llm.Stage(
            name="stt", model=speech.STT_MODEL, units=heard["seconds"],
            cost=costs.stt_cost(speech.STT_MODEL, heard["seconds"]))

    def synthesize(text, lang):
        name, tier = speech.voice_for(lang)
        return b"OggS-fake-audio", llm.Stage(name="tts", model=name, units=len(text),
                                             cost=costs.tts_cost(tier, len(text)))

    monkeypatch.setattr(speech, "transcribe", transcribe)
    monkeypatch.setattr(speech, "synthesize", synthesize)

    # ---- Cloud Storage ----
    storage = FakeStorage()
    storage_mod = storage.as_module()
    monkeypatch.setitem(sys.modules, "app.platform_storage", storage_mod)
    monkeypatch.setattr(app, "platform_storage", storage_mod, raising=False)

    # ---- FCM ----
    pushes = []

    def _send(tokens, title, body, data):
        pushes.append({"tokens": list(tokens), "title": title, "body": body, "data": data})
        return [None] * len(tokens)

    monkeypatch.setattr(platform_push, "_send", _send)

    # ---- Google Play / Razorpay ----
    play = FakePlay()
    monkeypatch.setattr(platform_wallet, "_publisher", lambda: play)
    razorpay = FakeRazorpay()
    monkeypatch.setattr(platform_wallet, "_razorpay", lambda: razorpay)
    monkeypatch.setattr(platform_wallet, "RAZORPAY_KEY_ID", "rzp_test_key")
    monkeypatch.setattr(platform_wallet, "RAZORPAY_KEY_SECRET", "rzp_test_secret")
    monkeypatch.setattr(platform_wallet, "RAZORPAY_WEBHOOK_SECRET", "rzp_hook_secret")

    # ---- reports: short chapters, one at a time, generated inline so the
    # HTTP flow is deterministic (production runs them in a thread pool) ----
    monkeypatch.setattr(reports, "REPORT_SECTION_WORDS", 300)
    monkeypatch.setattr(reports, "REPORT_CONCURRENCY", 1, raising=False)
    launched = []

    def launch(report_id):
        launched.append(report_id)
        if not getattr(launch, "paused", False):
            reports._generate(report_id)

    monkeypatch.setattr(reports, "_launch", launch)

    client = TestClient(main_gcp.app, raise_server_exceptions=False)
    return Api(client, db, storage=storage, play=play, razorpay=razorpay,
               pushes=pushes, gemini=gemini, claude=claude, set_models=set_models,
               heard=heard, revoked=revoked, launch=launch, launched=launched,
               monkeypatch=monkeypatch)
