import sys
import types
from datetime import date

import pytest

from tests.features.conftest import RAVI, SITA, auth, make_user

LANGS = ("hi", "te", "ta", "kn", "ml", "en")


@pytest.fixture()
def storage(monkeypatch):
    import app
    saved = {}
    mod = types.ModuleType("app.platform_storage")

    def upload_bytes(path, data, content_type="application/octet-stream"):
        saved[path] = (data, content_type)
        return "gs://bucket/" + path

    mod.upload_bytes = upload_bytes
    mod.signed_url = lambda path, minutes=60: "https://signed.example/%s?m=%d" % (path, minutes)
    monkeypatch.setitem(sys.modules, "app.platform_storage", mod)
    monkeypatch.setattr(app, "platform_storage", mod, raising=False)
    return saved


@pytest.fixture()
def pushes(monkeypatch):
    import app
    sent = []
    mod = types.ModuleType("app.platform_push")

    def send_push(uid, title, body, data=None, category=None):
        sent.append({"uid": uid, "title": title, "body": body, "data": data, "category": category})
        return 1

    mod.send_push = send_push
    monkeypatch.setitem(sys.modules, "app.platform_push", mod)
    monkeypatch.setattr(app, "platform_push", mod, raising=False)
    return sent


@pytest.mark.parametrize("lang", LANGS)
def test_share_cards(client, db, storage, lang):
    make_user(db)
    p = client.post("/api/profiles", json=RAVI, headers=auth()).json()
    for kind in ("chart", "daily"):
        r = client.post("/api/share-card?lang=%s" % lang, json={"profile_id": p["id"], "kind": kind},
                        headers=auth())
        assert r.status_code == 200, r.text
        assert r.json()["url"].startswith("https://signed.example/share/u1/")
    pngs = [v for k, v in storage.items() if k.endswith(".png")]
    assert len(pngs) == 2
    from PIL import Image
    import io
    for data, ctype in pngs:
        assert ctype == "image/png"
        assert Image.open(io.BytesIO(data)).size == (1080, 1350)


@pytest.mark.parametrize("lang", LANGS)
def test_matching_pdf(client, db, storage, lang):
    make_user(db, role="astrologer")
    client.put("/api/astro/brand", json={"display_name": "Sri Sai Jyotisham", "phone": "+91 90000 00000",
                                         "footer": "By appointment"}, headers=auth())
    a = client.post("/api/profiles", json=RAVI, headers=auth()).json()
    b = client.post("/api/profiles", json=SITA, headers=auth()).json()
    r = client.post("/api/matching/pdf?lang=%s" % lang, json={"profile_a": a["id"], "profile_b": b["id"]},
                    headers=auth())
    assert r.status_code == 200, r.text
    data, ctype = next(v for k, v in storage.items() if k.endswith(".pdf"))
    assert ctype == "application/pdf" and data.startswith(b"%PDF") and len(data) > 5000


def test_share_card_without_storage(client, db, monkeypatch):
    import app
    monkeypatch.setitem(sys.modules, "app.platform_storage", None)
    monkeypatch.delattr(app, "platform_storage", raising=False)
    make_user(db)
    p = client.post("/api/profiles", json=RAVI, headers=auth()).json()
    r = client.post("/api/share-card", json={"profile_id": p["id"], "kind": "chart"}, headers=auth())
    assert r.status_code == 503


def test_daily_push_cron(client, db, pushes):
    make_user(db, "u1", lang="ta")
    make_user(db, "u2", lang="hi", notif_prefs={"daily": False, "transits": True})
    make_user(db, "u3", lang="te")  # opted in, but no profile yet
    client.post("/api/profiles", json=RAVI, headers=auth("u1"))
    client.post("/api/profiles", json=RAVI, headers=auth("u2"))
    r = client.post("/internal/cron/daily-push")
    assert r.status_code == 200, r.text
    stats = r.json()
    assert stats["sent"] == 1 and stats["considered"] == 2
    assert [p["uid"] for p in pushes] == ["u1"]
    assert pushes[0]["category"] == "daily" and "Ravi" in pushes[0]["title"]
    # Retry is idempotent
    assert client.post("/internal/cron/daily-push").json()["sent"] == 0
    assert len(pushes) == 1


def test_transit_alert_cron_dedupes(db, pushes):
    from app.features import alerts, cron, profiles
    make_user(db, "u1", lang="te")
    prof = profiles.create("u1", {"role": "user"}, dict(RAVI))
    # Ravi's Venus antardasha starts 16-10-2026: a 7-day lead fires on 09-10.
    today = date(2026, 10, 9)
    upcoming = alerts.compute(prof, "te", days=8, today=today)
    assert any(a["type"] == "antar_change" and a["days_away"] == 7 for a in upcoming)
    leads = [7, 1]
    s1 = cron.transit_alerts(today=today, lead_days=leads)
    assert s1["sent"] >= 1
    s2 = cron.transit_alerts(today=today, lead_days=leads)
    assert s2["sent"] == 0
    assert len(pushes) == s1["sent"]
    for p in pushes:
        assert p["category"] == "transits" and p["body"]


def test_cron_requires_auth(client, db, monkeypatch):
    monkeypatch.setenv("CRON_INSECURE_DEV", "0")
    r = client.post("/internal/cron/daily-push")
    assert r.status_code == 401
