"""Hindu festival calendar for a year (amanta lunar months, sidereal).

Lunar months are named from the Sun's sidereal sign at each new moon
(amavasya): Sun in Pisces -> Chaitra, Aries -> Vaishakha, and so on.
Festival dates use the tithi prevailing at local sunrise (midnight rule for
Janmashtami and Shivaratri) — the common Indian civil convention.
Sankrantis (solar ingresses) are exact Swiss Ephemeris events.
"""

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from . import ephemeris

_MONTHS = ["Chaitra", "Vaishakha", "Jyeshtha", "Ashadha", "Shravana",
           "Bhadrapada", "Ashwina", "Kartika", "Margashirsha", "Pausha",
           "Magha", "Phalguna"]

# (name, lunar month, paksha, tithi(1-15), rule)
_FESTIVALS = [
    ("Ugadi / Gudi Padwa", "Chaitra", "Shukla", 1, "sunrise"),
    ("Rama Navami", "Chaitra", "Shukla", 9, "sunrise"),
    ("Hanuman Jayanti", "Chaitra", "Shukla", 15, "sunrise"),
    ("Akshaya Tritiya", "Vaishakha", "Shukla", 3, "sunrise"),
    ("Buddha Purnima", "Vaishakha", "Shukla", 15, "sunrise"),
    ("Ratha Yatra", "Ashadha", "Shukla", 2, "sunrise"),
    ("Guru Purnima", "Ashadha", "Shukla", 15, "sunrise"),
    ("Naga Panchami", "Shravana", "Shukla", 5, "sunrise"),
    ("Raksha Bandhan", "Shravana", "Shukla", 15, "sunrise"),
    # Krishna-paksha festivals are commonly quoted in purnimanta months;
    # in this amanta calendar they fall one month earlier.
    ("Krishna Janmashtami", "Shravana", "Krishna", 8, "midnight"),
    ("Ganesh Chaturthi", "Bhadrapada", "Shukla", 4, "midday"),
    ("Sharad Navaratri begins", "Ashwina", "Shukla", 1, "sunrise"),
    ("Durga Ashtami", "Ashwina", "Shukla", 8, "sunrise"),
    ("Vijaya Dashami (Dussehra)", "Ashwina", "Shukla", 10, "afternoon"),
    ("Karwa Chauth", "Ashwina", "Krishna", 4, "sunrise"),
    ("Dhanteras", "Ashwina", "Krishna", 13, "evening"),
    ("Diwali (Lakshmi Puja)", "Ashwina", "Krishna", 15, "evening"),
    ("Kartika Purnima / Dev Deepavali", "Kartika", "Shukla", 15, "sunrise"),
    ("Vaikuntha Ekadashi (approx.)", "Margashirsha", "Shukla", 11, "sunrise"),
    ("Vasant Panchami", "Magha", "Shukla", 5, "sunrise"),
    ("Maha Shivaratri", "Magha", "Krishna", 14, "midnight"),
    ("Holika Dahan", "Phalguna", "Shukla", 15, "sunrise"),
    ("Holi (Dhulandi)", "Phalguna", "Krishna", 1, "sunrise"),
]

_SANKRANTI_NAMES = {9: "Makara Sankranti (Pongal)", 0: "Mesha Sankranti (solar new year)"}


def _sun_moon(dt: datetime):
    jd = ephemeris.julian_day(dt)
    pos = ephemeris.planet_positions(jd, "lahiri")
    return pos["Sun"]["longitude"], pos["Moon"]["longitude"]


def _phase(dt: datetime) -> float:
    s, m = _sun_moon(dt)
    return (m - s) % 360


def _tithi_at(dt: datetime) -> int:
    """Tithi number 1..30 at `dt` (1-15 shukla, 16-30 krishna)."""
    return int(_phase(dt) // 12) + 1


def _new_moons(year: int) -> List[datetime]:
    """All amavasya end moments (phase 360->0) covering the year."""
    out = []
    t = datetime(year - 1, 11, 25, tzinfo=timezone.utc)
    end = datetime(year + 1, 1, 15, tzinfo=timezone.utc)
    prev = _phase(t)
    while t < end:
        t2 = t + timedelta(days=1)
        cur = _phase(t2)
        if cur < prev:  # wrapped 360 -> 0
            lo, hi = t, t2
            for _ in range(40):
                mid = lo + (hi - lo) / 2
                if _phase(mid) > 180:
                    lo = mid
                else:
                    hi = mid
            out.append(hi)
        prev, t = cur, t2
    return out


def calendar(year: int, latitude: float = 28.6139, longitude: float = 77.2090,
             tz_name: str = "Asia/Kolkata") -> Dict:
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = timezone.utc

    moons = _new_moons(year)
    # month of the lunar cycle beginning at each new moon
    cycles = []
    for i, nm in enumerate(moons):
        sun_sign = int((_sun_moon(nm)[0] % 360) // 30)
        cycle_end = moons[i + 1] if i + 1 < len(moons) else nm + timedelta(days=30)
        cycles.append({"start": nm, "end": cycle_end,
                       "month": _MONTHS[(sun_sign + 1) % 12]})

    def _observance_date(month: str, paksha: str, tithi: int,
                         rule: str) -> Optional[str]:
        for c in cycles:
            if c["month"] != month:
                continue
            # target phase angle at which the tithi runs
            offset = (tithi - 1) * 12 + (180 if paksha == "Krishna" else 0)
            if paksha == "Krishna" and tithi == 15:
                offset = 348  # amavasya
            # scan up to 31 days from cycle start for the local date where
            # the tithi prevails at the rule's probe time: sunrise (06:00),
            # evening/pradosh (18:30), or the night of the day (23:30 —
            # Shivaratri and Janmashtami honour the tithi at night).
            probe_h, probe_m = {"sunrise": (6, 0), "midday": (12, 30),
                                "afternoon": (15, 30), "evening": (18, 30),
                                "midnight": (23, 30)}[rule]
            for d in range(31):
                day = (c["start"] + timedelta(days=d)).astimezone(tz).date()
                probe_local = datetime(day.year, day.month, day.day,
                                       probe_h, probe_m, tzinfo=tz)
                probe_utc = probe_local.astimezone(timezone.utc)
                if probe_utc < c["start"]:
                    continue  # before this month's amavasya ended
                if probe_utc >= c["end"]:
                    break  # ran into the next lunar month
                ph = _phase(probe_utc)
                if offset <= ph < offset + 12:
                    if day.year == year:
                        return day.isoformat()
                    break
            else:
                continue
            # No probe hit inside this cycle (short tithi): fall through to
            # the tithi-begin fallback below rather than a wrong-year match.
            break
        # Tithi never touched the probe time (spans between two probes):
        # fall back to the local date on which the tithi begins. Elongation
        # climbs 0 -> 360 monotonically across a lunar cycle, so a plain
        # threshold bisect inside (start, end) finds the tithi's start.
        for c in cycles:
            if c["month"] != month:
                continue
            offset = (tithi - 1) * 12 + (180 if paksha == "Krishna" else 0)
            if paksha == "Krishna" and tithi == 15:
                offset = 348
            if offset == 0:
                day = c["start"].astimezone(tz).date()
            else:
                lo, hi = c["start"], c["end"]
                for _ in range(40):
                    mid = lo + (hi - lo) / 2
                    if _phase(mid) < offset:
                        lo = mid
                    else:
                        hi = mid
                day = hi.astimezone(tz).date()
            if day.year == year:
                return day.isoformat()
        return None

    festivals = []
    for name, month, paksha, tithi, rule in _FESTIVALS:
        date = _observance_date(month, paksha, tithi, rule)
        if date:
            festivals.append({"festival": name, "date": date,
                              "lunar_month": month, "paksha": paksha,
                              "tithi": tithi})
    festivals.sort(key=lambda f: f["date"])

    # Sankrantis: exact solar sidereal ingresses
    sankrantis = []
    t = datetime(year, 1, 1, tzinfo=timezone.utc)
    end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    prev_sign = int((_sun_moon(t)[0] % 360) // 30)
    while t < end:
        t2 = t + timedelta(days=5)
        sign = int((_sun_moon(min(t2, end))[0] % 360) // 30)
        if sign != prev_sign:
            lo, hi = t, min(t2, end)
            for _ in range(40):
                mid = lo + (hi - lo) / 2
                if int((_sun_moon(mid)[0] % 360) // 30) == prev_sign:
                    lo = mid
                else:
                    hi = mid
            from .constants import SIGNS
            local_day = hi.astimezone(tz)
            sankrantis.append({
                "sankranti": _SANKRANTI_NAMES.get(sign, SIGNS[sign] + " Sankranti"),
                "sun_enters": SIGNS[sign],
                "date": local_day.date().isoformat(),
                "time_local": local_day.strftime("%H:%M"),
            })
            prev_sign = sign
        t = t2
    return {
        "system": ("Amanta lunar months, sidereal (Lahiri); tithi at local "
                   "sunrise (midnight rule for Shivaratri/Janmashtami)"),
        "year": year, "tz_name": tz_name,
        "festivals": festivals,
        "sankrantis": sankrantis,
        "note": "Regional observance can differ by a day where a tithi "
                "spans two sunrises; purnimanta traditions shift Krishna-"
                "paksha month names.",
    }
