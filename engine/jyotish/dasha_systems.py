"""Additional dasha systems: Yogini, Chara (Jaimini), Kalachakra.

Conventions (variants exist across traditions; these follow the most common
software implementations):

Yogini    - 8 yoginis over a 36-year cycle, started from the Moon's
            nakshatra: (nakshatra number + 3) mod 8. Sub-periods run in the
            same sequence starting from the running yogini, proportional to
            their years.
Chara     - K.N. Rao convention. Sequence starts at the lagna sign, direct
            for savya lagnas (Ar Ta Ge Li Sc Sg), reverse otherwise.
            Duration = count from sign to its lord (direct for savya signs,
            reverse for the rest) minus 1; lord in own sign = 12 years.
            Scorpio has co-lords Mars/Ketu, Aquarius Saturn/Rahu: the co-lord
            outside the sign is used; if both are outside, the longer period
            wins; if both are inside, 12 years. Antardashas: 12 equal parts
            starting from the sign after the mahadasha sign, in that sign's
            counting direction.
Kalachakra- BPHS pada sequences. Nakshatras alternate savya/apasavya in
            groups of three. Each pada maps to a fixed 9-navamsa chain whose
            total is the paramayu (savya 100/85/83/86, apasavya 86/83/85/100).
            The Moon's progress within its pada fixes the start point and
            balance. Antardashas are proportional (rasi years / paramayu of
            the chain), running along the chain from the mahadasha rasi.
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional

from .constants import NAKSHATRA_SPAN, SIGNS, YEAR_DAYS

# ---------------------------------------------------------------- Yogini

# (yogini, planet lord, years); cycle total 36 years.
YOGINI_SEQUENCE = [
    ("Mangala", "Moon", 1), ("Pingala", "Sun", 2), ("Dhanya", "Jupiter", 3),
    ("Bhramari", "Mars", 4), ("Bhadrika", "Mercury", 5), ("Ulka", "Saturn", 6),
    ("Siddha", "Venus", 7), ("Sankata", "Rahu", 8),
]
YOGINI_TOTAL = 36


def yogini(moon_longitude: float, birth_utc: datetime, cycles: int = 3) -> Dict:
    nak_index = int((moon_longitude % 360.0) / NAKSHATRA_SPAN) % 27
    traversed = (moon_longitude % NAKSHATRA_SPAN) / NAKSHATRA_SPAN
    start_index = (nak_index + 1 + 3) % 8 - 1  # (nak number + 3) mod 8, 0-based
    if start_index < 0:
        start_index = 7

    name0, lord0, years0 = YOGINI_SEQUENCE[start_index]
    elapsed_days = years0 * YEAR_DAYS * traversed
    cursor = birth_utc - timedelta(days=elapsed_days)

    mahadashas = []
    for i in range(8 * max(1, cycles)):
        name, lord, years = YOGINI_SEQUENCE[(start_index + i) % 8]
        days = years * YEAR_DAYS
        antars = []
        sub_cursor = cursor
        for j in range(8):
            s_name, s_lord, s_years = YOGINI_SEQUENCE[(start_index + i + j) % 8]
            s_days = days * s_years / YOGINI_TOTAL
            antars.append({
                "lord": "%s (%s)" % (s_name, s_lord),
                "start": sub_cursor.isoformat(),
                "end": (sub_cursor + timedelta(days=s_days)).isoformat(),
            })
            sub_cursor += timedelta(days=s_days)
        mahadashas.append({
            "lord": "%s (%s)" % (name, lord),
            "start": cursor.isoformat(),
            "end": (cursor + timedelta(days=days)).isoformat(),
            "years": years,
            "antardashas": antars,
        })
        cursor += timedelta(days=days)

    return {
        "system": "Yogini",
        "cycle_years": YOGINI_TOTAL,
        "birth_lord": "%s (%s)" % (name0, lord0),
        "balance_years_at_birth": round(years0 * (1 - traversed), 4),
        "mahadashas": mahadashas,
    }


# ---------------------------------------------------------------- Chara

SAVYA_SIGNS = {0, 1, 2, 6, 7, 8}  # Ar Ta Ge Li Sc Sg
_SIGN_MAIN_LORD = ["Mars", "Venus", "Mercury", "Moon", "Sun", "Mercury",
                   "Venus", "Mars", "Jupiter", "Saturn", "Saturn", "Jupiter"]
_CO_LORDS = {7: ["Mars", "Ketu"], 10: ["Saturn", "Rahu"]}  # Scorpio, Aquarius


def _chara_years(sign: int, planet_signs: Dict[str, int]) -> int:
    def years_via(lord: str) -> int:
        lord_sign = planet_signs[lord]
        if lord_sign == sign:
            return 12
        if sign in SAVYA_SIGNS:
            count = (lord_sign - sign) % 12 + 1
        else:
            count = (sign - lord_sign) % 12 + 1
        return count - 1

    if sign in _CO_LORDS:
        a, b = _CO_LORDS[sign]
        a_in = planet_signs[a] == sign
        b_in = planet_signs[b] == sign
        if a_in and b_in:
            return 12
        if a_in:
            return years_via(b)
        if b_in:
            return years_via(a)
        return max(years_via(a), years_via(b))
    return years_via(_SIGN_MAIN_LORD[sign])


def chara(asc_longitude: float, planet_longitudes: Dict[str, float],
          birth_utc: datetime) -> Dict:
    planet_signs = {name: int((lon % 360.0) // 30)
                    for name, lon in planet_longitudes.items()}
    lagna_sign = int((asc_longitude % 360.0) // 30)
    direction = 1 if lagna_sign in SAVYA_SIGNS else -1

    mahadashas = []
    cursor = birth_utc
    for i in range(12):
        sign = (lagna_sign + direction * i) % 12
        years = _chara_years(sign, planet_signs)
        days = years * YEAR_DAYS
        sub_dir = 1 if sign in SAVYA_SIGNS else -1
        antars = []
        sub_cursor = cursor
        for j in range(1, 13):
            sub_sign = (sign + sub_dir * j) % 12
            s_days = days / 12.0
            antars.append({
                "lord": SIGNS[sub_sign],
                "start": sub_cursor.isoformat(),
                "end": (sub_cursor + timedelta(days=s_days)).isoformat(),
            })
            sub_cursor += timedelta(days=s_days)
        mahadashas.append({
            "lord": SIGNS[sign],
            "start": cursor.isoformat(),
            "end": (cursor + timedelta(days=days)).isoformat(),
            "years": years,
            "antardashas": antars,
        })
        cursor += timedelta(days=days)

    return {
        "system": "Chara (K.N. Rao convention)",
        "lagna_sign": SIGNS[lagna_sign],
        "direction": "direct" if direction == 1 else "reverse",
        "mahadashas": mahadashas,
    }


# ---------------------------------------------------------------- Kalachakra

# Dasha years by rasi (fixed by sign lord).
KC_YEARS = {
    "Aries": 7, "Taurus": 16, "Gemini": 9, "Cancer": 21, "Leo": 5, "Virgo": 9,
    "Libra": 16, "Scorpio": 7, "Sagittarius": 10,
    "Capricorn": 4, "Aquarius": 4, "Pisces": 10,
}

# Savya pada chains (BPHS); paramayus 100, 85, 83, 86.
KC_SAVYA = [
    ["Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo", "Libra", "Scorpio", "Sagittarius"],
    ["Capricorn", "Aquarius", "Pisces", "Scorpio", "Libra", "Virgo", "Cancer", "Leo", "Gemini"],
    ["Taurus", "Aries", "Pisces", "Aquarius", "Capricorn", "Sagittarius", "Scorpio", "Libra", "Virgo"],
    ["Cancer", "Leo", "Gemini", "Taurus", "Aries", "Pisces", "Aquarius", "Capricorn", "Sagittarius"],
]
# Apasavya chains are the savya chains read in full reverse; paramayus 86, 83, 85, 100.
KC_APASAVYA = [list(reversed(KC_SAVYA[3 - i])) for i in range(4)]


def _kc_chain(moon_longitude: float):
    nak_index = int((moon_longitude % 360.0) / NAKSHATRA_SPAN) % 27
    savya = (nak_index // 3) % 2 == 0
    within_nak = (moon_longitude % 360.0) - nak_index * NAKSHATRA_SPAN
    pada_span = NAKSHATRA_SPAN / 4.0
    pada = min(int(within_nak / pada_span), 3)
    frac_in_pada = (within_nak - pada * pada_span) / pada_span
    chain = (KC_SAVYA if savya else KC_APASAVYA)[pada]
    return chain, savya, pada, frac_in_pada


def kalachakra(moon_longitude: float, birth_utc: datetime) -> Dict:
    chain, savya, pada, frac = _kc_chain(moon_longitude)
    paramayu = sum(KC_YEARS[r] for r in chain)

    # How far into the paramayu the birth falls.
    elapsed_years = frac * paramayu
    idx = 0
    while elapsed_years >= KC_YEARS[chain[idx]]:
        elapsed_years -= KC_YEARS[chain[idx]]
        idx += 1

    first_rasi = chain[idx]
    balance = KC_YEARS[first_rasi] - elapsed_years
    cursor = birth_utc - timedelta(days=elapsed_years * YEAR_DAYS)

    mahadashas = []
    for i in range(9):  # one full paramayu from the running rasi onward
        rasi = chain[(idx + i) % 9]
        years = KC_YEARS[rasi]
        days = years * YEAR_DAYS
        antars = []
        sub_cursor = cursor
        for j in range(9):
            s_rasi = chain[(idx + i + j) % 9]
            s_days = days * KC_YEARS[s_rasi] / paramayu
            antars.append({
                "lord": s_rasi,
                "start": sub_cursor.isoformat(),
                "end": (sub_cursor + timedelta(days=s_days)).isoformat(),
            })
            sub_cursor += timedelta(days=s_days)
        mahadashas.append({
            "lord": rasi,
            "start": cursor.isoformat(),
            "end": (cursor + timedelta(days=days)).isoformat(),
            "years": years,
            "antardashas": antars,
        })
        cursor += timedelta(days=days)

    return {
        "system": "Kalachakra (BPHS)",
        "group": "savya" if savya else "apasavya",
        "pada": pada + 1,
        "paramayu_years": paramayu,
        "deha_rasi": chain[0],
        "jeeva_rasi": chain[-1],
        "balance_years_at_birth": round(balance, 4),
        "mahadashas": mahadashas,
    }
