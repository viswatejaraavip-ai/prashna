"""Shared plumbing for the features workstream: engine import, errors in the
contract's shape, i18n template access, birth-data conversion, Pro gating."""

import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from typing import Any, Callable, Dict, Optional

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

# Engine import, same convention as app.agent (ENGINE_PATH or repo layout).
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
_ENGINE = os.environ.get("ENGINE_PATH", os.path.join(_ROOT, "engine"))
if _ENGINE not in sys.path:
    sys.path.insert(0, _ENGINE)

from jyotish import api as japi  # noqa: E402
from jyotish import constants as jc  # noqa: E402
from jyotish import locale as jlocale  # noqa: E402

LANGS = ("hi", "te", "ta", "kn", "ml", "en")
I18N_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "i18n")


# ---------- errors: {"detail": ..., "code": ...} ----------

class FeatureError(HTTPException):
    def __init__(self, status: int, code: str, detail: str):
        super().__init__(status_code=status, detail=detail)
        self.code = code


def invalid(detail: str) -> FeatureError:
    return FeatureError(400, "invalid", detail)


def not_found(detail: str = "Not found") -> FeatureError:
    return FeatureError(404, "not_found", detail)


def forbidden(detail: str) -> FeatureError:
    return FeatureError(403, "forbidden", detail)


class FeatureRoute(APIRoute):
    """Route class that renders FeatureError as the contract's error body,
    without needing a global exception handler in main.py."""

    def get_route_handler(self) -> Callable:
        handler = super().get_route_handler()

        async def wrapped(request: Request):
            try:
                return await handler(request)
            except FeatureError as exc:
                return JSONResponse({"detail": exc.detail, "code": exc.code},
                                    status_code=exc.status_code)
        return wrapped


# ---------- i18n ----------

@lru_cache(maxsize=16)
def templates(lang: str) -> Dict:
    lang = lang if lang in LANGS or lang == "en" else "te"
    with open(os.path.join(I18N_DIR, "%s.json" % lang), encoding="utf-8") as fh:
        return json.load(fh)


@lru_cache(maxsize=1)
def panchanga_names() -> Dict:
    with open(os.path.join(I18N_DIR, "panchanga_names.json"), encoding="utf-8") as fh:
        return json.load(fh)


def t(lang: str, path: str, **kw) -> str:
    """Template lookup by dotted path, formatted with kw."""
    node: Any = templates(lang)
    for part in path.split("."):
        node = node[part]
    return node.format(**kw) if kw else node


def names(lang: str) -> Dict[str, Dict[str, str]]:
    """English engine term -> localized term (planets, signs, nakshatras,
    weekdays from the engine locale; tithi/yoga/karana from our data file)."""
    if lang == "en":
        return _english_names()
    b = jlocale.bundle(lang) or {}
    out = {k: dict(b.get(k, {})) for k in ("planets", "signs", "nakshatras", "weekdays")}
    pn = panchanga_names().get(lang, {})
    for k in ("tithis", "yogas", "karanas"):
        out[k] = dict(pn.get(k, {}))
    return out


@lru_cache(maxsize=1)
def _english_names() -> Dict[str, Dict[str, str]]:
    """The engine's own (English/Sanskrit) terms, as identity maps."""
    from jyotish import constants as c
    ident = lambda xs: {x: x for x in xs}  # noqa: E731
    return {
        "planets": ident(getattr(c, "PLANETS", [])), "signs": ident(getattr(c, "SIGNS", [])),
        "nakshatras": ident(getattr(c, "NAKSHATRAS", [])),
        "weekdays": ident(getattr(c, "WEEKDAYS", [])),
        "tithis": ident(list(c.TITHIS) + ["Purnima", "Amavasya"]),
        "yogas": ident(c.YOGAS),
        "karanas": ident(list(c.KARANA_MOVABLE) + list(c.KARANA_FIXED_END)
                         + [c.KARANA_FIXED_START]),
    }


def planet(lang: str, p: str) -> str:
    return names(lang)["planets"].get(p, p)


def sign(lang: str, s: str) -> str:
    return names(lang)["signs"].get(s, s)


def nak(lang: str, n: str) -> str:
    return names(lang)["nakshatras"].get(n, n)


def weekday(lang: str, w: str) -> str:
    return names(lang)["weekdays"].get(w, w)


def ordinal(lang: str, n: int) -> str:
    return templates(lang)["ordinal"][str(int(n))]


def fmt_date(value, lang: str = "") -> str:
    """dd-mm-yyyy (the common Indian format; digits are universal)."""
    if isinstance(value, str):
        value = datetime.fromisoformat(value) if "T" in value else date.fromisoformat(value[:10])
    if isinstance(value, datetime) and value.tzinfo is not None:
        value = value.astimezone(timezone(timedelta(hours=5, minutes=30)))  # IST calendar
    return value.strftime("%d-%m-%Y")


# ---------- birth data ----------

def birth_dict(profile: Dict, lang: Optional[str] = None) -> Dict:
    """Engine birth dict from a stored profile (noon when time unknown)."""
    b = profile["birth"]
    y, m, d = (int(x) for x in b["date"].split("-"))
    time_str = b.get("time") if profile.get("time_known", True) and b.get("time") else "12:00"
    hh, mm = (int(x) for x in time_str.split(":")[:2])
    out = {"year": y, "month": m, "day": d, "hour": hh, "minute": mm,
           "latitude": float(b["lat"]), "longitude": float(b["lon"]),
           "tz_name": b.get("tz") or "Asia/Kolkata"}
    if lang:
        out["lang"] = lang
    return out


def birth_utc(profile: Dict) -> datetime:
    return japi.BirthData.from_dict(birth_dict(profile)).utc


def natal_positions(profile: Dict) -> Dict[str, float]:
    from jyotish import ephemeris
    bd = japi.BirthData.from_dict(birth_dict(profile))
    pos = ephemeris.planet_positions(bd.jd, bd.ayanamsa)
    out = {k: v["longitude"] for k, v in pos.items()}
    out["Lagna"] = ephemeris.ascendant(bd.jd, bd.latitude, bd.longitude, bd.ayanamsa)
    return out


def derive(profile: Dict) -> Dict:
    """Small natal summary stored on the profile (used by cron/daily without
    recomputing): sign indices 0..11, nakshatra index 0..26."""
    pos = natal_positions(profile)
    moon = pos["Moon"] % 360.0
    return {
        "moon_sign": int(moon // 30),
        "nakshatra": int(moon / jc.NAKSHATRA_SPAN) % 27,
        "lagna_sign": int((pos["Lagna"] % 360.0) // 30),
        "moon_lon": round(moon, 6),
    }


# ---------- plan gating ----------

def is_pro(user: Optional[Dict]) -> bool:
    if not user or user.get("plan") != "pro":
        return False
    exp = user.get("plan_expires_at")
    if not exp:
        return False
    try:
        dt = datetime.fromisoformat(str(exp).replace("Z", "+00:00"))
    except ValueError:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt > datetime.now(timezone.utc)


def require_pro(user: Dict) -> None:
    if not is_pro(user):
        raise forbidden("This needs an active Pro plan")


def require_astrologer(user: Dict) -> None:
    if (user or {}).get("role") != "astrologer":
        raise forbidden("Astrologer accounts only")


def tz_today(tz_name: str) -> date:
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(tz_name)).date()
    except Exception:
        return (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).date()
