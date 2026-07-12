"""Gemstone recommendations from the lagna (classical benefic-lord method).

Life stone = lagna lord; fortune (bhagya) stone = 9th lord; career/creative
(karma/santana) stone = 5th lord (widely used with 10th as alternative).
Stones of the 6th, 8th and 12th lords are flagged as generally avoided.
"""

from typing import Dict

from .constants import SIGN_LORDS, SIGNS

GEMS = {
    "Sun": {"gem": "Ruby", "hindi": "Manikya", "substitutes": ["Red Garnet", "Red Spinel"],
            "metal": "Gold / copper", "finger": "Ring finger", "day": "Sunday",
            "carats": "3-5", "mantra": "Om Suryaya Namah"},
    "Moon": {"gem": "Pearl", "hindi": "Moti", "substitutes": ["Moonstone"],
             "metal": "Silver", "finger": "Little finger", "day": "Monday",
             "carats": "4-6", "mantra": "Om Chandraya Namah"},
    "Mars": {"gem": "Red Coral", "hindi": "Moonga", "substitutes": ["Carnelian"],
             "metal": "Gold / copper", "finger": "Ring finger", "day": "Tuesday",
             "carats": "5-8", "mantra": "Om Mangalaya Namah"},
    "Mercury": {"gem": "Emerald", "hindi": "Panna", "substitutes": ["Peridot", "Green Tourmaline"],
                "metal": "Gold", "finger": "Little finger", "day": "Wednesday",
                "carats": "3-6", "mantra": "Om Budhaya Namah"},
    "Jupiter": {"gem": "Yellow Sapphire", "hindi": "Pukhraj", "substitutes": ["Citrine", "Yellow Topaz"],
                "metal": "Gold", "finger": "Index finger", "day": "Thursday",
                "carats": "3-5", "mantra": "Om Brihaspataye Namah"},
    "Venus": {"gem": "Diamond", "hindi": "Heera", "substitutes": ["White Sapphire", "White Zircon"],
              "metal": "Platinum / silver", "finger": "Middle or ring finger", "day": "Friday",
              "carats": "0.5-1.5", "mantra": "Om Shukraya Namah"},
    "Saturn": {"gem": "Blue Sapphire", "hindi": "Neelam", "substitutes": ["Amethyst", "Iolite"],
               "metal": "Silver / panchdhatu", "finger": "Middle finger", "day": "Saturday",
               "carats": "3-5", "mantra": "Om Shanaye Namah"},
    "Rahu": {"gem": "Hessonite Garnet", "hindi": "Gomed", "substitutes": ["Orange Zircon"],
             "metal": "Silver / panchdhatu", "finger": "Middle finger", "day": "Saturday",
             "carats": "4-6", "mantra": "Om Rahave Namah"},
    "Ketu": {"gem": "Cat's Eye", "hindi": "Lehsunia", "substitutes": ["Chrysoberyl Cat's Eye"],
             "metal": "Silver / panchdhatu", "finger": "Middle finger", "day": "Thursday",
             "carats": "3-5", "mantra": "Om Ketave Namah"},
}


def recommend(ascendant: float) -> Dict:
    asc_sign = int((ascendant % 360) // 30) % 12
    lord = {h: SIGN_LORDS[(asc_sign + h - 1) % 12] for h in range(1, 13)}

    def entry(role, house, note):
        planet = lord[house]
        return dict(GEMS[planet], role=role, planet=planet, house=house, note=note)

    avoid = []
    for h in (6, 8, 12):
        p = lord[h]
        # A dusthana lord that also owns a good house is not flat-out avoided.
        good_too = any(lord[g] == p for g in (1, 5, 9))
        if not good_too:
            avoid.append({"planet": p, "gem": GEMS[p]["gem"], "house": h})

    return {
        "system": "Classical benefic-lord method (lagna based)",
        "lagna_sign": SIGNS[asc_sign],
        "recommended": [
            entry("Life stone (lagna lord)", 1,
                  "Wear for overall vitality, identity and health."),
            entry("Fortune stone (9th lord)", 9,
                  "Wear for luck, dharma and opportunities."),
            entry("Wisdom/creativity stone (5th lord)", 5,
                  "Wear for education, children and creative growth."),
        ],
        "avoid": avoid,
        "note": "Test a new stone for a trial period per tradition. This is a "
                "sign-lordship recommendation; a practitioner may refine it "
                "with dasha and strength analysis.",
    }
