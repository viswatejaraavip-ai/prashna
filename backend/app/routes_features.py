"""Personal-user and astrologer features (no LLM): profiles, free charts,
first-reading snapshot, daily panchanga + forecast, transit alerts, matching
(+PDF), muhurta finder, birth-time helper, share cards, places, astrologer
clients / Pro bundle / white-label brand, and the two cron jobs.

Exposes ``router`` (/api/...) and ``internal_router`` (/internal/cron/...).
See docs/launch/CONTRACT.md, "Personal & astrologer features".
"""

import uuid
from datetime import date
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import BaseModel, Field

from . import store
from .features import views
from .features import alerts as alerts_mod
from .features import brand as brand_mod
from .features import charts as charts_mod
from .features import cron as cron_mod
from .features import daily as daily_mod
from .features import matching as matching_mod
from .features import muhurta as muhurta_mod
from .features import places as places_mod
from .features import profiles as prof_mod
from .features import rectify as rectify_mod
from .features import snapshot as snapshot_mod
from .features.common import (FeatureError, FeatureRoute, birth_dict, invalid, japi,
                              require_astrologer, require_pro, t, tz_today)

router = APIRouter(route_class=FeatureRoute, tags=["features"])


# ---------- request context ----------

class Ctx:
    def __init__(self, uid: str, user: Dict, lang: str):
        self.uid, self.user, self.lang = uid, user, lang


def ctx(request: Request, uid: str = Depends(store.current_uid),
        user: Dict = Depends(store.current_user)) -> Ctx:
    return Ctx(uid, user, store.lang_of(request, user))


def _upload(path: str, data: bytes, content_type: str) -> str:
    try:
        from . import platform_storage  # platform workstream; imported lazily
    except ImportError:
        raise FeatureError(503, "unavailable", "File storage is not configured")
    try:
        platform_storage.upload_bytes(path, data, content_type)
        return platform_storage.signed_url(path, 60)
    except Exception as exc:
        raise FeatureError(503, "unavailable", "Could not store the file: %s" % exc)


# ---------- places ----------

def _local_labels(texts, lang):
    if lang == "en" or not texts:
        return list(texts)
    from .features.translate import translate_many
    return translate_many(list(texts), lang)


def with_place_local(profiles, lang):
    """Adds birth.place_local (the stored English place name, localized)."""
    items = profiles if isinstance(profiles, list) else [profiles]
    names = [((p.get("birth") or {}).get("place") or "") for p in items]
    local = _local_labels([n for n in names if n], lang)
    it = iter(local)
    for p, n in zip(items, names):
        if n:
            p.setdefault("birth", {})["place_local"] = next(it)
    return profiles


@router.get("/api/places")
def places(q: str = "", request: Request = None):
    res = places_mod.search(q)
    lang = store.lang_of(request) if request is not None else "en"
    for r, loc in zip(res, _local_labels([r["label"] for r in res], lang)):
        r["label_local"] = loc
    return res


# ---------- profiles ----------

class BirthIn(BaseModel):
    date: str
    time: Optional[str] = None
    tz: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    place: Optional[str] = None


class ProfileIn(BaseModel):
    name: str
    relation: str = "other"
    birth: BirthIn
    time_known: bool = True
    gender: Optional[str] = None
    notes: str = ""


class ProfilePatch(BaseModel):
    name: Optional[str] = None
    relation: Optional[str] = None
    birth: Optional[Dict] = None
    time_known: Optional[bool] = None
    gender: Optional[str] = None
    notes: Optional[str] = None


@router.get("/api/profiles")
def list_profiles(include_clients: bool = False, c: Ctx = Depends(ctx)):
    return {"profiles": with_place_local(
        prof_mod.list_profiles(c.uid, exclude_clients=not include_clients), c.lang)}


@router.post("/api/profiles")
def create_profile(body: ProfileIn, c: Ctx = Depends(ctx)):
    data = body.model_dump()
    data["birth"] = {k: v for k, v in data["birth"].items() if v is not None}
    return with_place_local(prof_mod.create(c.uid, c.user, data), c.lang)


@router.get("/api/profiles/{pid}")
def get_profile(pid: str, c: Ctx = Depends(ctx)):
    return with_place_local(prof_mod.get(c.uid, pid), c.lang)


@router.patch("/api/profiles/{pid}")
def patch_profile(pid: str, body: ProfilePatch, c: Ctx = Depends(ctx)):
    return with_place_local(prof_mod.update(c.uid, pid, body.model_dump(exclude_unset=True)), c.lang)


@router.delete("/api/profiles/{pid}")
def delete_profile(pid: str, c: Ctx = Depends(ctx)):
    prof_mod.delete(c.uid, pid)
    return {"ok": True}


# ---------- charts / snapshot ----------

@router.get("/api/profiles/{pid}/chart")
def profile_chart(pid: str, kind: str = "rasi", division: Optional[str] = None,
                  year: Optional[int] = None, c: Ctx = Depends(ctx)):
    prof = prof_mod.get(c.uid, pid)
    return charts_mod.chart(prof, c.user, kind, division, c.lang, year)


@router.get("/api/profiles/{pid}/snapshot")
def profile_snapshot(pid: str, c: Ctx = Depends(ctx)):
    return snapshot_mod.snapshot(prof_mod.get(c.uid, pid), c.lang)


# ---------- daily ----------

_DAILY_LABEL_KEYS = ("tithi", "vara", "nakshatra_short", "yoga", "karana", "moon_sign",
                     "sunrise", "sunset", "rahu_kalam", "yamagandam", "gulika", "abhijit", "brahma")


def daily_labels(lang: str) -> dict:
    """Localized row labels so the app never has to show engine field names."""
    from .features.common import templates
    labels = templates(lang).get("labels", {})
    return {k: labels[k] for k in _DAILY_LABEL_KEYS if k in labels}


@router.get("/api/daily")
def daily(profile_id: Optional[str] = None, day: Optional[str] = Query(None, alias="date"),
          lat: Optional[float] = None, lon: Optional[float] = None, tz: Optional[str] = None,
          c: Ctx = Depends(ctx)):
    prof = prof_mod.get(c.uid, profile_id) if profile_id else prof_mod.primary(c.uid)
    birth = (prof or {}).get("birth") or {}
    tz = tz or birth.get("tz") or "Asia/Kolkata"
    if lat is None or lon is None:
        lat, lon = birth.get("lat", 17.385), birth.get("lon", 78.4867)  # default: Hyderabad
    try:
        the_day = date.fromisoformat(day) if day else tz_today(tz)
    except ValueError:
        raise invalid("date must be YYYY-MM-DD")
    pan = daily_mod.day_panchanga(the_day, float(lat), float(lon), tz, c.lang)
    raw_timings = pan.pop("_raw_timings", None)
    out = {"date": the_day.isoformat(), "lang": c.lang,
           "place": {"lat": lat, "lon": lon, "tz": tz, "name": birth.get("place") if prof else None},
           "panchanga": pan, "forecast": None,
           "labels": daily_labels(c.lang)}
    if prof:
        derived = prof_mod.ensure_derived(c.uid, prof)
        out["profile_id"] = prof["id"]
        out["forecast"] = daily_mod.personal(the_day, c.lang, derived, prof.get("name", ""),
                                             raw_timings)
    else:
        from .features.common import t
        out["message"] = t(c.lang, "daily.no_profile")
    return out


# ---------- alerts ----------

@router.get("/api/profiles/{pid}/alerts")
def profile_alerts(pid: str, days: int = Query(180, ge=1, le=366), c: Ctx = Depends(ctx)):
    prof = prof_mod.get(c.uid, pid)
    prof_mod.ensure_derived(c.uid, prof)
    return {"profile_id": pid, "days": days,
            "alerts": alerts_mod.compute(prof, c.lang, days=days)}


# ---------- matching ----------

class MatchIn(BaseModel):
    profile_a: str
    profile_b: str
    brand: bool = True


def _match(body: MatchIn, c: Ctx):
    if body.profile_a == body.profile_b:
        raise invalid("Pick two different profiles")
    a = prof_mod.get(c.uid, body.profile_a)
    b = prof_mod.get(c.uid, body.profile_b)
    return a, b, matching_mod.match(a, b, c.lang)


@router.post("/api/matching")
def matching(body: MatchIn, c: Ctx = Depends(ctx)):
    res = _match(body, c)[2]
    res["view"] = views.tool_view("matching", res, c.lang)
    return res


@router.post("/api/matching/pdf")
def matching_pdf(body: MatchIn, c: Ctx = Depends(ctx)):
    from .features import pdf as pdf_mod
    a, b, result = _match(body, c)
    brand = None
    if body.brand and c.user.get("role") == "astrologer":
        brand = brand_mod.get_brand(c.uid)
    by_id = {a["id"]: a, b["id"]: b}
    births = {"groom": by_id[result["groom"]["profile_id"]]["birth"],
              "bride": by_id[result["bride"]["profile_id"]]["birth"]}
    data = pdf_mod.matching_pdf(result, c.lang, brand, births)
    path = "matching/%s/%s.pdf" % (c.uid, uuid.uuid4().hex)
    return {"url": _upload(path, data, "application/pdf"), "path": path,
            "expires_in_minutes": 60}


# ---------- muhurta ----------

class MuhurtaIn(BaseModel):
    event: str
    from_: str = Field(..., alias="from")
    to: str
    profile_id: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    tz: Optional[str] = None
    limit: int = 10

    model_config = {"populate_by_name": True}


@router.post("/api/muhurta")
def muhurta(body: MuhurtaIn, c: Ctx = Depends(ctx)):
    try:
        start, end = date.fromisoformat(body.from_[:10]), date.fromisoformat(body.to[:10])
    except ValueError:
        raise invalid("from/to must be YYYY-MM-DD")
    person = None
    if body.profile_id:
        person = prof_mod.get(c.uid, body.profile_id)
        prof_mod.ensure_derived(c.uid, person)
    lat, lon, tz = body.lat, body.lon, body.tz
    if lat is None or lon is None:
        if not person:
            raise invalid("Send lat/lon (or a profile_id to use its place)")
        lat, lon = person["birth"]["lat"], person["birth"]["lon"]
        tz = tz or person["birth"].get("tz")
    res = muhurta_mod.find(body.event, start, end, float(lat), float(lon),
                           tz or "Asia/Kolkata", c.lang, person, body.limit)
    res["view"] = views.tool_view("muhurta", res, c.lang)
    return res


# ---------- birth-time helper ----------

class LifeEvent(BaseModel):
    date: str
    type: str = "other"


class RectifyIn(BaseModel):
    events: List[LifeEvent]
    window_minutes: Optional[int] = Field(None, ge=5, le=720)
    from_time: Optional[str] = None
    to_time: Optional[str] = None
    step_minutes: Optional[int] = Field(None, ge=1, le=60)


@router.post("/api/profiles/{pid}/rectify")
def rectify(pid: str, body: RectifyIn, c: Ctx = Depends(ctx)):
    prof = prof_mod.get(c.uid, pid)
    res = rectify_mod.rectify(prof, [e.model_dump() for e in body.events], c.lang,
                              body.window_minutes, body.step_minutes,
                              body.from_time, body.to_time)
    res["view"] = views.tool_view("rectify", res, c.lang)
    return res


# ---------- share card ----------

class ShareIn(BaseModel):
    profile_id: str
    kind: str = "chart"


@router.post("/api/share-card")
def share_card(body: ShareIn, c: Ctx = Depends(ctx)):
    from .features import sharecard
    prof = prof_mod.get(c.uid, body.profile_id)
    if body.kind == "chart":
        chart = japi.birth_chart(birth_dict(prof))
        snap = snapshot_mod.snapshot(prof, c.lang)
        png = sharecard.chart_card(prof, chart, snap, c.lang)
    elif body.kind == "daily":
        b = prof["birth"]
        the_day = tz_today(b.get("tz") or "Asia/Kolkata")
        pan = daily_mod.day_panchanga(the_day, b["lat"], b["lon"], b.get("tz") or "Asia/Kolkata",
                                      c.lang)
        raw = pan.pop("_raw_timings", None)
        derived = prof_mod.ensure_derived(c.uid, prof)
        fc = daily_mod.personal(the_day, c.lang, derived, prof.get("name", ""), raw)
        png = sharecard.daily_card(prof.get("name", ""), the_day, fc, pan, c.lang)
    else:
        raise invalid("kind must be chart or daily")
    path = "share/%s/%s.png" % (c.uid, uuid.uuid4().hex)
    return {"url": _upload(path, png, "image/png"), "path": path, "expires_in_minutes": 60}


# ---------- astrologer ----------

class ClientIn(BaseModel):
    name: str
    birth: BirthIn
    time_known: bool = True
    gender: Optional[str] = None
    notes: str = ""


class ClientPatch(BaseModel):
    notes: Optional[str] = None
    name: Optional[str] = None
    gender: Optional[str] = None
    birth: Optional[Dict] = None
    time_known: Optional[bool] = None


class BrandIn(BaseModel):
    """Every field is optional so a partial body is rejected by brand.py with a
    localized message instead of FastAPI's raw English validation array."""

    display_name: str = ""
    phone: str = ""
    logo_url: str = ""
    footer: str = ""


def astro_ctx(c: Ctx = Depends(ctx)) -> Ctx:
    require_astrologer(c.user, c.lang)
    return c


def _client(uid: str, pid: str, lang: str = "en") -> Dict:
    prof = prof_mod.get(uid, pid)
    if prof.get("relation") != "client":
        raise FeatureError(404, "not_found", t(lang, "errors.client_not_found"))
    return prof


@router.get("/api/astro/clients")
def list_clients(q: str = "", c: Ctx = Depends(astro_ctx)):
    clients = prof_mod.list_profiles(c.uid, relation="client")
    needle = q.strip().lower()
    if needle:
        clients = [p for p in clients
                   if needle in (p.get("name") or "").lower()
                   or needle in (p.get("notes") or "").lower()
                   or needle in ((p.get("birth") or {}).get("place") or "").lower()]
    clients.sort(key=lambda p: (p.get("name") or "").lower())
    return {"clients": with_place_local(clients, c.lang)}


@router.post("/api/astro/clients")
def create_client(body: ClientIn, c: Ctx = Depends(astro_ctx)):
    data = body.model_dump()
    data["birth"] = {k: v for k, v in data["birth"].items() if v is not None}
    data["relation"] = "client"
    return with_place_local(prof_mod.create(c.uid, c.user, data), c.lang)


@router.get("/api/astro/clients/{pid}")
def get_client(pid: str, c: Ctx = Depends(astro_ctx)):
    return with_place_local(_client(c.uid, pid, c.lang), c.lang)


@router.patch("/api/astro/clients/{pid}")
def patch_client(pid: str, body: ClientPatch, c: Ctx = Depends(astro_ctx)):
    _client(c.uid, pid, c.lang)
    patch = body.model_dump(exclude_unset=True)
    patch.pop("relation", None)  # a client stays a client
    return with_place_local(prof_mod.update(c.uid, pid, patch), c.lang)


@router.delete("/api/astro/clients/{pid}")
def delete_client(pid: str, c: Ctx = Depends(astro_ctx)):
    _client(c.uid, pid, c.lang)
    prof_mod.delete(c.uid, pid)
    return {"ok": True}


@router.get("/api/astro/clients/{pid}/pro-bundle")
def pro_bundle(pid: str, c: Ctx = Depends(astro_ctx)):
    require_pro(c.user, c.lang)
    return charts_mod.pro_bundle(_client(c.uid, pid, c.lang), c.lang)


@router.get("/api/astro/brand")
def get_brand(c: Ctx = Depends(astro_ctx)):
    # Never `null`: an astrologer who has not saved a brand gets an empty one,
    # so the settings form always has the four fields to bind to.
    return {"brand": brand_mod.get_brand(c.uid) or brand_mod.blank()}


@router.put("/api/astro/brand")
def put_brand(body: BrandIn, c: Ctx = Depends(astro_ctx)):
    return {"brand": brand_mod.put_brand(c.uid, body.model_dump(), c.lang)}


# ---------- cron (Cloud Scheduler, OIDC) ----------

def _cron_guard(authorization: Optional[str] = Header(None)):
    from .platform_cron import verify_cron  # platform workstream; imported lazily
    return verify_cron(authorization)


internal_router = APIRouter(route_class=FeatureRoute, tags=["cron"],
                            dependencies=[Depends(_cron_guard)])


@internal_router.post("/internal/cron/daily-push")
def cron_daily_push():
    return cron_mod.daily_push()


@internal_router.post("/internal/cron/transit-alerts")
def cron_transit_alerts():
    return cron_mod.transit_alerts()
