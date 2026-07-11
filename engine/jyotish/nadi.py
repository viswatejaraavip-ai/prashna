"""Nadi analysis: stellar (Meena) delivery chains, BNN karakas & links,
nadi-amsa (D-150), planetary dignity, and the Jupiter (jeeva) timeline.

What is computed here is the exact, mechanical layer of Nadi work:

* Meena stellar system: a planet primarily delivers the results of its
  nakshatra (star) lord — we surface each planet's star lord, the houses that
  lord occupies/owns (Placidus), and the planet's own "deputies" (planets
  sitting in its stars).
* Bhrigu Nandi Nadi: fixed karakas, sign-based links between planets
  (conjunction / trine / opposition / 2-12 adjacency), and the year-by-year
  transit of Jupiter (jeeva karaka) over natal points, from the ephemeris.
* Nadi-amsa: the 150th division of a sign (12' each) as a number 1..150.
  (The classical amsa *names* vary by grantha and are not encoded here.)
"""

from datetime import datetime, timezone
from typing import Dict, List

import swisseph as swe

from . import ephemeris, kp
from .constants import SIGNS

KARAKAS = {
    "Jupiter": "Jeeva (self, native)", "Saturn": "Karma (profession)",
    "Sun": "Atma / father / authority", "Moon": "Mind / mother",
    "Venus": "Spouse / wealth / vehicles", "Mars": "Siblings / courage / land",
    "Mercury": "Intellect / speech / business", "Rahu": "Foreign / unconventional",
    "Ketu": "Moksha / detachment / ancestry",
}

_EXALT_SIGN = {"Sun": 0, "Moon": 1, "Mars": 9, "Mercury": 5, "Jupiter": 3,
               "Venus": 11, "Saturn": 6, "Rahu": 1, "Ketu": 7}
_OWN_SIGNS = {"Sun": [4], "Moon": [3], "Mars": [0, 7], "Mercury": [2, 5],
              "Jupiter": [8, 11], "Venus": [1, 6], "Saturn": [9, 10],
              "Rahu": [], "Ketu": []}

_LINK_TYPES = {0: "conjunction (same sign)", 4: "trine", 8: "trine",
               6: "opposition (7th)", 1: "2nd/12th", 11: "2nd/12th"}


def dignity(planet: str, sign: int) -> str:
    if _EXALT_SIGN.get(planet) == sign:
        return "exalted"
    if (_EXALT_SIGN.get(planet, -99) + 6) % 12 == sign:
        return "debilitated"
    if sign in _OWN_SIGNS.get(planet, []):
        return "own sign"
    return "neutral"


def nadiamsa(lon: float) -> int:
    """Nadi-amsa number 1..150 within the sign (12 arc-minutes each)."""
    return min(int((lon % 30.0) / (30.0 / 150.0)) + 1, 150)


def bnn_links(signs: Dict[str, int]) -> List[Dict]:
    """Sign-based planetary links as read in Bhrigu Nandi Nadi."""
    names = list(signs)
    out = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            diff = (signs[b] - signs[a]) % 12
            kind = _LINK_TYPES.get(min(diff, (12 - diff) % 12)
                                   if diff in (1, 11) else diff)
            if diff in _LINK_TYPES:
                out.append({"a": a, "b": b, "link": _LINK_TYPES[diff]})
    return out


def jupiter_timeline(birth_utc: datetime, natal_signs: Dict[str, int],
                     ayanamsa: str, years: int = 80) -> List[Dict]:
    """Transit Jupiter's sign on each birthday, with contacts to natal points.

    BNN reads life chapters through the jeeva karaka's movement; this uses the
    real ephemeris rather than the 1-sign-per-year approximation. Saturn's
    transit sign is included as the karma reference.
    """
    ephemeris.set_ayanamsa(ayanamsa)
    rows = []
    for age in range(0, years + 1):
        try:
            when = birth_utc.replace(year=birth_utc.year + age)
        except ValueError:  # Feb 29 birthdays
            when = birth_utc.replace(year=birth_utc.year + age, day=28)
        jd = ephemeris.julian_day(when.astimezone(timezone.utc))
        ju = swe.calc_ut(jd, swe.JUPITER, ephemeris.SIDEREAL_FLAGS)[0][0] % 360
        sa = swe.calc_ut(jd, swe.SATURN, ephemeris.SIDEREAL_FLAGS)[0][0] % 360
        ju_sign = int(ju // 30)
        hits = []
        for planet, ns in natal_signs.items():
            diff = (ju_sign - ns) % 12
            if diff == 0:
                hits.append({"natal": planet, "relation": "conjunction"})
            elif diff in (4, 8):
                hits.append({"natal": planet, "relation": "trine"})
            elif diff == 6:
                hits.append({"natal": planet, "relation": "opposition"})
        rows.append({
            "age": age, "year": birth_utc.year + age,
            "jupiter_sign": SIGNS[ju_sign], "saturn_sign": SIGNS[int(sa // 30)],
            "contacts": hits,
        })
    return rows


def analyze(planet_lons: Dict[str, float], asc_lon: float,
            cusps: List[float], birth_utc: datetime, ayanamsa: str) -> Dict:
    signs = {p: int((lon % 360) // 30) for p, lon in planet_lons.items()}

    planets = {}
    for p, lon in planet_lons.items():
        planets[p] = {
            "sign": SIGNS[signs[p]],
            "degrees_in_sign": round(lon % 30, 4),
            "dignity": dignity(p, signs[p]),
            "nadiamsa": nadiamsa(lon),
            "star_lord": kp.star_lord(lon),
            "sub_lord": kp.sub_lord(lon),
        }
    lagna = {
        "sign": SIGNS[int((asc_lon % 360) // 30)],
        "nadiamsa": nadiamsa(asc_lon),
        "star_lord": kp.star_lord(asc_lon),
        "sub_lord": kp.sub_lord(asc_lon),
    }

    # Meena stellar delivery: planet -> star lord -> that lord's houses.
    sig = kp.significator_tables(planet_lons, cusps)
    stellar = {}
    for p in planet_lons:
        s = sig["planets"][p]
        deputies = [q for q in planet_lons if kp.star_lord(planet_lons[q]) == p]
        stellar[p] = {
            "star_lord": s["star_lord"],
            "delivers_house_of_star_lord": s["star_lord_house"],
            "delivers_houses_owned_by_star_lord": s["star_lord_owns"],
            "own_house": s["own_house"],
            "own_houses_owned": s["owns"],
            "in_own_star": s["star_lord"] == p,
            "deputies": deputies,  # planets acting as this planet's agents
        }

    return {
        "system": ("Nadi: Meena stellar delivery, BNN karakas/links, "
                   "nadi-amsa (D-150), Jupiter jeeva timeline"),
        "karakas": KARAKAS,
        "lagna": lagna,
        "planets": planets,
        "stellar": stellar,
        "bnn_links": bnn_links(signs),
        "jupiter_timeline": jupiter_timeline(birth_utc, signs, ayanamsa),
    }
