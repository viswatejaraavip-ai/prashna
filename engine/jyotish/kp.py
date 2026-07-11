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
