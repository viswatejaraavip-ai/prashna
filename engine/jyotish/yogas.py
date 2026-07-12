"""Classical yoga detection on the rasi chart (whole-sign houses).

Covers the widely used set: Panch Mahapurusha, lunar and solar yogas,
Gajakesari, Budhaditya, Vipareeta Raja trio, Kemadruma, Adhi, Amala,
Parivartana exchanges, simple Dhana/Raja combinations and Neecha Bhanga.
"""

from typing import Dict, List

from .constants import SIGNS, SIGN_LORDS

_KENDRA = {1, 4, 7, 10}
_TRIKONA = {1, 5, 9}
_DUSTHANA = {6, 8, 12}
_BENEFICS = {"Jupiter", "Venus", "Mercury"}

_OWN = {"Sun": {4}, "Moon": {3}, "Mars": {0, 7}, "Mercury": {2, 5},
        "Jupiter": {8, 11}, "Venus": {1, 6}, "Saturn": {9, 10}}
_EXALT = {"Sun": 0, "Moon": 1, "Mars": 9, "Mercury": 5,
          "Jupiter": 3, "Venus": 11, "Saturn": 6}
_DEBIL = {"Sun": 6, "Moon": 7, "Mars": 3, "Mercury": 11,
          "Jupiter": 9, "Venus": 5, "Saturn": 0}

_MAHAPURUSHA = {"Mars": "Ruchaka", "Mercury": "Bhadra", "Jupiter": "Hamsa",
                "Venus": "Malavya", "Saturn": "Sasa"}


def _sign(lon: float) -> int:
    return int((lon % 360) // 30) % 12


def _house(lon: float, ref: float) -> int:
    return (_sign(lon) - _sign(ref)) % 12 + 1


def detect(positions: Dict[str, float], ascendant: float) -> Dict:
    """Return the yogas present in the chart with the factors that form them."""
    yogas: List[Dict] = []
    asc_sign = _sign(ascendant)
    sign_of = {p: _sign(lon) for p, lon in positions.items()}
    house_of = {p: _house(positions[p], ascendant) for p in positions}
    lord_of_house = {h: SIGN_LORDS[(asc_sign + h - 1) % 12] for h in range(1, 13)}

    def add(name, desc, factors):
        yogas.append({"yoga": name, "description": desc, "factors": factors})

    # Panch Mahapurusha: planet in own/exalted sign in a kendra from lagna
    for planet, yname in _MAHAPURUSHA.items():
        s = sign_of[planet]
        if (s in _OWN[planet] or s == _EXALT[planet]) and house_of[planet] in _KENDRA:
            add("%s Yoga (Panch Mahapurusha)" % yname,
                "%s strong in a kendra — marks distinguished personality and "
                "success in that planet's significations." % planet,
                "%s in %s, house %d" % (planet, SIGNS[s], house_of[planet]))

    # Gajakesari: Jupiter in kendra from Moon
    jm = (_sign(positions["Jupiter"]) - _sign(positions["Moon"])) % 12 + 1
    if jm in _KENDRA:
        add("Gajakesari Yoga",
            "Jupiter in a kendra from the Moon — reputation, wisdom, lasting "
            "prosperity.",
            "Jupiter %d houses from Moon" % jm)

    # Budhaditya: Sun + Mercury together
    if sign_of["Sun"] == sign_of["Mercury"]:
        add("Budhaditya Yoga", "Sun and Mercury conjunct — sharp intellect, "
            "skill in communication and administration.",
            "Both in " + SIGNS[sign_of["Sun"]])

    # Chandra-Mangala: Moon + Mars together
    if sign_of["Moon"] == sign_of["Mars"]:
        add("Chandra-Mangala Yoga", "Moon and Mars conjunct — earning drive "
            "and material enterprise.", "Both in " + SIGNS[sign_of["Moon"]])

    # Guru-Mangala
    if sign_of["Jupiter"] == sign_of["Mars"]:
        add("Guru-Mangala Yoga", "Jupiter and Mars conjunct — energetic "
            "righteousness, technical-dharmic drive.",
            "Both in " + SIGNS[sign_of["Mars"]])

    # Sunapha / Anapha / Durudhara (from Moon, excluding Sun)
    others = [p for p in ("Mars", "Mercury", "Jupiter", "Venus", "Saturn")]
    m2 = [p for p in others if (_sign(positions[p]) - _sign(positions["Moon"])) % 12 == 1]
    m12 = [p for p in others if (_sign(positions["Moon"]) - _sign(positions[p])) % 12 == 1]
    if m2 and m12:
        add("Durudhara Yoga", "Planets on both sides of the Moon — resources, "
            "vehicles and comforts.", "2nd: %s; 12th: %s" % (m2, m12))
    elif m2:
        add("Sunapha Yoga", "Planet in the 2nd from Moon — self-earned wealth "
            "and standing.", "2nd from Moon: %s" % m2)
    elif m12:
        add("Anapha Yoga", "Planet in the 12th from Moon — health, character, "
            "renown.", "12th from Moon: %s" % m12)
    else:
        # Kemadruma needs Moon also unconjunct
        conj_moon = [p for p in others if _sign(positions[p]) == _sign(positions["Moon"])]
        if not conj_moon:
            add("Kemadruma Yoga", "No planets around or with the Moon — "
                "emotional isolation; strength must be built consciously. "
                "(Cancelled if Moon/kendra factors are strong.)",
                "Moon alone in " + SIGNS[sign_of["Moon"]])

    # Vesi / Vasi / Ubhayachari (from Sun, excluding Moon)
    others_s = [p for p in ("Mars", "Mercury", "Jupiter", "Venus", "Saturn")]
    s2 = [p for p in others_s if (_sign(positions[p]) - sign_of["Sun"]) % 12 == 1]
    s12 = [p for p in others_s if (sign_of["Sun"] - _sign(positions[p])) % 12 == 1]
    if s2 and s12:
        add("Ubhayachari Yoga", "Planets on both sides of the Sun — balanced, "
            "influential personality.", "2nd: %s; 12th: %s" % (s2, s12))
    elif s2:
        add("Vesi Yoga", "Planet in the 2nd from the Sun — truthful, "
            "even-tempered nature.", "2nd from Sun: %s" % s2)
    elif s12:
        add("Vasi Yoga", "Planet in the 12th from the Sun — skilful, "
            "charitable disposition.", "12th from Sun: %s" % s12)

    # Adhi: benefics in 6/7/8 from Moon
    adhi = [p for p in _BENEFICS
            if ((_sign(positions[p]) - _sign(positions["Moon"])) % 12 + 1) in (6, 7, 8)]
    if len(adhi) >= 2:
        add("Adhi Yoga", "Benefics in 6th/7th/8th from the Moon — leadership, "
            "comfort and victory over rivals.", "From Moon: %s" % adhi)

    # Amala: benefic in the 10th from Moon or Lagna
    for ref_name, ref in (("Lagna", ascendant), ("Moon", positions["Moon"])):
        amala = [p for p in _BENEFICS
                 if ((_sign(positions[p]) - _sign(ref)) % 12 + 1) == 10]
        if amala:
            add("Amala Yoga", "Benefic alone in the 10th from %s — spotless "
                "reputation and ethical career." % ref_name,
                "10th from %s: %s" % (ref_name, amala))
            break

    # Vipareeta Raja: lord of a dusthana placed in another dusthana
    vip_names = {6: "Harsha", 8: "Sarala", 12: "Vimala"}
    for h, vname in vip_names.items():
        lord = lord_of_house[h]
        if lord in house_of and house_of[lord] in (_DUSTHANA - {h}):
            add("%s (Vipareeta Raja) Yoga" % vname,
                "Lord of the %dth in another dusthana — gains through "
                "adversity, rivals' losses become your wins." % h,
                "%s (lord of %d) in house %d" % (lord, h, house_of[lord]))

    # Parivartana: mutual sign exchange between two lords
    seen = set()
    for p, s in sign_of.items():
        if p in ("Rahu", "Ketu"):
            continue
        host = SIGN_LORDS[s]
        if host == p or host in ("Rahu", "Ketu") or host not in sign_of:
            continue
        if SIGN_LORDS[sign_of[host]] == p and frozenset((p, host)) not in seen:
            seen.add(frozenset((p, host)))
            add("Parivartana Yoga",
                "%s and %s exchange signs — their houses' results are "
                "strongly linked and mutually reinforced." % (p, host),
                "%s in %s, %s in %s" % (p, SIGNS[s], host, SIGNS[sign_of[host]]))

    # Dhana: 2nd lord in 11th or 11th lord in 2nd
    if house_of.get(lord_of_house[2]) == 11 or house_of.get(lord_of_house[11]) == 2:
        add("Dhana Yoga", "Wealth lords (2nd/11th) exchange influence — "
            "strong earning combination.",
            "2nd lord %s in house %s; 11th lord %s in house %s"
            % (lord_of_house[2], house_of.get(lord_of_house[2]),
               lord_of_house[11], house_of.get(lord_of_house[11])))

    # Raja (simple): 9th and 10th lords conjunct
    l9, l10 = lord_of_house[9], lord_of_house[10]
    if l9 != l10 and sign_of.get(l9) == sign_of.get(l10):
        add("Raja Yoga (Dharma-Karmadhipati)",
            "Lords of the 9th and 10th together — fortune united with "
            "career; rise in status.",
            "%s and %s in %s" % (l9, l10, SIGNS[sign_of[l9]]))

    # Neecha Bhanga (basic): debilitated planet whose dispositor is in a
    # kendra from Lagna or Moon
    for planet, deb in _DEBIL.items():
        if sign_of.get(planet) == deb:
            disp = SIGN_LORDS[deb]
            in_kendra = (house_of.get(disp) in _KENDRA or
                         ((_sign(positions[disp]) - _sign(positions["Moon"])) % 12 + 1)
                         in _KENDRA)
            if in_kendra:
                add("Neecha Bhanga Raja Yoga",
                    "%s is debilitated but its dispositor %s stands in a "
                    "kendra — the debility cancels into strength." % (planet, disp),
                    "%s in %s; %s in house %d" % (planet, SIGNS[deb], disp,
                                                  house_of.get(disp, 0)))

    return {
        "count": len(yogas),
        "yogas": yogas,
        "note": "Whole-sign detection of the classical yoga set; strength "
                "grading (uttama/madhyama) is not attempted.",
    }
