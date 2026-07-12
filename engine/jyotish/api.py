"""High-level, JSON-friendly API over the Jyotish engine.

Every function takes plain scalars and returns plain dicts, so the same
surface serves the MCP server, the web backend, and the Claude tool-use loop.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional

from . import ashtakavarga as av
from . import charts, dasha, dasha_systems, ephemeris, kp, nadi, panchanga, vargas
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

    planet_lons = {name: data["longitude"] for name, data in positions.items()}
    return {
        "system": "KP (Krishnamurti Paddhati), Placidus cusps, true node",
        "meta": b.meta(),
        "cusps": kp.cusp_table(list(cusps)),
        "planets": planets,
        "significators": kp.significator_tables(planet_lons, list(cusps)[:12]),
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


def nadi_analysis(birth: Dict) -> Dict:
    """Nadi analysis: Meena stellar delivery chains, BNN karakas and
    sign-links, nadi-amsa (D-150), dignity, Jupiter jeeva timeline."""
    b = BirthData.from_dict(birth)
    positions = ephemeris.planet_positions(b.jd, b.ayanamsa)
    asc = ephemeris.ascendant(b.jd, b.latitude, b.longitude, b.ayanamsa)
    cusps, _ascmc = ephemeris.houses(b.jd, b.latitude, b.longitude, b"P", b.ayanamsa)
    planet_lons = {name: data["longitude"] for name, data in positions.items()}
    result = nadi.analyze(planet_lons, asc, list(cusps)[:12], b.utc, b.ayanamsa)
    result["meta"] = b.meta()
    return result


def transit_year(year: int, ayanamsa: str = "lahiri",
                 include_moon: bool = False) -> Dict:
    """Year transit timeline: where each planet is through the year -
    sign occupancy periods, exact ingress dates, retro/direct stations."""
    year = int(year)
    if not 1800 <= year <= 2400:
        raise ValueError("year must be between 1800 and 2400")
    return yt.year_transits(year, ayanamsa, include_moon)


def _as_dt(value) -> datetime:
    dt = datetime.fromisoformat(value) if isinstance(value, str) else value
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _active_chain(mahadashas: List[Dict], at: datetime) -> Optional[Dict]:
    """The maha (and its antar) covering `at` in any dasha system's timeline."""
    for maha in mahadashas:
        if _as_dt(maha["start"]) <= at < _as_dt(maha["end"]):
            active = {"lord": maha["lord"], "start": maha["start"], "end": maha["end"]}
            for antar in maha.get("antardashas", []):
                if _as_dt(antar["start"]) <= at < _as_dt(antar["end"]):
                    active["antardasha"] = antar
                    break
            return active
    return None


def full_analysis(birth: Dict, at_iso: Optional[str] = None) -> Dict:
    """One-call synthesis bundle for cross-system readings: rasi (D-1),
    navamsa (D-9), bhava chalit, KP with significator tables, Ashtakavarga,
    Nadi analysis, current transits, and ALL FOUR dasha systems — each with
    its full maha timeline, the running maha/antar at `at`, and antardasha
    detail for the running maha. Built so a prediction can be checked across
    houses (whole-sign vs chalit), strength (SAV/BAV), precision (KP sub
    lords), delivery (Nadi stellar chains) and multi-dasha timing at once."""
    at = _as_dt(at_iso) if at_iso else datetime.now(timezone.utc)

    rasi = birth_chart(birth)
    d9 = varga_chart(birth, "D9")
    bhava = bhava_chart(birth)
    kp_data = kp_chart(birth)
    av_data = ashtakavarga_chart(birth)
    nadi_data = nadi_analysis(birth)

    # Bound the Jupiter jeeva timeline to a working window around `at`.
    birth_year = int(birth["year"])
    age_now = at.year - birth_year
    nadi_data["jupiter_timeline"] = [
        row for row in nadi_data["jupiter_timeline"]
        if age_now - 2 <= row["age"] <= age_now + 15
    ]
    nadi_data["jupiter_timeline_window"] = "ages %d-%d (call nadi_analysis for all 80 years)" % (
        max(age_now - 2, 0), age_now + 15)

    dashas = {"at": at.isoformat()}
    for system in DASHA_SYSTEMS:
        timeline = dasha_periods(birth, 2, system)
        running = _active_chain(timeline["mahadashas"], at)
        dashas[system] = {
            "system": timeline["system"],
            "running": running,
            "running_antardashas": next(
                (m.get("antardashas", []) for m in timeline["mahadashas"]
                 if running and m["lord"] == running["lord"]
                 and m["start"] == running["start"]), []),
            "mahadashas": [{"lord": m["lord"], "start": m["start"], "end": m["end"]}
                           for m in timeline["mahadashas"]],
        }
    dashas["vimshottari_now_l3"] = current_dasha(birth, at.isoformat())

    return {
        "system": ("Full synthesis bundle: cross-check houses (whole-sign vs "
                   "chalit), strength (Ashtakavarga), precision (KP sub lords "
                   "and significators), delivery (Nadi stellar chains), and "
                   "timing across all four dasha systems before predicting."),
        "meta": rasi["meta"],
        "rasi": {"ascendant": rasi["ascendant"], "planets": rasi["planets"],
                 "houses": rasi["houses"]},
        "birth_panchanga": rasi["panchanga"],
        "navamsa": {"ascendant_sign": d9["ascendant_sign"],
                    "placements": d9["placements"]},
        "bhava_chalit": bhava["placements"],
        "kp": {"cusps": kp_data["cusps"], "planets": kp_data["planets"],
               "significators": kp_data["significators"]},
        "ashtakavarga": {"sav": av_data["sav"], "sav_total": av_data["sav_total"],
                         "bav_totals": av_data["bav_totals"], "bav": av_data["bav"]},
        "nadi": {k: v for k, v in nadi_data.items() if k != "meta"},
        "dashas": dashas,
        "transits_now": transits(at.isoformat())["planets"],
    }


def panchanga_for(birth: Dict) -> Dict:
    """Panchanga (tithi/vara/nakshatra/yoga/karana) for the birth moment."""
    b = BirthData.from_dict(birth)
    positions = ephemeris.planet_positions(b.jd, b.ayanamsa)
    result = panchanga.panchanga(
        positions["Sun"]["longitude"], positions["Moon"]["longitude"], b.local)
    result["meta"] = b.meta()
    return result
