"""Vimshottari dasha calculations (maha -> antar -> pratyantar)."""

from datetime import datetime, timedelta
from typing import Dict, List, Optional

from .constants import DASHA_SEQUENCE, DASHA_TOTAL_YEARS, NAKSHATRA_SPAN, YEAR_DAYS


def _lord_index_and_balance(moon_longitude: float):
    """Which dasha lord rules at birth and what fraction of it remains."""
    nak_index = int(moon_longitude / NAKSHATRA_SPAN) % 27
    traversed = (moon_longitude % NAKSHATRA_SPAN) / NAKSHATRA_SPAN
    lord_index = nak_index % 9
    balance_fraction = 1.0 - traversed
    return lord_index, balance_fraction


def _sub_periods(lord_index: int, start: datetime, duration_days: float, depth: int,
                 max_depth: int) -> List[Dict]:
    """Split a period into 9 sub-periods starting from its own lord."""
    if depth >= max_depth:
        return []
    out = []
    cursor = start
    for i in range(9):
        sub_lord, sub_years = DASHA_SEQUENCE[(lord_index + i) % 9]
        sub_days = duration_days * sub_years / DASHA_TOTAL_YEARS
        period = {
            "lord": sub_lord,
            "start": cursor.isoformat(),
            "end": (cursor + timedelta(days=sub_days)).isoformat(),
        }
        subs = _sub_periods((lord_index + i) % 9, cursor, sub_days, depth + 1, max_depth)
        if subs:
            period["sub_periods"] = subs
        out.append(period)
        cursor = cursor + timedelta(days=sub_days)
    return out


def vimshottari(moon_longitude: float, birth_utc: datetime, levels: int = 2) -> Dict:
    """Full Vimshottari tree from birth.

    levels: 1 = mahadashas only, 2 = + antardashas, 3 = + pratyantardashas.
    """
    lord_index, balance = _lord_index_and_balance(moon_longitude)
    first_lord, first_years = DASHA_SEQUENCE[lord_index]
    elapsed_days = first_years * YEAR_DAYS * (1.0 - balance)
    # The first mahadasha notionally started before birth.
    first_start = birth_utc - timedelta(days=elapsed_days)

    mahadashas = []
    cursor = first_start
    for i in range(9):
        lord, years = DASHA_SEQUENCE[(lord_index + i) % 9]
        days = years * YEAR_DAYS
        period = {
            "lord": lord,
            "start": cursor.isoformat(),
            "end": (cursor + timedelta(days=days)).isoformat(),
            "years": years,
        }
        subs = _sub_periods((lord_index + i) % 9, cursor, days, 1, levels)
        if subs:
            period["antardashas"] = subs
        mahadashas.append(period)
        cursor = cursor + timedelta(days=days)

    return {
        "system": "Vimshottari",
        "birth_lord": first_lord,
        "balance_years_at_birth": round(first_years * balance, 4),
        "mahadashas": mahadashas,
    }


def current_dasha(moon_longitude: float, birth_utc: datetime,
                  at: Optional[datetime] = None) -> Dict:
    """Maha/antar/pratyantar lords running at a given moment."""
    at = at or datetime.utcnow().replace(tzinfo=birth_utc.tzinfo)
    tree = vimshottari(moon_longitude, birth_utc, levels=3)

    def find(periods, key):
        for p in periods:
            if p["start"] <= at.isoformat() <= p["end"]:
                return p
        return None

    maha = find(tree["mahadashas"], None)
    if maha is None:
        return {"error": "date outside the 120-year dasha cycle"}
    antar = find(maha.get("antardashas", []), None)
    pratyantar = find(antar.get("sub_periods", []), None) if antar else None
    return {
        "at": at.isoformat(),
        "mahadasha": {"lord": maha["lord"], "start": maha["start"], "end": maha["end"]},
        "antardasha": {"lord": antar["lord"], "start": antar["start"], "end": antar["end"]} if antar else None,
        "pratyantardasha": {"lord": pratyantar["lord"], "start": pratyantar["start"], "end": pratyantar["end"]} if pratyantar else None,
    }
