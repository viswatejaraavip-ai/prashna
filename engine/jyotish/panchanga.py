"""Panchanga: tithi, vara, nakshatra, yoga, karana."""

from datetime import datetime
from typing import Dict

from .constants import (
    KARANA_FIXED_END, KARANA_FIXED_START, KARANA_MOVABLE,
    NAKSHATRAS, NAKSHATRA_SPAN, TITHIS, WEEKDAYS, YOGAS,
)


def nakshatra_of(longitude: float) -> Dict:
    idx = int((longitude % 360.0) / NAKSHATRA_SPAN) % 27
    within = (longitude % 360.0) - idx * NAKSHATRA_SPAN
    pada = int(within / (NAKSHATRA_SPAN / 4)) + 1
    return {"name": NAKSHATRAS[idx], "index": idx + 1, "pada": min(pada, 4)}


def _karana_name(k: int) -> str:
    # k is the 0-indexed half-tithi (0..59)
    if k == 0:
        return KARANA_FIXED_START
    if k < 57:
        return KARANA_MOVABLE[(k - 1) % 7]
    return KARANA_FIXED_END[k - 57]


def panchanga(sun_longitude: float, moon_longitude: float, local_dt: datetime) -> Dict:
    elongation = (moon_longitude - sun_longitude) % 360.0

    tithi_num = int(elongation / 12.0) + 1  # 1..30
    paksha = "Shukla" if tithi_num <= 15 else "Krishna"
    tithi_in_paksha = tithi_num if tithi_num <= 15 else tithi_num - 15
    if tithi_in_paksha == 15:
        tithi_name = "Purnima" if paksha == "Shukla" else "Amavasya"
    else:
        tithi_name = TITHIS[tithi_in_paksha - 1]

    yoga_val = (sun_longitude + moon_longitude) % 360.0
    yoga_idx = int(yoga_val / NAKSHATRA_SPAN) % 27

    karana_idx = int(elongation / 6.0) % 60

    return {
        "tithi": {
            "number": tithi_num,
            "name": tithi_name,
            "paksha": paksha,
            "completion_pct": round((elongation % 12.0) / 12.0 * 100, 1),
        },
        "vara": WEEKDAYS[local_dt.weekday()],
        "nakshatra": nakshatra_of(moon_longitude),
        "yoga": {"name": YOGAS[yoga_idx], "index": yoga_idx + 1},
        "karana": {"name": _karana_name(karana_idx), "index": karana_idx + 1},
    }
