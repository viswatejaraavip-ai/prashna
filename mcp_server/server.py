"""Udhyath MCP server - Vedic astrology tools with pay-per-use billing.

Modes
-----
1. Local stdio, free/dev (no token): computes locally with the bundled engine.
       python server.py

2. Local stdio, billed: set your Udhyath API token; every tool call goes to
   the hosted metered API and is charged to your prepaid wallet.
       UDHYATH_API_KEY=udh_... UDHYATH_API_URL=https://api.astrology.example.com \
       python server.py

3. Hosted (Streamable HTTP), billed: clients send their token per request:
       Authorization: Bearer udh_...
   Run with:
       MCP_TRANSPORT=http MCP_PORT=8100 UDHYATH_API_URL=http://web:8000 \
       MCP_REQUIRE_TOKEN=1 python server.py

Requires Python 3.10+ and: pip install "mcp[cli]" httpx pyswisseph
"""

import contextvars
import os
import sys
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "engine"))

import httpx  # noqa: E402
from mcp.server.fastmcp import FastMCP  # noqa: E402

from jyotish import api  # noqa: E402

API_URL = os.environ.get("UDHYATH_API_URL", "").rstrip("/")
ENV_KEY = os.environ.get("UDHYATH_API_KEY", "")
REQUIRE_TOKEN = os.environ.get("MCP_REQUIRE_TOKEN", "") in ("1", "true", "yes")

# Per-request token captured from the Authorization header in HTTP mode.
_request_token: contextvars.ContextVar = contextvars.ContextVar(
    "udhyath_token", default=None)

mcp = FastMCP(
    "udhyath-jyotish",
    instructions=(
        "Udhyath Vedic (Jyotish) astrology tools on Swiss Ephemeris. All "
        "positions are sidereal (default Lahiri ayanamsa). Birth details need "
        "date, time, latitude, longitude and an IANA timezone name (e.g. "
        "'Asia/Kolkata') or a fixed UTC offset in hours. Usage is billed "
        "per tool call to your prepaid Udhyath wallet."
    ),
)


def _token() -> Optional[str]:
    return _request_token.get() or (ENV_KEY or None)


def _remote(method: str, path: str, payload: Optional[dict] = None,
            params: Optional[dict] = None):
    """Call the hosted metered API. Returns the JSON result, an error dict,
    or None meaning 'use local computation'."""
    token = _token()
    if not API_URL or not token:
        if REQUIRE_TOKEN:
            return {"error": "authentication_required",
                    "message": "This server bills per call. Send your Udhyath "
                               "API token as 'Authorization: Bearer udh_...' "
                               "or set UDHYATH_API_KEY."}
        return None
    try:
        resp = httpx.request(
            method, API_URL + path, json=payload, params=params,
            headers={"Authorization": "Bearer " + token}, timeout=30.0)
        if resp.status_code in (401, 402):
            detail = resp.json().get("detail", resp.text)
            return {"error": "billing" if resp.status_code == 402 else "auth",
                    "detail": detail}
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPError as exc:
        return {"error": "api_unreachable", "detail": str(exc)}


def _birth(year, month, day, hour, minute, latitude, longitude,
           tz_name, utc_offset_hours, ayanamsa) -> dict:
    return {
        "year": year, "month": month, "day": day, "hour": hour, "minute": minute,
        "latitude": latitude, "longitude": longitude, "tz_name": tz_name,
        "utc_offset_hours": utc_offset_hours, "ayanamsa": ayanamsa,
    }


@mcp.tool()
def birth_chart(year: int, month: int, day: int, hour: int, minute: int,
                latitude: float, longitude: float, tz_name: Optional[str] = None,
                utc_offset_hours: Optional[float] = None, ayanamsa: str = "lahiri") -> dict:
    """Rasi (D-1) birth chart: sidereal planet positions with signs, nakshatras,
    padas, retrogrades, whole-sign houses, ascendant (lagna) and birth panchanga."""
    b = _birth(year, month, day, hour, minute, latitude, longitude,
               tz_name, utc_offset_hours, ayanamsa)
    remote = _remote("POST", "/v1/birth-chart", b)
    return remote if remote is not None else api.birth_chart(b)


@mcp.tool()
def varga_chart(varga: str, year: int, month: int, day: int, hour: int, minute: int,
                latitude: float, longitude: float, tz_name: Optional[str] = None,
                utc_offset_hours: Optional[float] = None, ayanamsa: str = "lahiri") -> dict:
    """One divisional chart. varga is one of: D1, D2 (Hora), D3 (Drekkana), D4,
    D7 (Saptamsa), D9 (Navamsa), D10 (Dasamsa), D12, D16, D20, D24, D27,
    D30 (Trimsamsa), D40, D45, D60 (Shashtiamsa)."""
    b = _birth(year, month, day, hour, minute, latitude, longitude,
               tz_name, utc_offset_hours, ayanamsa)
    remote = _remote("POST", "/v1/varga-chart", dict(b, varga=varga))
    return remote if remote is not None else api.varga_chart(b, varga)


@mcp.tool()
def all_varga_charts(year: int, month: int, day: int, hour: int, minute: int,
                     latitude: float, longitude: float, tz_name: Optional[str] = None,
                     utc_offset_hours: Optional[float] = None,
                     ayanamsa: str = "lahiri") -> dict:
    """All 16 classical (Shodasavarga) divisional charts in compact form."""
    b = _birth(year, month, day, hour, minute, latitude, longitude,
               tz_name, utc_offset_hours, ayanamsa)
    remote = _remote("POST", "/v1/all-vargas", b)
    return remote if remote is not None else api.all_vargas(b)


@mcp.tool()
def bhava_chalit_chart(year: int, month: int, day: int, hour: int, minute: int,
                       latitude: float, longitude: float, tz_name: Optional[str] = None,
                       utc_offset_hours: Optional[float] = None,
                       ayanamsa: str = "lahiri") -> dict:
    """Bhava chalit (Sripati) house placements."""
    b = _birth(year, month, day, hour, minute, latitude, longitude,
               tz_name, utc_offset_hours, ayanamsa)
    remote = _remote("POST", "/v1/bhava-chalit", b)
    return remote if remote is not None else api.bhava_chart(b)


@mcp.tool()
def dasha_periods(year: int, month: int, day: int, hour: int, minute: int,
                  latitude: float, longitude: float, tz_name: Optional[str] = None,
                  utc_offset_hours: Optional[float] = None, ayanamsa: str = "lahiri",
                  levels: int = 2, system: str = "vimshottari") -> dict:
    """Dasha timeline from birth. system: vimshottari (default), yogini
    (36-year cycle), chara (Jaimini, K.N. Rao), kalachakra (BPHS). levels
    applies to vimshottari: 1 maha, 2 +antar, 3 +pratyantar."""
    b = _birth(year, month, day, hour, minute, latitude, longitude,
               tz_name, utc_offset_hours, ayanamsa)
    remote = _remote("POST", "/v1/dashas", dict(b, system=system, levels=levels))
    return remote if remote is not None else api.dasha_periods(b, levels, system)


@mcp.tool()
def current_dasha(year: int, month: int, day: int, hour: int, minute: int,
                  latitude: float, longitude: float, tz_name: Optional[str] = None,
                  utc_offset_hours: Optional[float] = None, ayanamsa: str = "lahiri",
                  at_iso: Optional[str] = None) -> dict:
    """Vimshottari maha/antar/pratyantar lords running now (or at at_iso)."""
    b = _birth(year, month, day, hour, minute, latitude, longitude,
               tz_name, utc_offset_hours, ayanamsa)
    if at_iso is None:
        remote = _remote("POST", "/v1/current-dasha", b)
        if remote is not None:
            return remote
    return api.current_dasha(b, at_iso)


@mcp.tool()
def birth_panchanga(year: int, month: int, day: int, hour: int, minute: int,
                    latitude: float, longitude: float, tz_name: Optional[str] = None,
                    utc_offset_hours: Optional[float] = None,
                    ayanamsa: str = "lahiri") -> dict:
    """Panchanga at birth: tithi (+paksha), vara, nakshatra+pada, yoga, karana."""
    b = _birth(year, month, day, hour, minute, latitude, longitude,
               tz_name, utc_offset_hours, ayanamsa)
    remote = _remote("POST", "/v1/birth-chart", b)
    if remote is not None:
        return remote.get("panchanga", remote)
    return api.panchanga_for(b)


@mcp.tool()
def kp_chart(year: int, month: int, day: int, hour: int, minute: int,
             latitude: float, longitude: float, tz_name: Optional[str] = None,
             utc_offset_hours: Optional[float] = None,
             ayanamsa: Optional[str] = None) -> dict:
    """KP (Krishnamurti Paddhati): sign/star/sub/sub-sub lords for every planet
    and all 12 Placidus cusps. Uses the Krishnamurti ayanamsa by default."""
    b = _birth(year, month, day, hour, minute, latitude, longitude,
               tz_name, utc_offset_hours, ayanamsa or "kp")
    remote = _remote("POST", "/v1/kp-chart", b)
    return remote if remote is not None else api.kp_chart(b)


@mcp.tool()
def ashtakavarga(year: int, month: int, day: int, hour: int, minute: int,
                 latitude: float, longitude: float, tz_name: Optional[str] = None,
                 utc_offset_hours: Optional[float] = None,
                 ayanamsa: str = "lahiri") -> dict:
    """Ashtakavarga: Bhinnashtakavarga bindus per sign for the 7 classical
    planets plus Sarvashtakavarga totals (337 bindus)."""
    b = _birth(year, month, day, hour, minute, latitude, longitude,
               tz_name, utc_offset_hours, ayanamsa)
    remote = _remote("POST", "/v1/ashtakavarga", b)
    return remote if remote is not None else api.ashtakavarga_chart(b)


@mcp.tool()
def panchanga_today(latitude: Optional[float] = None, longitude: Optional[float] = None,
                    tz_name: Optional[str] = None) -> dict:
    """Panchanga of the current moment plus current transit positions."""
    params = {"tz_name": tz_name or "Asia/Kolkata"}
    if latitude is not None:
        params["latitude"] = latitude
    if longitude is not None:
        params["longitude"] = longitude
    remote = _remote("GET", "/v1/panchanga", params=params)
    return remote if remote is not None else api.panchanga_now(latitude, longitude, tz_name)


@mcp.tool()
def nadi_analysis(year: int, month: int, day: int, hour: int, minute: int,
                  latitude: float, longitude: float, tz_name: Optional[str] = None,
                  utc_offset_hours: Optional[float] = None,
                  ayanamsa: str = "lahiri") -> dict:
    """Nadi analysis: Meena stellar delivery (each planet delivers its star
    lord's houses; deputies = planets in its stars), Bhrigu Nandi Nadi karakas
    and sign-links (conjunction/trine/opposition/2-12), nadi-amsa (D-150),
    planetary dignity, and an 80-year Jupiter (jeeva) transit timeline with
    contacts to natal points - the BNN life-chapter clock."""
    b = _birth(year, month, day, hour, minute, latitude, longitude,
               tz_name, utc_offset_hours, ayanamsa)
    remote = _remote("POST", "/v1/nadi-analysis", b)
    return remote if remote is not None else api.nadi_analysis(b)


@mcp.tool()
def full_analysis(year: int, month: int, day: int, hour: int, minute: int,
                  latitude: float, longitude: float, tz_name: Optional[str] = None,
                  utc_offset_hours: Optional[float] = None,
                  ayanamsa: str = "lahiri", at_iso: Optional[str] = None) -> dict:
    """Cross-system synthesis bundle in ONE call - the right first tool for
    any full reading or prediction. Returns rasi (D-1), navamsa (D-9), bhava
    chalit placements, KP sub lords + planet/house significator tables,
    Ashtakavarga BAV/SAV, complete Nadi analysis, current transits, and ALL
    FOUR dasha systems (vimshottari, yogini, chara, kalachakra) with full
    maha timelines plus the exact maha/antar running at at_iso (default now).
    Billed as 3 API calls. Cross-check houses (whole-sign vs chalit),
    strength (SAV/BAV), KP precision, Nadi delivery and multi-dasha timing
    before predicting."""
    b = _birth(year, month, day, hour, minute, latitude, longitude,
               tz_name, utc_offset_hours, ayanamsa)
    remote = _remote("POST", "/v1/full-analysis", dict(b, at_iso=at_iso))
    return remote if remote is not None else api.full_analysis(b, at_iso)


@mcp.tool()
def shadbala(year: int, month: int, day: int, hour: int, minute: int,
             latitude: float, longitude: float, tz_name: Optional[str] = None,
             utc_offset_hours: Optional[float] = None,
             ayanamsa: str = "lahiri") -> dict:
    """Shadbala six-fold planetary strength (BPHS): sthana, dig, kala,
    chesta, naisargika and drik balas in virupas/rupas for the 7 classical
    planets, with required minima, strength flags and ranking."""
    b = _birth(year, month, day, hour, minute, latitude, longitude,
               tz_name, utc_offset_hours, ayanamsa)
    remote = _remote("POST", "/v1/shadbala", b)
    return remote if remote is not None else api.shadbala_chart(b)


@mcp.tool()
def lal_kitab(year: int, month: int, day: int, hour: int, minute: int,
              latitude: float, longitude: float, tz_name: Optional[str] = None,
              utc_offset_hours: Optional[float] = None) -> dict:
    """Lal Kitab essentials: house chart, pakka ghar (permanent house)
    occupancy, and rins (karmic debts) with the traditional remedies."""
    b = _birth(year, month, day, hour, minute, latitude, longitude,
               tz_name, utc_offset_hours, "lahiri")
    remote = _remote("POST", "/v1/lal-kitab", b)
    return remote if remote is not None else api.lal_kitab(b)


@mcp.tool()
def varshphal(year: int, month: int, day: int, hour: int, minute: int,
              latitude: float, longitude: float, year_of_varsha: int,
              tz_name: Optional[str] = None,
              utc_offset_hours: Optional[float] = None) -> dict:
    """Varshphal (Tajika annual chart) for year_of_varsha: exact
    varshapravesh (solar return), varsha lagna, muntha, planet placements
    and the mudda dasha timeline of the year."""
    b = _birth(year, month, day, hour, minute, latitude, longitude,
               tz_name, utc_offset_hours, "lahiri")
    remote = _remote("POST", "/v1/varshphal", dict(b, year_of_varsha=year_of_varsha))
    return remote if remote is not None else api.varshphal(b, year_of_varsha)


@mcp.tool()
def gemstones(year: int, month: int, day: int, hour: int, minute: int,
              latitude: float, longitude: float, tz_name: Optional[str] = None,
              utc_offset_hours: Optional[float] = None) -> dict:
    """Gemstone recommendations from the lagna: life stone (lagna lord),
    fortune stone (9th lord) and wisdom stone (5th lord) with metal, finger,
    day and mantra — plus stones to avoid."""
    b = _birth(year, month, day, hour, minute, latitude, longitude,
               tz_name, utc_offset_hours, "lahiri")
    remote = _remote("POST", "/v1/gemstones", b)
    return remote if remote is not None else api.gemstone_recommendations(b)


@mcp.tool()
def festival_calendar(year: int, latitude: float = 28.6139,
                      longitude: float = 77.2090,
                      tz_name: str = "Asia/Kolkata") -> dict:
    """Hindu festival calendar for a year: Diwali, Holi, Navaratri,
    Janmashtami, Shivaratri and more (sidereal, amanta convention) plus all
    12 sankrantis with exact ingress times."""
    remote = _remote("GET", "/v1/festivals",
                     params={"year": year, "latitude": latitude,
                             "longitude": longitude, "tz_name": tz_name})
    return remote if remote is not None else api.festival_calendar(
        year, latitude, longitude, tz_name)


@mcp.tool()
def match_making(boy_year: int, boy_month: int, boy_day: int, boy_hour: int,
                 boy_minute: int, boy_latitude: float, boy_longitude: float,
                 girl_year: int, girl_month: int, girl_day: int, girl_hour: int,
                 girl_minute: int, girl_latitude: float, girl_longitude: float,
                 boy_tz_name: Optional[str] = None,
                 girl_tz_name: Optional[str] = None) -> dict:
    """Kundali matching between two people: Ashtakoot 36-guna score with
    per-koota detail, Dashakoot 10-porutham (South Indian), and a Manglik
    cross-check. Billed as 2 API calls."""
    boy = _birth(boy_year, boy_month, boy_day, boy_hour, boy_minute,
                 boy_latitude, boy_longitude, boy_tz_name, None, "lahiri")
    girl = _birth(girl_year, girl_month, girl_day, girl_hour, girl_minute,
                  girl_latitude, girl_longitude, girl_tz_name, None, "lahiri")
    remote = _remote("POST", "/v1/match-making", {"boy": boy, "girl": girl})
    return remote if remote is not None else api.match_making(boy, girl)


@mcp.tool()
def dosha_analysis(year: int, month: int, day: int, hour: int, minute: int,
                   latitude: float, longitude: float, tz_name: Optional[str] = None,
                   utc_offset_hours: Optional[float] = None,
                   ayanamsa: str = "lahiri") -> dict:
    """Dosha analysis: Manglik (from Lagna/Moon/Venus with severity),
    Kaal Sarpa (with classical type), and life-long Sadhe Sati / Dhaiya
    windows including what is active right now."""
    b = _birth(year, month, day, hour, minute, latitude, longitude,
               tz_name, utc_offset_hours, ayanamsa)
    remote = _remote("POST", "/v1/doshas", b)
    return remote if remote is not None else api.dosha_analysis(b)


@mcp.tool()
def yoga_analysis(year: int, month: int, day: int, hour: int, minute: int,
                  latitude: float, longitude: float, tz_name: Optional[str] = None,
                  utc_offset_hours: Optional[float] = None,
                  ayanamsa: str = "lahiri") -> dict:
    """Classical yogas present in the rasi chart: Panch Mahapurusha,
    Gajakesari, Budhaditya, Sunapha/Anapha/Durudhara, Vesi/Vasi/Ubhayachari,
    Adhi, Amala, Vipareeta Raja, Parivartana, Dhana, Raja, Neecha Bhanga."""
    b = _birth(year, month, day, hour, minute, latitude, longitude,
               tz_name, utc_offset_hours, ayanamsa)
    remote = _remote("POST", "/v1/yogas", b)
    return remote if remote is not None else api.yoga_analysis(b)


@mcp.tool()
def muhurta_of_day(date: Optional[str] = None, latitude: float = 28.6139,
                   longitude: float = 77.2090,
                   tz_name: str = "Asia/Kolkata") -> dict:
    """Day timings for a date and place: sunrise/sunset, moonrise/moonset,
    Rahu Kalam, Yamaganda, Gulika Kalam, Abhijit muhurta and Brahma muhurta
    (date YYYY-MM-DD, defaults to today at New Delhi)."""
    params = {"latitude": latitude, "longitude": longitude, "tz_name": tz_name}
    if date:
        params["date"] = date
    remote = _remote("GET", "/v1/muhurta", params=params)
    return remote if remote is not None else api.muhurta_of_day(
        date, latitude, longitude, tz_name)


@mcp.tool()
def year_transits(year: int, ayanamsa: str = "lahiri",
                  include_moon: bool = False) -> dict:
    """Transit timeline for a calendar year: where each planet will be -
    per-planet sign occupancy periods, exact sign-ingress dates (with
    retrograde flag) and retrograde/direct station dates. Times in UTC,
    sidereal positions. Great for questions like 'when does Jupiter change
    signs next year?' or 'when is Saturn retrograde in 2026?'."""
    remote = _remote("GET", "/v1/year-transits",
                     params={"year": year, "ayanamsa": ayanamsa,
                             "include_moon": include_moon})
    return remote if remote is not None else api.transit_year(year, ayanamsa, include_moon)


@mcp.tool()
def transits(at_iso: Optional[str] = None, ayanamsa: str = "lahiri") -> dict:
    """Current sidereal planetary positions (gochar), or at a given ISO datetime."""
    params = {"ayanamsa": ayanamsa}
    if at_iso:
        params["at_iso"] = at_iso
    remote = _remote("GET", "/v1/transits", params=params)
    return remote if remote is not None else api.transits(at_iso, ayanamsa)


class _TokenMiddleware:
    """Serve /healthz and capture 'Authorization: Bearer udh_...' per request."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http" and scope.get("path") == "/healthz":
            await send({"type": "http.response.start", "status": 200,
                        "headers": [(b"content-type", b"application/json")]})
            await send({"type": "http.response.body", "body": b'{"ok":true}'})
            return
        reset = None
        if scope.get("type") == "http":
            headers = {k.decode().lower(): v.decode()
                       for k, v in scope.get("headers", [])}
            value = headers.get("authorization", "")
            if value.lower().startswith("bearer "):
                reset = _request_token.set(value[7:].strip())
            # This server is intentionally public (App Runner / API Gateway,
            # auth via bearer token), so neutralise the SDK's localhost-only
            # DNS-rebinding Host check by presenting a local Host downstream.
            rewritten = [(k, v) for k, v in scope.get("headers", [])
                         if k.lower() != b"host"]
            # Port must be present: the SDK allowlist matches "localhost:*".
            port = os.environ.get("MCP_PORT", "8100")
            rewritten.append((b"host", ("localhost:%s" % port).encode()))
            scope = dict(scope, headers=rewritten)
        try:
            await self.app(scope, receive, send)
        finally:
            if reset is not None:
                _request_token.reset(reset)


if __name__ == "__main__":
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    if transport == "http":
        import uvicorn
        mcp.settings.host = os.environ.get("MCP_HOST", "0.0.0.0")
        mcp.settings.port = int(os.environ.get("MCP_PORT", "8100"))
        app = _TokenMiddleware(mcp.streamable_http_app())
        uvicorn.run(app, host=mcp.settings.host, port=mcp.settings.port)
    else:
        mcp.run()
