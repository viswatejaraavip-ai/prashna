"""High-level, JSON-friendly API over the Jyotish engine.

Every function takes plain scalars and returns plain dicts, so the same
surface serves the MCP server, the web backend, and the Claude tool-use loop.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional

from . import ashtakavarga as av
from . import charts, dasha, dasha_systems, ephemeris, kp, panchanga, vargas
from . import year_transits as yt
from .constants import SIGNS, VARGA_LIST, VARGA_SIGNIFICATIONS


class BirthData:
    def __init__(self, year: int, month: int, day: int, hour: int, minute: int,
                 latitude: float, longitude: float, second: int = 0,
                 tz_name: Optional[str] = None, utc_offset_hours: Optional[float] = None,
                 ayanamsa: str = "lahiri"):
        self.local = datetime(year, month, day, hour, minute, second)
        self.utc = ephemeris.to_utc(year, month, day, hour, minute, second,
                                    tz_name=tz_name, utc_offset_hours=utc_offset_hours)
        self.jd = ephemeris.julian_day(self.utc)
        self.latitude = latitude
        self.longitude = longitude
        self.ayanamsa = ayanamsa

    @classmethod
    def from_dict(cls, d: Dict) -> "BirthData":
        return cls(
            year=int(d["year"]), month=int(d["month"]), day=int(d["day"]),
            hour=int(d["hour"]), minute=int(d["minute"]), second=int(d.get("second", 0)),
            latitude=float(d["latitude"]), longitude=float(d["longitude"]),
            tz_name=d.get("tz_name"),
            utc_offset_hours=(float(d["utc_offset_hours"])
                              if d.get("utc_offset_hours") is not None else None),
            ayanamsa=d.get("ayanamsa", "lahiri"),
        )

    def meta(self) -> Dict:
        return {
            "local_time": self.local.isoformat(),
            "utc_time": self.utc.isoformat(),
            "julian_day": round(self.jd, 6),
            "latitude": self.latitude,
            "longitude": self.longitude,
            "ayanamsa": self.ayanamsa,
            "ayanamsa_value_deg": round(
                ephemeris.get_ayanamsa_value(self.jd, self.ayanamsa), 6),
        }


def birth_chart(birth: Dict) -> Dict:
    """Rasi (D-1) chart: positions, ascendant, whole-sign houses, nakshatras."""
    b = BirthData.from_dict(birth)
    positions = ephemeris.planet_positions(b.jd, b.ayanamsa)
    asc = ephemeris.ascendant(b.jd, b.latitude, b.longitude, b.ayanamsa)

    planets = {}
    for name, data in positions.items():
        entry = charts.format_longitude(data["longitude"])
        entry["retrograde"] = data["retrograde"]
        entry["speed"] = round(data["speed"], 6)
        entry["nakshatra"] = panchanga.nakshatra_of(data["longitude"])
        entry["house_whole_sign"] = charts.whole_sign_house(data["longitude"], asc)
        planets[name] = entry

    return {
        "meta": b.meta(),
        "ascendant": charts.format_longitude(asc),
        "planets": planets,
        "houses": charts.houses_summary(positions, asc),
        "panchanga": panchanga.panchanga(
            positions["Sun"]["longitude"], positions["Moon"]["longitude"], b.local),
    }


def bhava_chart(birth: Dict) -> Dict:
    """Bhava chalit (Sripati) placements — can differ from whole-sign houses."""
    b = BirthData.from_dict(birth)
    positions = ephemeris.planet_positions(b.jd, b.ayanamsa)
    result = charts.bhava_chalit(b.jd, b.latitude, b.longitude, positions, b.ayanamsa)
    result["meta"] = b.meta()
    return result


def varga_chart(birth: Dict, varga: str) -> Dict:
    """A single divisional chart (D1..D60) with planets + lagna in varga signs."""
    b = BirthData.from_dict(birth)
    key = varga.upper()
    positions = ephemeris.planet_positions(b.jd, b.ayanamsa)
    asc = ephemeris.ascendant(b.jd, b.latitude, b.longitude, b.ayanamsa)

    asc_sign = vargas.varga_sign(asc, key)
    placements = {}
    for name, data in positions.items():
        v_sign = vargas.varga_sign(data["longitude"], key)
        placements[name] = {
            "sign": SIGNS[v_sign],
            "sign_index": v_sign,
            "house_from_varga_lagna": (v_sign - asc_sign) % 12 + 1,
        }
    return {
        "varga": key,
        "signification": VARGA_SIGNIFICATIONS.get(key, ""),
        "ascendant_sign": SIGNS[asc_sign],
        "placements": placements,
        "meta": b.meta(),
    }


def all_vargas(birth: Dict) -> Dict:
    """All 16 classical divisional charts in one call (compact form)."""
    b = BirthData.from_dict(birth)
    positions = ephemeris.planet_positions(b.jd, b.ayanamsa)
    asc = ephemeris.ascendant(b.jd, b.latitude, b.longitude, b.ayanamsa)

    out = {"meta": b.meta(), "charts": {}}
    for key in VARGA_LIST:
        asc_sign = vargas.varga_sign(asc, key)
        chart = {"Lagna": SIGNS[asc_sign]}
        for name, data in positions.items():
            chart[name] = SIGNS[vargas.varga_sign(data["longitude"], key)]
        out["charts"][key] = chart
    return out


DASHA_SYSTEMS = ["vimshottari", "yogini", "chara", "kalachakra"]


def dasha_periods(birth: Dict, levels: int = 2, system: str = "vimshottari") -> Dict:
    """Dasha timeline in the requested system.

    system: vimshottari (default; levels 1-3), yogini, chara (Jaimini,
    K.N. Rao convention), kalachakra (BPHS). Non-vimshottari systems always
    include antardashas.
    """
    b = BirthData.from_dict(birth)
    positions = ephemeris.planet_positions(b.jd, b.ayanamsa)
    moon = positions["Moon"]["longitude"]
    key = (system or "vimshottari").lower().strip()

    if key == "vimshottari":
        return dasha.vimshottari(moon, b.utc, levels=min(int(levels), 3))
    if key == "yogini":
        return dasha_systems.yogini(moon, b.utc)
    if key == "chara":
        asc = ephemeris.ascendant(b.jd, b.latitude, b.longitude, b.ayanamsa)
        lons = {name: data["longitude"] for name, data in positions.items()}
        return dasha_systems.chara(asc, lons, b.utc)
    if key == "kalachakra":
        return dasha_systems.kalachakra(moon, b.utc)
    raise ValueError("Unknown dasha system '%s'. Supported: %s"
                     % (system, ", ".join(DASHA_SYSTEMS)))


def current_dasha(birth: Dict, at_iso: Optional[str] = None) -> Dict:
    """Dasha lords running now (or at a given ISO datetime, UTC)."""
    b = BirthData.from_dict(birth)
    positions = ephemeris.planet_positions(b.jd, b.ayanamsa)
    at = None
    if at_iso:
        at = datetime.fromisoformat(at_iso)
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
    else:
        at = datetime.now(timezone.utc)
    return dasha.current_dasha(positions["Moon"]["longitude"], b.utc, at=at)


def transits(at_iso: Optional[str] = None, ayanamsa: str = "lahiri") -> Dict:
    """Current (or given-time) sidereal planetary positions."""
    at = datetime.fromisoformat(at_iso) if at_iso else datetime.now(timezone.utc)
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    at = at.astimezone(timezone.utc)
    jd = ephemeris.julian_day(at)
    positions = ephemeris.planet_positions(jd, ayanamsa)
    out = {"utc_time": at.isoformat(), "ayanamsa": ayanamsa, "planets": {}}
    for name, data in positions.items():
        entry = charts.format_longitude(data["longitude"])
        entry["retrograde"] = data["retrograde"]
        entry["nakshatra"] = panchanga.nakshatra_of(data["longitude"])
        out["planets"][name] = entry
    return out


def kp_chart(birth: Dict) -> Dict:
    """KP analysis: sign/star/sub/sub-sub lords for all planets and the 12
    Placidus house cusps. Uses the Krishnamurti ayanamsa unless overridden."""
    birth = dict(birth)
    birth.setdefault("ayanamsa", "kp")
    if birth["ayanamsa"] is None:
        birth["ayanamsa"] = "kp"
    b = BirthData.from_dict(birth)
    positions = ephemeris.planet_positions(b.jd, b.ayanamsa)
    cusps, _ascmc = ephemeris.houses(b.jd, b.latitude, b.longitude, b"P", b.ayanamsa)

    planets = {}
    for name, data in positions.items():
        row = kp.significators(data["longitude"])
        row["retrograde"] = data["retrograde"]
        planets[name] = row

    return {
        "system": "KP (Krishnamurti Paddhati), Placidus cusps",
        "meta": b.meta(),
        "cusps": kp.cusp_table(list(cusps)),
        "planets": planets,
    }


def ashtakavarga_chart(birth: Dict) -> Dict:
    """Ashtakavarga: Bhinnashtakavarga for the 7 planets and Sarvashtakavarga."""
    b = BirthData.from_dict(birth)
    positions = ephemeris.planet_positions(b.jd, b.ayanamsa)
    asc = ephemeris.ascendant(b.jd, b.latitude, b.longitude, b.ayanamsa)
    contributor_signs = {
        name: int((positions[name]["longitude"] % 360.0) // 30)
        for name in av.AV_PLANETS
    }
    contributor_signs["Ascendant"] = int((asc % 360.0) // 30)
    result = av.compute(contributor_signs)
    result["meta"] = b.meta()
    result["ascendant_sign"] = SIGNS[contributor_signs["Ascendant"]]
    return result


def panchanga_now(latitude: Optional[float] = None, longitude: Optional[float] = None,
                  tz_name: Optional[str] = None) -> Dict:
    """Panchanga of the current moment plus current transits."""
    now_utc = datetime.now(timezone.utc)
    local = now_utc
    if tz_name:
        try:
            from zoneinfo import ZoneInfo
            local = now_utc.astimezone(ZoneInfo(tz_name))
        except Exception:
            pass
    jd = ephemeris.julian_day(now_utc)
    positions = ephemeris.planet_positions(jd, "lahiri")
    result = panchanga.panchanga(
        positions["Sun"]["longitude"], positions["Moon"]["longitude"],
        local.replace(tzinfo=None))
    result["local_time"] = local.isoformat()
    result["transits"] = {}
    for name, data in positions.items():
        entry = charts.format_longitude(data["longitude"])
        entry["retrograde"] = data["retrograde"]
        entry["nakshatra"] = panchanga.nakshatra_of(data["longitude"])
        result["transits"][name] = entry
    return result


def transit_year(year: int, ayanamsa: str = "lahiri",
                 include_moon: bool = False) -> Dict:
    """Year transit timeline: where each planet is through the year -
    sign occupancy periods, exact ingress dates, retro/direct stations."""
    year = int(year)
    if not 1800 <= year <= 2400:
        raise ValueError("year must be between 1800 and 2400")
    return yt.year_transits(year, ayanamsa, include_moon)


def panchanga_for(birth: Dict) -> Dict:
    """Panchanga (tithi/vara/nakshatra/yoga/karana) for the birth moment."""
    b = BirthData.from_dict(birth)
    positions = ephemeris.planet_positions(b.jd, b.ayanamsa)
    result = panchanga.panchanga(
        positions["Sun"]["longitude"], positions["Moon"]["longitude"], b.local)
    result["meta"] = b.meta()
    return result
