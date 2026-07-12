"""Daily muhurta timings: sunrise/sunset, Rahu Kalam, Yamaganda, Gulika,
Abhijit and Brahma muhurta for a given date and place."""

from datetime import date, datetime, timedelta, timezone
from typing import Dict, Optional

import swisseph as swe

from . import ephemeris

# Octant (1..8) of the daytime occupied per weekday, Monday=0 .. Sunday=6
_RAHU_OCTANT = {6: 8, 0: 2, 1: 7, 2: 5, 3: 6, 4: 4, 5: 3}
_YAMAGANDA_OCTANT = {6: 5, 0: 4, 1: 3, 2: 2, 3: 1, 4: 7, 5: 6}
_GULIKA_OCTANT = {6: 7, 0: 6, 1: 5, 2: 4, 3: 3, 4: 2, 5: 1}


def _rise_set(jd_midnight_ut: float, body: int, latitude: float,
              longitude: float, rise: bool) -> Optional[datetime]:
    flag = swe.CALC_RISE if rise else swe.CALC_SET
    try:
        res, tret = swe.rise_trans(jd_midnight_ut, body, flag,
                                   (longitude, latitude, 0.0))
    except Exception:
        return None
    if res != 0:
        return None  # circumpolar etc.
    y, mo, d, h = swe.revjul(tret[0])
    hh = int(h); mm = int((h - hh) * 60); ss = int(round(((h - hh) * 60 - mm) * 60))
    if ss == 60:
        ss, mm = 0, mm + 1
    return datetime(y, mo, d, hh, mm, ss, tzinfo=timezone.utc)


def day_timings(day: date, latitude: float, longitude: float,
                tz_name: str = "Asia/Kolkata") -> Dict:
    """All classical day timings for `day` (local calendar date at place)."""
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = timezone.utc

    # Search from local midnight so the found events belong to this local day.
    local_midnight = datetime(day.year, day.month, day.day, tzinfo=tz)
    jd0 = ephemeris.julian_day(local_midnight.astimezone(timezone.utc))

    sunrise = _rise_set(jd0, swe.SUN, latitude, longitude, rise=True)
    sunset = _rise_set(jd0, swe.SUN, latitude, longitude, rise=False)
    moonrise = _rise_set(jd0, swe.MOON, latitude, longitude, rise=True)
    moonset = _rise_set(jd0, swe.MOON, latitude, longitude, rise=False)
    if sunrise is None or sunset is None:
        raise ValueError("Sun does not rise/set at this latitude on this date")
    if sunset < sunrise:  # set event found past local midnight boundary
        sunset = _rise_set(jd0 + 0.5, swe.SUN, latitude, longitude, rise=False)

    day_len = sunset - sunrise
    octant = day_len / 8
    muhurta_len = day_len / 15  # 15 daytime muhurtas

    def _local(dt: Optional[datetime]) -> Optional[str]:
        return dt.astimezone(tz).strftime("%H:%M") if dt else None

    def _octant_window(idx: int) -> Dict:
        start = sunrise + octant * (idx - 1)
        return {"start": _local(start), "end": _local(start + octant)}

    weekday = local_midnight.weekday()  # Monday=0
    abhijit_start = sunrise + muhurta_len * 7  # 8th of 15 muhurtas
    brahma_start = sunrise - timedelta(minutes=96)

    return {
        "date": day.isoformat(),
        "weekday": local_midnight.strftime("%A"),
        "tz_name": tz_name,
        "sunrise": _local(sunrise), "sunset": _local(sunset),
        "moonrise": _local(moonrise), "moonset": _local(moonset),
        "day_duration_hours": round(day_len.total_seconds() / 3600, 2),
        "inauspicious": {
            "rahu_kalam": _octant_window(_RAHU_OCTANT[weekday]),
            "yamaganda": _octant_window(_YAMAGANDA_OCTANT[weekday]),
            "gulika_kalam": _octant_window(_GULIKA_OCTANT[weekday]),
        },
        "auspicious": {
            "brahma_muhurta": {"start": _local(brahma_start),
                               "end": _local(brahma_start + timedelta(minutes=48))},
            "abhijit_muhurta": (None if weekday == 2 else  # avoided on Wednesday
                                {"start": _local(abhijit_start),
                                 "end": _local(abhijit_start + muhurta_len)}),
        },
        "note": "Rahu/Yamaganda/Gulika are day-length octants from sunrise; "
                "Abhijit is the 8th of 15 daytime muhurtas (omitted on "
                "Wednesdays per tradition).",
    }
