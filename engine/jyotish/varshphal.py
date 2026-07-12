"""Varshphal (Tajika annual chart): solar return, muntha, mudda dasha.

The varsha begins at the exact moment the transiting Sun returns to its
natal sidereal longitude in the target year (varshapravesh). The chart is
cast for that moment at the birth place.
"""

from datetime import datetime, timedelta, timezone
from typing import Dict

from . import charts, ephemeris, panchanga
from .constants import SIGN_LORDS, SIGNS


def _sun_lon(dt: datetime, ayanamsa: str) -> float:
    jd = ephemeris.julian_day(dt)
    return ephemeris.planet_positions(jd, ayanamsa)["Sun"]["longitude"]


def _solar_return(birth_utc: datetime, natal_sun: float, year: int,
                  ayanamsa: str) -> datetime:
    """Moment the Sun returns to natal longitude near the birthday of `year`."""
    approx = birth_utc.replace(year=year)
    lo, hi = approx - timedelta(days=4), approx + timedelta(days=4)

    def delta(dt):
        d = (_sun_lon(dt, ayanamsa) - natal_sun + 180) % 360 - 180
        return d

    # Sun moves ~1°/day; bracket the zero crossing then bisect.
    while delta(lo) > 0:
        lo -= timedelta(days=2)
    while delta(hi) < 0:
        hi += timedelta(days=2)
    for _ in range(50):
        mid = lo + (hi - lo) / 2
        if delta(mid) < 0:
            lo = mid
        else:
            hi = mid
    return lo + (hi - lo) / 2


def compute(birth: Dict, year: int, ayanamsa: str = "lahiri") -> Dict:
    from .api import BirthData
    b = BirthData.from_dict(birth)
    natal_positions = ephemeris.planet_positions(b.jd, b.ayanamsa)
    natal_sun = natal_positions["Sun"]["longitude"]
    natal_asc = ephemeris.ascendant(b.jd, b.latitude, b.longitude, b.ayanamsa)

    if year < b.utc.year:
        raise ValueError("Varshphal year must be >= birth year")
    vp = _solar_return(b.utc, natal_sun, year, ayanamsa)
    age = year - b.utc.year  # completed years at this varshapravesh

    jd = ephemeris.julian_day(vp)
    positions = ephemeris.planet_positions(jd, ayanamsa)
    asc = ephemeris.ascendant(jd, b.latitude, b.longitude, ayanamsa)

    planets = {}
    for name, data in positions.items():
        entry = charts.format_longitude(data["longitude"])
        entry["retrograde"] = data["retrograde"]
        entry["nakshatra"] = panchanga.nakshatra_of(data["longitude"])
        entry["house_from_varsha_lagna"] = charts.whole_sign_house(
            data["longitude"], asc)
        planets[name] = entry

    # Muntha: natal lagna sign advanced one sign per completed year
    muntha_sign = (int((natal_asc % 360) // 30) + age) % 12
    muntha_house = (muntha_sign - int((asc % 360) // 30)) % 12 + 1

    # Mudda dasha: vimshottari compressed into the solar year, seeded from
    # the Moon's nakshatra at varshapravesh (365.25-day year convention).
    from .constants import DASHA_SEQUENCE
    mudda = []
    moon = positions["Moon"]["longitude"] % 360
    span = 360.0 / 27.0
    nak_idx = int(moon / span)
    frac_left = 1.0 - (moon - nak_idx * span) / span
    start_idx = nak_idx % 9
    t = vp
    for i in range(10):
        lord, years = DASHA_SEQUENCE[(start_idx + i) % 9]
        days = years / 120.0 * 365.25
        if i == 0:
            days *= frac_left
        end = t + timedelta(days=days)
        mudda.append({"lord": lord, "start": t.date().isoformat(),
                      "end": end.date().isoformat(),
                      "days": round(days, 1)})
        t = end
        if t >= vp + timedelta(days=366):
            break

    return {
        "system": "Varshphal (Tajika solar return)",
        "year": year, "age_completed": age,
        "varshapravesh_utc": vp.isoformat(),
        "varsha_lagna": charts.format_longitude(asc),
        "varsha_lagna_lord": SIGN_LORDS[int((asc % 360) // 30)],
        "muntha": {"sign": SIGNS[muntha_sign],
                   "house_in_varsha_chart": muntha_house,
                   "lord": SIGN_LORDS[muntha_sign]},
        "planets": planets,
        "mudda_dasha": mudda,
        "note": "Muntha advances one sign per completed year from the natal "
                "lagna; mudda dasha compresses vimshottari into the solar "
                "year from the varshapravesh Moon.",
    }
