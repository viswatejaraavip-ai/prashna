"""Shadbala — classical six-fold planetary strength (BPHS formulas).

Computed for the seven classical planets in virupas (60 virupas = 1 rupa):
  1. Sthana  (positional): uchcha, saptavargaja, ojayugma, kendradi, drekkana
  2. Dig     (directional)
  3. Kala    (temporal): natonnata, paksha, tribhaga, varsha/masa/vara/hora, ayana
  4. Chesta  (motional)
  5. Naisargika (natural)
  6. Drik    (aspectual, graded sputa-drishti)

Where the classical texts admit variant readings (chesta motion classes,
hora reckoning) the widely used software conventions are applied and noted.
"""

import math
from datetime import datetime, timedelta, timezone
from typing import Dict

import swisseph as swe

from . import ephemeris, muhurta, vargas
from .constants import SIGN_LORDS, SIGNS, WEEKDAYS

_SEVEN = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn"]

_EXALT_DEG = {"Sun": 10, "Moon": 33, "Mars": 298, "Mercury": 165,
              "Jupiter": 95, "Venus": 357, "Saturn": 200}
_MOOLATRIKONA = {"Sun": (4, 0, 20), "Moon": (1, 3, 30), "Mars": (0, 0, 12),
                 "Mercury": (5, 15, 20), "Jupiter": (8, 0, 10),
                 "Venus": (6, 0, 15), "Saturn": (10, 0, 20)}
_OWN = {"Sun": {4}, "Moon": {3}, "Mars": {0, 7}, "Mercury": {2, 5},
        "Jupiter": {8, 11}, "Venus": {1, 6}, "Saturn": {9, 10}}
_FRIENDS = {"Sun": {"Moon", "Mars", "Jupiter"}, "Moon": {"Sun", "Mercury"},
            "Mars": {"Sun", "Moon", "Jupiter"}, "Mercury": {"Sun", "Venus"},
            "Jupiter": {"Sun", "Moon", "Mars"}, "Venus": {"Mercury", "Saturn"},
            "Saturn": {"Mercury", "Venus"}}
_ENEMIES = {"Sun": {"Venus", "Saturn"}, "Moon": set(), "Mars": {"Mercury"},
            "Mercury": {"Moon"}, "Jupiter": {"Mercury", "Venus"},
            "Venus": {"Sun", "Moon"}, "Saturn": {"Sun", "Moon", "Mars"}}

_NAISARGIKA = {"Sun": 60.0, "Moon": 51.43, "Venus": 42.85, "Jupiter": 34.28,
               "Mercury": 25.70, "Mars": 17.14, "Saturn": 8.57}
_REQUIRED = {"Sun": 390, "Moon": 360, "Mars": 300, "Mercury": 420,
             "Jupiter": 390, "Venus": 330, "Saturn": 300}
# Powerless point reference for dig bala (planet is strongest 180° away):
# Jupiter/Mercury -> lagna (strong in 1st), Sun/Mars -> MC (10th),
# Saturn -> descendant (7th), Moon/Venus -> IC (4th).
_DIG_WEAK_POINT = {"Jupiter": "dsc", "Mercury": "dsc", "Sun": "ic", "Mars": "ic",
                   "Saturn": "asc", "Moon": "mc", "Venus": "mc"}
_TYPICAL_SPEED = {"Mars": 0.55, "Mercury": 1.40, "Jupiter": 0.13,
                  "Venus": 1.20, "Saturn": 0.07}
_SAPTA_VARGAS = ["D1", "D2", "D3", "D7", "D9", "D12", "D30"]


def _sign(lon):
    return int((lon % 360) // 30) % 12


def _uchcha(planet, lon):
    dist = abs((lon - (_EXALT_DEG[planet] + 180)) % 360)
    if dist > 180:
        dist = 360 - dist
    return dist / 3.0


def _relation(planet, lord, sign_idx, planet_sign):
    """Compound (natural + temporal) relation, per varga sign lord."""
    if lord == planet:
        return "own"
    natural = ("friend" if lord in _FRIENDS[planet] else
               "enemy" if lord in _ENEMIES[planet] else "neutral")
    # Temporal friendship: planets in 2,3,4,10,11,12 from the planet are
    # temporal friends (uses rasi-chart signs).
    diff = (sign_idx - planet_sign) % 12
    temporal = "friend" if diff in (1, 2, 3, 9, 10, 11) else "enemy"
    table = {("friend", "friend"): 22.5, ("friend", "enemy"): 7.5,
             ("neutral", "friend"): 15.0, ("neutral", "enemy"): 3.75,
             ("enemy", "friend"): 7.5, ("enemy", "enemy"): 1.875}
    return table[(natural, temporal)]


def _saptavargaja(planet, lon, rasi_sign_of, jd_lons):
    total = 0.0
    for v in _SAPTA_VARGAS:
        vsign = vargas.varga_sign(lon, v)
        lord = SIGN_LORDS[vsign]
        mt = _MOOLATRIKONA[planet]
        if v == "D1" and vsign == mt[0] and mt[1] <= (lon % 30) <= mt[2]:
            total += 45.0
            continue
        rel = _relation(planet, lord, vsign, rasi_sign_of[planet])
        total += 30.0 if rel == "own" else rel
    return total


def _ojayugma(planet, lon):
    score = 0.0
    for l in (lon, ):  # rasi
        even = _sign(l) % 2 == 1
        if planet in ("Moon", "Venus"):
            score += 15.0 if even else 0.0
        else:
            score += 0.0 if even else 15.0
    d9 = vargas.varga_sign(lon, "D9")
    even9 = d9 % 2 == 1
    if planet in ("Moon", "Venus"):
        score += 15.0 if even9 else 0.0
    else:
        score += 0.0 if even9 else 15.0
    return score


def _kendradi(lon, asc):
    house = (_sign(lon) - _sign(asc)) % 12 + 1
    if house in (1, 4, 7, 10):
        return 60.0
    if house in (2, 5, 8, 11):
        return 30.0
    return 15.0


def _drekkana(planet, lon):
    part = int((lon % 30) // 10)  # 0,1,2
    male = planet in ("Sun", "Mars", "Jupiter")
    female = planet in ("Moon", "Venus")
    if male and part == 0:
        return 15.0
    if female and part == 1:
        return 15.0
    if not male and not female and part == 2:  # Mercury, Saturn
        return 15.0
    return 0.0


def _declination(lon_sidereal, ayanamsa_value):
    lam = math.radians((lon_sidereal + ayanamsa_value) % 360)
    eps = math.radians(23.44)
    return math.degrees(math.asin(math.sin(eps) * math.sin(lam)))


def _sputa_drishti(aspecting: str, sep: float) -> float:
    """Graded aspect value (virupas) of `aspecting` at separation `sep`
    (aspected - aspecting, 0..360)."""
    special = {"Mars": (90, 210), "Jupiter": (120, 240), "Saturn": (60, 270)}
    for centre in special.get(aspecting, ()):
        if abs(sep - centre) < 15:
            return 60.0 - abs(sep - centre) * 2  # full special aspect, tapered
    d = sep
    if d <= 30:
        return 0.0
    if d <= 60:
        return (d - 30) / 2
    if d <= 90:
        return (d - 60) + 15
    if d <= 120:
        return 45 - (d - 90) / 2
    if d <= 150:
        return 150 - d
    if d <= 180:
        return (d - 150) * 2
    if d <= 300:
        return (300 - d) / 2
    return 0.0


def compute(birth_jd: float, latitude: float, longitude: float,
            local_dt: datetime, utc_dt: datetime,
            ayanamsa: str = "lahiri") -> Dict:
    positions = ephemeris.planet_positions(birth_jd, ayanamsa)
    lons = {p: positions[p]["longitude"] for p in _SEVEN}
    speeds = {p: positions[p]["speed"] for p in _SEVEN}
    asc = ephemeris.ascendant(birth_jd, latitude, longitude, ayanamsa)
    _cusps, ascmc = ephemeris.houses(birth_jd, latitude, longitude, b"P", ayanamsa)
    angles = {"asc": asc, "mc": ascmc[1] % 360,
              "dsc": (asc + 180) % 360, "ic": (ascmc[1] + 180) % 360}
    ayan_val = ephemeris.get_ayanamsa_value(birth_jd, ayanamsa)
    rasi_sign_of = {p: _sign(l) for p, l in lons.items()}

    elong = (lons["Moon"] - lons["Sun"]) % 360
    if elong > 180:
        elong = 360 - elong
    paksha_benefic = elong / 3.0  # 0..60

    # --- kala pieces shared setup ---
    midnight_dist = abs(local_dt.hour * 60 + local_dt.minute - 0)  # minutes from local midnight
    midnight_dist = min(midnight_dist, 1440 - midnight_dist) / 60.0  # hours 0..12
    day_strength = midnight_dist / 12.0 * 60.0  # 60 at noon
    night_strength = 60.0 - day_strength

    jd0 = ephemeris.julian_day(datetime(local_dt.year, local_dt.month, local_dt.day,
                                        tzinfo=timezone.utc) - timedelta(hours=longitude / 15.0))
    sunrise = muhurta._rise_set(jd0, swe.SUN, latitude, longitude, rise=True)
    sunset = muhurta._rise_set(jd0, swe.SUN, latitude, longitude, rise=False)
    is_day = bool(sunrise and sunset and sunrise <= utc_dt < sunset)

    # tribhaga part (0,1,2) of day or night
    tribhaga_lord = "Jupiter"
    if sunrise and sunset:
        if is_day:
            frac = (utc_dt - sunrise) / (sunset - sunrise)
            tribhaga_lord = ["Mercury", "Sun", "Saturn"][min(int(frac * 3), 2)]
        else:
            next_rise = muhurta._rise_set(jd0 + 1, swe.SUN, latitude, longitude, rise=True)
            if utc_dt >= sunset and next_rise:
                frac = (utc_dt - sunset) / (next_rise - sunset)
                tribhaga_lord = ["Moon", "Venus", "Mars"][min(int(frac * 3), 2)]
            else:  # before sunrise: last third-ish of night
                tribhaga_lord = "Mars"

    # varsha/masa/vara/hora lords via ahargana from the Kali epoch (a Friday)
    KALI_JD = 588465.5
    ahargana = int(birth_jd - KALI_JD)
    wd_lords = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn"]
    # epoch weekday Friday = index 5 in Sun..Sat
    varsha_lord = wd_lords[(5 + ahargana - ahargana % 360) % 7]
    masa_lord = wd_lords[(5 + ahargana - ahargana % 30) % 7]
    vara_lord = wd_lords[(5 + ahargana) % 7]
    hora_lord = vara_lord
    if sunrise:
        hours_since_rise = max((utc_dt - sunrise).total_seconds() / 3600.0, 0)
        hora_seq_start = wd_lords.index(vara_lord)
        hora_order = ["Sun", "Venus", "Mercury", "Moon", "Saturn", "Jupiter", "Mars"]
        start_in_order = hora_order.index(wd_lords[hora_seq_start])
        hora_lord = hora_order[(start_in_order + int(hours_since_rise)) % 7]

    weekday_name = WEEKDAYS[local_dt.weekday()]

    out = {}
    for p in _SEVEN:
        lon = lons[p]
        sthana = {
            "uchcha": round(_uchcha(p, lon), 2),
            "saptavargaja": round(_saptavargaja(p, lon, rasi_sign_of, lons), 2),
            "ojayugma": round(_ojayugma(p, lon), 2),
            "kendradi": round(_kendradi(lon, asc), 2),
            "drekkana": round(_drekkana(p, lon), 2),
        }
        weak = angles[_DIG_WEAK_POINT[p]]
        dist = abs((lon - weak) % 360)
        if dist > 180:
            dist = 360 - dist
        dig = dist / 3.0

        # kala
        natonnata = (60.0 if p == "Mercury" else
                     day_strength if p in ("Sun", "Jupiter", "Venus") else
                     night_strength)
        paksha = (paksha_benefic if p in ("Moon", "Mercury", "Jupiter", "Venus")
                  else 60.0 - paksha_benefic)
        if p == "Moon":
            paksha *= 2
        tribhaga = 60.0 if p == tribhaga_lord else 0.0
        abda = 15.0 if p == varsha_lord else 0.0
        masa = 30.0 if p == masa_lord else 0.0
        vara = 45.0 if p == vara_lord else 0.0
        hora = 60.0 if p == hora_lord else 0.0
        decl = _declination(lon, ayan_val)
        signed = (abs(decl) if p == "Mercury" else
                  decl if p in ("Sun", "Mars", "Jupiter", "Venus") else -decl)
        ayana = max(0.0, (23.45 + signed) / 46.9 * 60.0)
        if p == "Sun":
            ayana *= 2
        kala = {"natonnata": round(natonnata, 2), "paksha": round(paksha, 2),
                "tribhaga": tribhaga, "abda": abda, "masa": masa,
                "vara": vara, "hora": hora, "ayana": round(ayana, 2)}

        # chesta
        if p == "Sun":
            chesta = ayana / (2 if p == "Sun" else 1)  # Sun: ayana bala (single)
            chesta = ayana / 2
        elif p == "Moon":
            chesta = paksha / 2 if paksha > 60 else paksha  # paksha bala (un-doubled cap)
            chesta = min(paksha, 60.0)
        else:
            sp, typ = speeds[p], _TYPICAL_SPEED[p]
            if sp < 0:
                chesta = 60.0          # vakra (retrograde)
            elif abs(sp) < 0.1 * typ:
                chesta = 15.0          # vikala (near-stationary)
            elif sp < typ:
                chesta = 30.0          # manda (slow)
            elif sp <= 1.5 * typ:
                chesta = 45.0          # sama/chara (normal)
            else:
                chesta = 30.0          # atichara (very fast)

        # drik
        drik = 0.0
        for other in _SEVEN:
            if other == p:
                continue
            sep = (lon - lons[other]) % 360  # separation from aspecting -> aspected
            val = _sputa_drishti(other, sep) / 4.0
            benefic = (other in ("Jupiter", "Venus", "Mercury") or
                       (other == "Moon" and paksha_benefic >= 30))
            drik += val if benefic else -val

        total = (sum(sthana.values()) + dig + sum(kala.values())
                 + chesta + _NAISARGIKA[p] + drik)
        out[p] = {
            "sthana": sthana, "sthana_total": round(sum(sthana.values()), 2),
            "dig": round(dig, 2), "kala": kala,
            "kala_total": round(sum(kala.values()), 2),
            "chesta": round(chesta, 2), "naisargika": _NAISARGIKA[p],
            "drik": round(drik, 2),
            "total_virupas": round(total, 2),
            "rupas": round(total / 60.0, 2),
            "required_virupas": _REQUIRED[p],
            "ratio": round(total / _REQUIRED[p], 2),
            "strong": total >= _REQUIRED[p],
        }

    ranked = sorted(out, key=lambda q: out[q]["total_virupas"], reverse=True)
    return {
        "system": ("Shadbala (BPHS). Conventions: compound saptavargaja "
                   "friendship; chesta by motion class for the five tara "
                   "grahas (Sun=ayana, Moon=paksha); graded sputa-drishti "
                   "drik bala; hora by unequal hours from sunrise."),
        "weekday": weekday_name,
        "planets": out,
        "ranking": ranked,
    }
