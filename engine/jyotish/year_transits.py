"""Year transit timeline: sign ingresses, occupancy periods and stations.

For a calendar year (UTC), scans each graha's sidereal longitude with a
per-planet step, then bisects every sign change (ingress) and speed reversal
(retrograde/direct station) down to ~1 minute.
"""

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import swisseph as swe

from . import ephemeris
from .constants import SIGNS

# Scan step in days, chosen safely below each planet's shortest sign stay.
_STEP_DAYS = {
    "Sun": 2.0, "Moon": 0.15, "Mercury": 1.0, "Venus": 1.0, "Mars": 2.0,
    "Jupiter": 5.0, "Saturn": 5.0, "Rahu": 5.0, "Ketu": 5.0,
}
# Planets that can station (luminaries never; mean nodes are always retro).
_STATION_PLANETS = ["Mercury", "Venus", "Mars", "Jupiter", "Saturn"]

_PLANET_IDS = {
    "Sun": swe.SUN, "Moon": swe.MOON, "Mercury": swe.MERCURY,
    "Venus": swe.VENUS, "Mars": swe.MARS, "Jupiter": swe.JUPITER,
    "Saturn": swe.SATURN, "Rahu": swe.MEAN_NODE,
}


def _calc(jd: float, planet: str):
    """(sidereal longitude, speed) for a planet at jd."""
    if planet == "Ketu":
        lon, speed = _calc(jd, "Rahu")
        return (lon + 180.0) % 360.0, speed
    values, _flags = swe.calc_ut(jd, _PLANET_IDS[planet], ephemeris.SIDEREAL_FLAGS)
    return values[0] % 360.0, values[3]


def _jd_to_iso(jd: float) -> str:
    y, m, d, h = swe.revjul(jd)
    hh = int(h)
    mm = int(round((h - hh) * 60))
    if mm == 60:
        hh, mm = hh + 1, 0
    return datetime(y, m, d, min(hh, 23), min(mm, 59),
                    tzinfo=timezone.utc).isoformat()


def _bisect(planet: str, jd0: float, jd1: float, changed) -> float:
    """Refine the moment `changed(jd)` flips between jd0 and jd1 (~1 min)."""
    for _ in range(40):
        if (jd1 - jd0) < (1.0 / 1440.0):
            break
        mid = (jd0 + jd1) / 2.0
        if changed(mid):
            jd1 = mid
        else:
            jd0 = mid
    return jd1


def year_transits(year: int, ayanamsa: str = "lahiri",
                  include_moon: bool = False) -> Dict:
    ephemeris.set_ayanamsa(ayanamsa)
    jd_start = swe.julday(year, 1, 1, 0.0)
    jd_end = swe.julday(year + 1, 1, 1, 0.0)

    planets = list(_STEP_DAYS.keys())
    if not include_moon:
        planets.remove("Moon")

    ingresses: List[Dict] = []
    stations: List[Dict] = []
    occupancy: Dict[str, List[Dict]] = {}

    for planet in planets:
        step = _STEP_DAYS[planet]
        jd = jd_start
        lon, speed = _calc(jd, planet)
        sign = int(lon // 30)
        periods = [{"sign": SIGNS[sign], "from": _jd_to_iso(jd_start), "to": None}]

        while jd < jd_end:
            jd_next = min(jd + step, jd_end)
            lon2, speed2 = _calc(jd_next, planet)
            sign2 = int(lon2 // 30)

            if sign2 != sign:
                target = sign2

                def sign_changed(j, p=planet, s=sign):
                    return int(_calc(j, p)[0] // 30) != s

                jd_x = _bisect(planet, jd, jd_next, sign_changed)
                lon_x, speed_x = _calc(jd_x, planet)
                new_sign = int(lon_x // 30)
                when = _jd_to_iso(jd_x)
                ingresses.append({
                    "planet": planet, "date": when,
                    "from_sign": SIGNS[sign], "to_sign": SIGNS[new_sign],
                    "retrograde": bool(speed_x < 0) and planet not in ("Sun", "Moon"),
                })
                periods[-1]["to"] = when
                periods.append({"sign": SIGNS[new_sign], "from": when, "to": None})
                sign = new_sign

            if planet in _STATION_PLANETS and (speed < 0) != (speed2 < 0):
                def speed_flipped(j, p=planet, was_neg=(speed < 0)):
                    return (_calc(j, p)[1] < 0) != was_neg

                jd_s = _bisect(planet, jd, jd_next, speed_flipped)
                lon_s, speed_s = _calc(jd_s, planet)
                stations.append({
                    "planet": planet, "date": _jd_to_iso(jd_s),
                    "type": "retrograde" if speed_s < 0 else "direct",
                    "sign": SIGNS[int(lon_s // 30)],
                    "degrees_in_sign": round(lon_s % 30, 2),
                })

            jd, lon, speed = jd_next, lon2, speed2

        periods[-1]["to"] = _jd_to_iso(jd_end)
        occupancy[planet] = periods

    ingresses.sort(key=lambda e: e["date"])
    stations.sort(key=lambda e: e["date"])
    return {
        "year": year,
        "ayanamsa": ayanamsa,
        "note": "All times UTC; sidereal positions.",
        "occupancy": occupancy,
        "ingresses": ingresses,
        "stations": stations,
    }
