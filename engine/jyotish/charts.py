"""House systems: whole-sign rasi houses and Sripati bhava chalit."""

from typing import Dict, List

from . import ephemeris
from .constants import SIGNS, SIGN_LORDS


def format_longitude(lon: float) -> Dict:
    lon = lon % 360.0
    sign = int(lon // 30)
    deg_in_sign = lon - sign * 30
    d = int(deg_in_sign)
    m_float = (deg_in_sign - d) * 60
    m = int(m_float)
    s = int(round((m_float - m) * 60))
    if s == 60:
        s, m = 0, m + 1
    if m == 60:
        m, d = 0, d + 1
    return {
        "longitude": round(lon, 6),
        "sign": SIGNS[sign],
        "sign_index": sign,
        "sign_lord": SIGN_LORDS[sign],
        "degrees_in_sign": round(deg_in_sign, 4),
        "dms": "%02d°%02d'%02d\"" % (d, m, s),
    }


def whole_sign_house(planet_lon: float, asc_lon: float) -> int:
    """House number 1-12 counting signs from the ascendant sign."""
    asc_sign = int((asc_lon % 360.0) // 30)
    p_sign = int((planet_lon % 360.0) // 30)
    return (p_sign - asc_sign) % 12 + 1


def bhava_chalit(jd: float, lat: float, lon: float, positions: Dict[str, Dict],
                 ayanamsa: str = "lahiri") -> Dict:
    """Sripati bhava: Porphyry cusps as bhava madhya, boundaries at midpoints.

    A planet belongs to the bhava whose span (sandhi to sandhi) contains it.
    """
    cusps, ascmc = ephemeris.houses(jd, lat, lon, b"O", ayanamsa)  # Porphyry
    madhya = [c % 360.0 for c in cusps[:12]]  # pyswisseph returns 12 cusps, 0-indexed

    def midpoint(a: float, b: float) -> float:
        diff = (b - a) % 360.0
        return (a + diff / 2.0) % 360.0

    # bhava i spans from midpoint(prev madhya, its madhya) to midpoint(its madhya, next madhya)
    starts = [midpoint(madhya[(i - 1) % 12], madhya[i]) for i in range(12)]

    def house_of(p_lon: float) -> int:
        p_lon = p_lon % 360.0
        for i in range(12):
            start = starts[i]
            end = starts[(i + 1) % 12]
            span = (end - start) % 360.0
            if (p_lon - start) % 360.0 < span:
                return i + 1
        return 12

    placements = {}
    for name, data in positions.items():
        placements[name] = house_of(data["longitude"])

    return {
        "system": "Sripati (Porphyry madhya)",
        "bhava_madhya": [round(m, 4) for m in madhya],
        "bhava_start": [round(s, 4) for s in starts],
        "placements": placements,
    }


def houses_summary(positions: Dict[str, Dict], asc_lon: float) -> List[Dict]:
    """Whole-sign houses with occupants, house 1 = ascendant sign."""
    asc_sign = int((asc_lon % 360.0) // 30)
    houses = []
    for h in range(12):
        sign_idx = (asc_sign + h) % 12
        occupants = [
            name for name, d in positions.items()
            if int((d["longitude"] % 360.0) // 30) == sign_idx
        ]
        houses.append({
            "house": h + 1,
            "sign": SIGNS[sign_idx],
            "sign_lord": SIGN_LORDS[sign_idx],
            "planets": occupants,
        })
    return houses
