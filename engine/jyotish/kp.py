"""KP (Krishnamurti Paddhati) calculations.

Each nakshatra (13d20') is divided into 9 unequal *subs* proportional to the
Vimshottari dasha years (Ketu 7, Venus 20, ... Mercury 17 over 120), starting
from the nakshatra's own lord. KP reads every position through the chain
  sign lord -> star (nakshatra) lord -> sub lord -> sub-sub lord
and uses Placidus house cusps with the Krishnamurti ayanamsa.
"""

from typing import Dict, List

from .constants import (
    DASHA_SEQUENCE, DASHA_TOTAL_YEARS, NAKSHATRAS, NAKSHATRA_SPAN,
    SIGNS, SIGN_LORDS,
)

_NAK_LORDS = [DASHA_SEQUENCE[i % 9][0] for i in range(27)]


def star_lord(lon: float) -> str:
    """Lord of the nakshatra occupied."""
    return _NAK_LORDS[int((lon % 360.0) / NAKSHATRA_SPAN) % 27]


def _sub_division(offset: float, start_lord_index: int, span: float):
    """Which of the 9 Vimshottari-proportioned divisions covers `offset`.

    Returns (lord, division_start, division_span) within a span that begins
    with the lord at start_lord_index.
    """
    cursor = 0.0
    for i in range(9):
        lord, years = DASHA_SEQUENCE[(start_lord_index + i) % 9]
        width = span * years / DASHA_TOTAL_YEARS
        if offset < cursor + width or i == 8:
            return lord, cursor, width
        cursor += width
    lord, years = DASHA_SEQUENCE[start_lord_index]
    return lord, 0.0, span * years / DASHA_TOTAL_YEARS


def sub_lord(lon: float) -> str:
    lon = lon % 360.0
    nak_index = int(lon / NAKSHATRA_SPAN) % 27
    within = lon - nak_index * NAKSHATRA_SPAN
    lord, _start, _width = _sub_division(within, nak_index % 9, NAKSHATRA_SPAN)
    return lord


def sub_sub_lord(lon: float) -> str:
    lon = lon % 360.0
    nak_index = int(lon / NAKSHATRA_SPAN) % 27
    within = lon - nak_index * NAKSHATRA_SPAN
    lord, start, width = _sub_division(within, nak_index % 9, NAKSHATRA_SPAN)
    # index of the sub lord in the dasha sequence
    sub_index = next(i for i, (name, _y) in enumerate(DASHA_SEQUENCE) if name == lord)
    lord2, _s2, _w2 = _sub_division(within - start, sub_index, width)
    return lord2


def significators(lon: float) -> Dict:
    """Full KP chain for one longitude."""
    lon = lon % 360.0
    sign_index = int(lon // 30)
    nak_index = int(lon / NAKSHATRA_SPAN) % 27
    return {
        "longitude": round(lon, 6),
        "sign": SIGNS[sign_index],
        "sign_lord": SIGN_LORDS[sign_index],
        "star": NAKSHATRAS[nak_index],
        "star_lord": _NAK_LORDS[nak_index],
        "sub_lord": sub_lord(lon),
        "sub_sub_lord": sub_sub_lord(lon),
    }


def cusp_table(cusps: List[float]) -> List[Dict]:
    out = []
    for i, c in enumerate(cusps[:12]):
        row = significators(c)
        row["cusp"] = i + 1
        out.append(row)
    return out


def occupied_house(lon: float, cusps: List[float]) -> int:
    """Which Placidus house (1-12) a longitude falls in."""
    lon = lon % 360.0
    for i in range(12):
        start = cusps[i] % 360.0
        end = cusps[(i + 1) % 12] % 360.0
        if (lon - start) % 360.0 < (end - start) % 360.0:
            return i + 1
    return 12


def significator_tables(planet_lons: Dict[str, float],
                        cusps: List[float]) -> Dict:
    """Classic KP significator tables.

    Planets: star lord's occupied house, own occupied house, houses owned by
    the star lord, houses owned by the planet.
    Houses: occupants, occupants' star lords, owner, planets in owner's stars.
    """
    house_owner = {i + 1: SIGN_LORDS[int((cusps[i] % 360.0) // 30)]
                   for i in range(12)}
    owned: Dict[str, List[int]] = {}
    for h, owner in house_owner.items():
        owned.setdefault(owner, []).append(h)

    occ = {p: occupied_house(lon, cusps) for p, lon in planet_lons.items()}
    star = {p: star_lord(lon) for p, lon in planet_lons.items()}

    planets_out = {}
    for p in planet_lons:
        planets_out[p] = {
            "star_lord": star[p],
            "star_lord_house": occ.get(star[p]),
            "own_house": occ[p],
            "star_lord_owns": sorted(owned.get(star[p], [])),
            "owns": sorted(owned.get(p, [])),
        }

    houses_out = {}
    for h in range(1, 13):
        occupants = [p for p, hh in occ.items() if hh == h]
        owner = house_owner[h]
        houses_out[h] = {
            "occupants": occupants,
            "occupants_star_lords": [star[p] for p in occupants],
            "owner": owner,
            "planets_in_owner_stars": [p for p in planet_lons
                                       if star[p] == owner],
        }
    return {"planets": planets_out, "houses": houses_out}
