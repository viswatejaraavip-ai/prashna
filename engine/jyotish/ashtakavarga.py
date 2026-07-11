"""Ashtakavarga: Bhinnashtakavarga (BAV) and Sarvashtakavarga (SAV).

Classical Parashara benefic-place tables. For each planet's BAV, every
contributor (the 7 planets + the lagna) donates one bindu into the signs at
the listed house positions counted from the contributor's own sign.

Checksums (classical): Sun 48, Moon 49, Mars 39, Mercury 54, Jupiter 56,
Venus 52, Saturn 39 bindus; SAV total 337. Verified in tests.
"""

from typing import Dict, List

from .constants import SIGNS

# BENEFIC_PLACES[planet][contributor] = houses (1..12) counted from contributor
BENEFIC_PLACES = {
    "Sun": {
        "Sun": [1, 2, 4, 7, 8, 9, 10, 11],
        "Moon": [3, 6, 10, 11],
        "Mars": [1, 2, 4, 7, 8, 9, 10, 11],
        "Mercury": [3, 5, 6, 9, 10, 11, 12],
        "Jupiter": [5, 6, 9, 11],
        "Venus": [6, 7, 12],
        "Saturn": [1, 2, 4, 7, 8, 9, 10, 11],
        "Ascendant": [3, 4, 6, 10, 11, 12],
    },
    "Moon": {
        "Sun": [3, 6, 7, 8, 10, 11],
        "Moon": [1, 3, 6, 7, 10, 11],
        "Mars": [2, 3, 5, 6, 9, 10, 11],
        "Mercury": [1, 3, 4, 5, 7, 8, 10, 11],
        "Jupiter": [1, 4, 7, 8, 10, 11, 12],
        "Venus": [3, 4, 5, 7, 9, 10, 11],
        "Saturn": [3, 5, 6, 11],
        "Ascendant": [3, 6, 10, 11],
    },
    "Mars": {
        "Sun": [3, 5, 6, 10, 11],
        "Moon": [3, 6, 11],
        "Mars": [1, 2, 4, 7, 8, 10, 11],
        "Mercury": [3, 5, 6, 11],
        "Jupiter": [6, 10, 11, 12],
        "Venus": [6, 8, 11, 12],
        "Saturn": [1, 4, 7, 8, 9, 10, 11],
        "Ascendant": [1, 3, 6, 10, 11],
    },
    "Mercury": {
        "Sun": [5, 6, 9, 11, 12],
        "Moon": [2, 4, 6, 8, 10, 11],
        "Mars": [1, 2, 4, 7, 8, 9, 10, 11],
        "Mercury": [1, 3, 5, 6, 9, 10, 11, 12],
        "Jupiter": [6, 8, 11, 12],
        "Venus": [1, 2, 3, 4, 5, 8, 9, 11],
        "Saturn": [1, 2, 4, 7, 8, 9, 10, 11],
        "Ascendant": [1, 2, 4, 6, 8, 10, 11],
    },
    "Jupiter": {
        "Sun": [1, 2, 3, 4, 7, 8, 9, 10, 11],
        "Moon": [2, 5, 7, 9, 11],
        "Mars": [1, 2, 4, 7, 8, 10, 11],
        "Mercury": [1, 2, 4, 5, 6, 9, 10, 11],
        "Jupiter": [1, 2, 3, 4, 7, 8, 10, 11],
        "Venus": [2, 5, 6, 9, 10, 11],
        "Saturn": [3, 5, 6, 12],
        "Ascendant": [1, 2, 4, 5, 6, 7, 9, 10, 11],
    },
    "Venus": {
        "Sun": [8, 11, 12],
        "Moon": [1, 2, 3, 4, 5, 8, 9, 11, 12],
        "Mars": [3, 5, 6, 9, 11, 12],
        "Mercury": [3, 5, 6, 9, 11],
        "Jupiter": [5, 8, 9, 10, 11],
        "Venus": [1, 2, 3, 4, 5, 8, 9, 10, 11],
        "Saturn": [3, 4, 5, 8, 9, 10, 11],
        "Ascendant": [1, 2, 3, 4, 5, 8, 9, 11],
    },
    "Saturn": {
        "Sun": [1, 2, 4, 7, 8, 10, 11],
        "Moon": [3, 6, 11],
        "Mars": [3, 5, 6, 10, 11, 12],
        "Mercury": [6, 8, 9, 10, 11, 12],
        "Jupiter": [5, 6, 11, 12],
        "Venus": [6, 11, 12],
        "Saturn": [3, 5, 6, 11],
        "Ascendant": [1, 3, 4, 6, 10, 11],
    },
}

BAV_TOTALS = {"Sun": 48, "Moon": 49, "Mars": 39, "Mercury": 54,
              "Jupiter": 56, "Venus": 52, "Saturn": 39}  # sum = 337

AV_PLANETS = list(BENEFIC_PLACES.keys())


def bav(planet: str, contributor_signs: Dict[str, int]) -> List[int]:
    """Bindus per sign (index 0=Aries..11) for one planet's BAV.

    contributor_signs: sign index of Sun..Saturn and 'Ascendant'.
    """
    counts = [0] * 12
    for contributor, houses in BENEFIC_PLACES[planet].items():
        base = contributor_signs[contributor]
        for h in houses:
            counts[(base + h - 1) % 12] += 1
    return counts


def compute(contributor_signs: Dict[str, int]) -> Dict:
    """All 7 BAVs + SAV. Returns sign-name keyed dicts plus totals."""
    result = {"bav": {}, "sav": {}, "bav_totals": {}}
    sav = [0] * 12
    for planet in AV_PLANETS:
        counts = bav(planet, contributor_signs)
        result["bav"][planet] = {SIGNS[i]: counts[i] for i in range(12)}
        result["bav_totals"][planet] = sum(counts)
        for i in range(12):
            sav[i] += counts[i]
    result["sav"] = {SIGNS[i]: sav[i] for i in range(12)}
    result["sav_total"] = sum(sav)
    return result
