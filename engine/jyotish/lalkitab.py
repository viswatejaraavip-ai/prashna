"""Lal Kitab essentials: kundali by house, pakka ghar, rins (karmic debts)
with the traditional upay (remedies).

Lal Kitab reads the lagna chart but interprets planets through fixed house
significations. This module covers the widely published core: house
placements, pakka-ghar (permanent house) occupancy, and the classical debt
combinations with their standard remedies.
"""

from typing import Dict, List

from .constants import SIGNS

# Permanent (pakka) houses of each planet in Lal Kitab
_PAKKA_GHAR = {1: ["Sun"], 2: ["Jupiter"], 3: ["Mars"], 4: ["Moon"],
               5: ["Jupiter"], 6: ["Mercury", "Ketu"], 7: ["Venus", "Mercury"],
               8: ["Saturn", "Mars"], 9: ["Jupiter"], 10: ["Saturn"],
               11: ["Jupiter"], 12: ["Jupiter", "Rahu"]}

_RINS = [
    {"name": "Pitru Rin (father's debt)",
     "planets": {"Venus", "Mercury", "Rahu"}, "houses": {5},
     "effect": "obstacles to status and lineage; friction with elders",
     "remedy": "Collect equal contributions from every blood relative and "
               "donate the pooled amount to a temple in one day."},
    {"name": "Matru Rin (mother's debt)",
     "planets": {"Ketu"}, "houses": {4},
     "effect": "domestic unrest, worries through property or vehicles",
     "remedy": "Collect equal amounts from blood relatives and immerse "
               "silver in a river; serve and respect the mother."},
    {"name": "Stri Rin (debt of the feminine)",
     "planets": {"Sun", "Moon", "Rahu"}, "houses": {2, 7},
     "effect": "disharmony in marriage and finances",
     "remedy": "Feed 100 cows in one day with contributions gathered from "
               "family members; honour the spouse."},
    {"name": "Bhratru Rin (sibling's debt)",
     "planets": {"Mercury", "Ketu"}, "houses": {1, 8},
     "effect": "strained sibling ties; instability in ventures",
     "remedy": "Donate medicines to the needy from pooled family "
               "contributions; support brothers and sisters."},
    {"name": "Kanya/Behen Rin (sister's debt)",
     "planets": {"Moon", "Mars"}, "houses": {3, 6},
     "effect": "delays through disputes; loss via relatives",
     "remedy": "Feed yellow food to girls/birds for consecutive days; "
               "treat sisters and daughters generously."},
]


def analyze(positions: Dict[str, float], ascendant: float) -> Dict:
    asc_sign = int((ascendant % 360) // 30) % 12
    house_of = {p: (int((lon % 360) // 30) - asc_sign) % 12 + 1
                for p, lon in positions.items()}

    houses: Dict[int, List[str]] = {h: [] for h in range(1, 13)}
    for p, h in house_of.items():
        houses[h].append(p)

    in_pakka = [p for p, h in house_of.items() if p in _PAKKA_GHAR.get(h, [])]

    debts = []
    for rin in _RINS:
        hits = [p for p in rin["planets"]
                if house_of.get(p) in rin["houses"]]
        if hits:
            debts.append({"rin": rin["name"], "formed_by":
                          ["%s in house %d" % (p, house_of[p]) for p in hits],
                          "effect": rin["effect"], "remedy": rin["remedy"]})

    return {
        "system": "Lal Kitab essentials (house chart, pakka ghar, rins)",
        "lagna_sign": SIGNS[asc_sign],
        "houses": {str(h): ps for h, ps in houses.items()},
        "pakka_ghar": {str(h): _PAKKA_GHAR[h] for h in range(1, 13)},
        "planets_in_pakka_ghar": in_pakka,
        "empty_houses": [h for h, ps in houses.items() if not ps],
        "rins": debts,
        "note": "Debts and remedies follow the commonly published Lal Kitab "
                "combinations; a Lal Kitab practitioner may weigh aspects "
                "and 'sleeping' planets further.",
    }
