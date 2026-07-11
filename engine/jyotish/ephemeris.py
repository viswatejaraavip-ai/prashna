"""Swiss Ephemeris wrapper: sidereal planetary positions and houses.

Uses the built-in Moshier ephemeris by default (no data files needed,
accuracy well under 1 arcsecond for planets). Set SE_EPHE_PATH to a
directory containing Swiss Ephemeris data files (sepl*.se1 etc.) for
maximum precision.
"""

import os
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Tuple

import swisseph as swe

try:
    from zoneinfo import ZoneInfo
except ImportError:  # Python < 3.9 fallback (not expected)
    ZoneInfo = None

_EPHE_PATH = os.environ.get("SE_EPHE_PATH")
if _EPHE_PATH:
    swe.set_ephe_path(_EPHE_PATH)
    _BASE_FLAGS = swe.FLG_SWIEPH | swe.FLG_SPEED
else:
    _BASE_FLAGS = swe.FLG_MOSEPH | swe.FLG_SPEED

SIDEREAL_FLAGS = _BASE_FLAGS | swe.FLG_SIDEREAL

AYANAMSAS = {
    "lahiri": swe.SIDM_LAHIRI,
    "raman": swe.SIDM_RAMAN,
    "kp": swe.SIDM_KRISHNAMURTI,
    "krishnamurti": swe.SIDM_KRISHNAMURTI,
    "fagan_bradley": swe.SIDM_FAGAN_BRADLEY,
    "yukteshwar": swe.SIDM_YUKTESHWAR,
}

# True node is the default (KP convention, and what most modern Indian
# software uses). Set NODE_TYPE=mean for the mean node.
_NODE_ID = swe.MEAN_NODE if os.environ.get("NODE_TYPE", "true").lower() == "mean" \
    else swe.TRUE_NODE

_PLANET_IDS = {
    "Sun": swe.SUN,
    "Moon": swe.MOON,
    "Mars": swe.MARS,
    "Mercury": swe.MERCURY,
    "Jupiter": swe.JUPITER,
    "Venus": swe.VENUS,
    "Saturn": swe.SATURN,
    "Rahu": _NODE_ID,
}


def set_ayanamsa(name: str) -> None:
    key = name.lower().strip()
    if key not in AYANAMSAS:
        raise ValueError(
            "Unknown ayanamsa '%s'. Supported: %s" % (name, ", ".join(sorted(AYANAMSAS)))
        )
    swe.set_sid_mode(AYANAMSAS[key], 0, 0)


def to_utc(
    year: int, month: int, day: int, hour: int, minute: int, second: int = 0,
    tz_name: Optional[str] = None, utc_offset_hours: Optional[float] = None,
) -> datetime:
    """Convert a local birth time to UTC using an IANA timezone or fixed offset."""
    naive = datetime(year, month, day, hour, minute, second)
    if tz_name:
        if ZoneInfo is None:
            raise RuntimeError("zoneinfo unavailable; pass utc_offset_hours instead")
        local = naive.replace(tzinfo=ZoneInfo(tz_name))
        return local.astimezone(timezone.utc)
    if utc_offset_hours is not None:
        return (naive - timedelta(hours=utc_offset_hours)).replace(tzinfo=timezone.utc)
    # No tz info given: treat the input as UTC already.
    return naive.replace(tzinfo=timezone.utc)


def julian_day(dt_utc: datetime) -> float:
    hour = dt_utc.hour + dt_utc.minute / 60.0 + dt_utc.second / 3600.0
    return swe.julday(dt_utc.year, dt_utc.month, dt_utc.day, hour)


def get_ayanamsa_value(jd: float, ayanamsa: str = "lahiri") -> float:
    set_ayanamsa(ayanamsa)
    return swe.get_ayanamsa_ut(jd)


def planet_positions(jd: float, ayanamsa: str = "lahiri") -> Dict[str, Dict]:
    """Sidereal longitudes, speeds and retrograde flags for all 9 grahas."""
    set_ayanamsa(ayanamsa)
    out = {}
    for name, pid in _PLANET_IDS.items():
        values, _retflags = swe.calc_ut(jd, pid, SIDEREAL_FLAGS)
        lon, lat, dist, speed_lon = values[0], values[1], values[2], values[3]
        out[name] = {
            "longitude": lon % 360.0,
            "latitude": lat,
            "distance": dist,
            "speed": speed_lon,
            "retrograde": bool(speed_lon < 0) and name not in ("Sun", "Moon"),
        }
    # Ketu is always exactly opposite Rahu; nodes are always retrograde.
    rahu = out["Rahu"]
    out["Rahu"]["retrograde"] = True
    out["Ketu"] = {
        "longitude": (rahu["longitude"] + 180.0) % 360.0,
        "latitude": -rahu["latitude"],
        "distance": rahu["distance"],
        "speed": rahu["speed"],
        "retrograde": True,
    }
    return out


def houses(
    jd: float, lat: float, lon: float, hsys: bytes = b"P", ayanamsa: str = "lahiri",
) -> Tuple[Tuple[float, ...], Tuple[float, ...]]:
    """Sidereal house cusps and asc/mc. hsys: b'P' Placidus, b'O' Porphyry, b'W' whole sign."""
    set_ayanamsa(ayanamsa)
    cusps, ascmc = swe.houses_ex(jd, lat, lon, hsys, swe.FLG_SIDEREAL)
    return cusps, ascmc


def ascendant(jd: float, lat: float, lon: float, ayanamsa: str = "lahiri") -> float:
    _cusps, ascmc = houses(jd, lat, lon, b"P", ayanamsa)
    return ascmc[0] % 360.0
