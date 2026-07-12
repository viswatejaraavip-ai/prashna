"""Dosha analysis: Manglik, Kaal Sarpa, Sadhe Sati (with life-long periods)."""

from datetime import datetime, timedelta, timezone
from typing import Dict, List

from . import ephemeris
from .constants import SIGNS

_KENDRA_HOUSES = {1, 2, 4, 7, 8, 12}

_KAAL_SARPA_TYPES = ["Anant", "Kulik", "Vasuki", "Shankhpal", "Padma",
                     "Mahapadma", "Takshak", "Karkotak", "Shankhachud",
                     "Ghatak", "Vishdhar", "Sheshnag"]

_MARS_OWN_EXALT = {0, 7, 9}  # Aries, Scorpio own; Capricorn exaltation


def _house_from(lon: float, ref: float) -> int:
    """Whole-sign house of `lon` counted from the sign of `ref` (1..12)."""
    return (int((lon % 360) // 30) - int((ref % 360) // 30)) % 12 + 1


def manglik(positions: Dict[str, float], ascendant: float) -> Dict:
    """Manglik (Kuja) dosha: Mars in 1,2,4,7,8,12 from Lagna, Moon or Venus."""
    mars = positions["Mars"]
    checks = {
        "from_lagna": _house_from(mars, ascendant),
        "from_moon": _house_from(mars, positions["Moon"]),
        "from_venus": _house_from(mars, positions["Venus"]),
    }
    afflicted = {k: h for k, h in checks.items() if h in _KENDRA_HOUSES}
    mars_sign = int((mars % 360) // 30)
    cancellations = []
    if mars_sign in _MARS_OWN_EXALT and afflicted:
        cancellations.append("Mars is in %s (own/exaltation) — dosha considered "
                             "substantially reduced" % SIGNS[mars_sign])
    severity = ("high" if len(afflicted) == 3 else
                "medium" if len(afflicted) == 2 else
                "low" if afflicted else "none")
    return {
        "dosha": "Manglik (Kuja/Mangal)",
        "is_manglik": bool(afflicted),
        "severity": severity,
        "mars_sign": SIGNS[mars_sign],
        "houses": checks,
        "afflicted_references": list(afflicted),
        "cancellations": cancellations,
        "note": "Counted whole-sign from Lagna, Moon and Venus; houses "
                "1,2,4,7,8,12 afflict.",
    }


def kaal_sarpa(positions: Dict[str, float], ascendant: float) -> Dict:
    """Kaal Sarpa dosha: the seven classical planets hemmed on one side of
    the Rahu–Ketu axis. Named by Rahu's whole-sign house from Lagna."""
    rahu, ketu = positions["Rahu"] % 360, positions["Ketu"] % 360
    seven = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn"]

    def _within(lon, start, end):
        return (lon - start) % 360 < (end - start) % 360

    side_rahu_ketu = [p for p in seven if _within(positions[p] % 360, rahu, ketu)]
    side_ketu_rahu = [p for p in seven if not _within(positions[p] % 360, rahu, ketu)]
    outside = min(side_rahu_ketu, side_ketu_rahu, key=len)
    present = len(outside) == 0
    partial = len(outside) == 1
    house = _house_from(rahu, ascendant)
    return {
        "dosha": "Kaal Sarpa",
        "present": present,
        "partial": partial,
        "type": (_KAAL_SARPA_TYPES[house - 1] + " Kaal Sarpa"
                 if (present or partial) else None),
        "rahu_house_from_lagna": house,
        "planets_outside_axis": outside,
        "note": "All seven classical planets on one side of the Rahu–Ketu "
                "axis; 'partial' when exactly one planet breaks the hem.",
    }


def _saturn_sign(dt: datetime, ayanamsa: str) -> int:
    jd = ephemeris.julian_day(dt)
    lon = ephemeris.planet_positions(jd, ayanamsa)["Saturn"]["longitude"]
    return int((lon % 360) // 30)


def _saturn_ingresses(start: datetime, years: int, ayanamsa: str) -> List[Dict]:
    """Saturn sign-change dates from `start` over `years`, via scan + bisection."""
    out = []
    step = timedelta(days=20)
    t = start
    end = start + timedelta(days=int(years * 365.25))
    sign = _saturn_sign(t, ayanamsa)
    while t < end:
        t2 = min(t + step, end)
        s2 = _saturn_sign(t2, ayanamsa)
        if s2 != sign:
            lo, hi = t, t2
            for _ in range(40):
                mid = lo + (hi - lo) / 2
                if _saturn_sign(mid, ayanamsa) == sign:
                    lo = mid
                else:
                    hi = mid
            out.append({"date": hi, "sign": s2})
            sign = s2
        t = t2
    return out


def sadhe_sati(positions: Dict[str, float], birth_utc: datetime,
               ayanamsa: str = "lahiri", years: int = 90) -> Dict:
    """Sadhe Sati windows across life: Saturn transiting the 12th, 1st and
    2nd signs from the natal Moon (plus Dhaiya: 4th and 8th)."""
    moon_sign = int((positions["Moon"] % 360) // 30)
    targets = {(moon_sign - 1) % 12: "first phase (12th from Moon)",
               moon_sign: "peak phase (over natal Moon)",
               (moon_sign + 1) % 12: "final phase (2nd from Moon)"}
    dhaiya = {(moon_sign + 3) % 12: "Ardha-shani / Dhaiya (4th from Moon)",
              (moon_sign + 7) % 12: "Ashtama Shani / Dhaiya (8th from Moon)"}

    if birth_utc.tzinfo is None:
        birth_utc = birth_utc.replace(tzinfo=timezone.utc)
    ingresses = _saturn_ingresses(birth_utc, years, ayanamsa)

    # Build sign occupancy periods from birth
    periods = []
    cur_sign = _saturn_sign(birth_utc, ayanamsa)
    cur_start = birth_utc
    for ing in ingresses:
        periods.append((cur_sign, cur_start, ing["date"]))
        cur_sign, cur_start = ing["sign"], ing["date"]
    periods.append((cur_sign, cur_start, birth_utc + timedelta(days=int(years * 365.25))))

    def _fmt(dt):
        return dt.date().isoformat()

    windows: List[Dict] = []
    for sign, start, end in periods:
        if sign in targets:
            windows.append({"kind": "sadhe_sati", "phase": targets[sign],
                            "saturn_sign": SIGNS[sign],
                            "start": _fmt(start), "end": _fmt(end)})
        elif sign in dhaiya:
            windows.append({"kind": "dhaiya", "phase": dhaiya[sign],
                            "saturn_sign": SIGNS[sign],
                            "start": _fmt(start), "end": _fmt(end)})

    now = datetime.now(timezone.utc)
    current = next((w for w in windows
                    if w["start"] <= now.date().isoformat() <= w["end"]), None)
    return {
        "dosha": "Sadhe Sati",
        "natal_moon_sign": SIGNS[moon_sign],
        "currently_active": current,
        "windows": windows,
        "note": "Sign-level Saturn transit over 12th/1st/2nd from natal Moon; "
                "Dhaiya = 4th/8th. Dates are sidereal ingress dates (UTC).",
    }


def analyze(positions: Dict[str, float], ascendant: float,
            birth_utc: datetime, ayanamsa: str = "lahiri") -> Dict:
    return {
        "manglik": manglik(positions, ascendant),
        "kaal_sarpa": kaal_sarpa(positions, ascendant),
        "sadhe_sati": sadhe_sati(positions, birth_utc, ayanamsa),
    }
