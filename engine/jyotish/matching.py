"""Kundali matching: Ashtakoot (36 guna) and Dashakoot (South Indian porutham).

Inputs are the boy's and girl's Moon longitudes (sidereal). Conventions follow
the widely published classical tables (North Indian Ashtakoot; Tamil/South
Dashakoot as pass/fail with notes).
"""

from typing import Dict, List

from .constants import NAKSHATRAS, NAKSHATRA_SPAN, SIGNS, SIGN_LORDS

# ---------------- lookup tables (index = sign 0..11 or nakshatra 0..26) ----

_VARNA = ["Kshatriya", "Vaishya", "Shudra", "Brahmin", "Kshatriya", "Vaishya",
          "Shudra", "Brahmin", "Kshatriya", "Vaishya", "Shudra", "Brahmin"]
_VARNA_RANK = {"Brahmin": 3, "Kshatriya": 2, "Vaishya": 1, "Shudra": 0}

_VASHYA = ["Chatushpada", "Chatushpada", "Manava", "Jalachara", "Vanachara",
           "Manava", "Manava", "Keeta", "Chatushpada", "Chatushpada",
           "Manava", "Jalachara"]
_VASHYA_SCORE = {  # boy group -> girl group -> points (of 2)
    "Chatushpada": {"Chatushpada": 2, "Manava": 1, "Jalachara": 1, "Vanachara": 0, "Keeta": 1},
    "Manava":      {"Chatushpada": 1, "Manava": 2, "Jalachara": 0.5, "Vanachara": 0, "Keeta": 1},
    "Jalachara":   {"Chatushpada": 1, "Manava": 0.5, "Jalachara": 2, "Vanachara": 0, "Keeta": 1},
    "Vanachara":   {"Chatushpada": 0, "Manava": 0, "Jalachara": 0, "Vanachara": 2, "Keeta": 0},
    "Keeta":       {"Chatushpada": 1, "Manava": 1, "Jalachara": 1, "Vanachara": 0, "Keeta": 2},
}

# Yoni animal per nakshatra (classical list)
_YONI = ["Horse", "Elephant", "Sheep", "Serpent", "Serpent", "Dog",
         "Cat", "Sheep", "Cat", "Rat", "Rat", "Cow",
         "Buffalo", "Tiger", "Buffalo", "Tiger", "Deer", "Deer",
         "Dog", "Monkey", "Mongoose", "Monkey", "Lion", "Horse",
         "Lion", "Cow", "Elephant"]
_YONI_ENEMY = {  # sworn enemies score 0
    "Horse": "Buffalo", "Buffalo": "Horse", "Elephant": "Lion", "Lion": "Elephant",
    "Sheep": "Monkey", "Monkey": "Sheep", "Serpent": "Mongoose", "Mongoose": "Serpent",
    "Dog": "Deer", "Deer": "Dog", "Cat": "Rat", "Rat": "Cat",
    "Cow": "Tiger", "Tiger": "Cow",
}
_YONI_FRIENDS = {  # unordered friendly pairs score 3
    frozenset(p) for p in [
        ("Horse", "Sheep"), ("Horse", "Serpent"), ("Elephant", "Sheep"),
        ("Elephant", "Monkey"), ("Sheep", "Serpent"), ("Serpent", "Dog"),
        ("Dog", "Monkey"), ("Cat", "Cow"), ("Rat", "Buffalo"), ("Cow", "Buffalo"),
        ("Tiger", "Lion"), ("Deer", "Monkey"), ("Mongoose", "Lion"),
    ]
}

# Natural planetary friendship (rows: planet -> friends / enemies)
_FRIENDS = {
    "Sun": {"Moon", "Mars", "Jupiter"}, "Moon": {"Sun", "Mercury"},
    "Mars": {"Sun", "Moon", "Jupiter"}, "Mercury": {"Sun", "Venus"},
    "Jupiter": {"Sun", "Moon", "Mars"}, "Venus": {"Mercury", "Saturn"},
    "Saturn": {"Mercury", "Venus"},
}
_ENEMIES = {
    "Sun": {"Venus", "Saturn"}, "Moon": set(),
    "Mars": {"Mercury"}, "Mercury": {"Moon"},
    "Jupiter": {"Mercury", "Venus"}, "Venus": {"Sun", "Moon"},
    "Saturn": {"Sun", "Moon", "Mars"},
}

_GANA = ["Deva", "Manushya", "Rakshasa", "Manushya", "Deva", "Manushya",
         "Deva", "Deva", "Rakshasa", "Rakshasa", "Manushya", "Manushya",
         "Deva", "Rakshasa", "Deva", "Rakshasa", "Deva", "Rakshasa",
         "Rakshasa", "Manushya", "Manushya", "Deva", "Rakshasa", "Rakshasa",
         "Manushya", "Manushya", "Deva"]
_GANA_SCORE = {  # boy -> girl -> points (of 6)
    "Deva":     {"Deva": 6, "Manushya": 6, "Rakshasa": 0},
    "Manushya": {"Deva": 5, "Manushya": 6, "Rakshasa": 0},
    "Rakshasa": {"Deva": 1, "Manushya": 0, "Rakshasa": 6},
}

_NADI = ["Adi", "Madhya", "Antya"]  # cycle over nakshatras: pattern below
_NADI_OF_NAK = [0, 1, 2, 2, 1, 0, 0, 1, 2, 2, 1, 0, 0, 1, 2, 2, 1, 0,
                0, 1, 2, 2, 1, 0, 0, 1, 2]

# Rajju groups (Tamil convention): 0=Pada,1=Kati,2=Nabhi,3=Kantha,4=Siro
_RAJJU = [0, 1, 2, 3, 4, 3, 2, 1, 0, 0, 1, 2, 3, 4, 3, 2, 1, 0,
          0, 1, 2, 3, 4, 3, 2, 1, 0]
_RAJJU_NAMES = ["Pada (feet)", "Kati (waist)", "Nabhi (navel)",
                "Kantha (neck)", "Siro (head)"]

# Vedha (mutually afflicting) nakshatra pairs, 1-indexed classical list
_VEDHA_PAIRS = {frozenset(p) for p in [
    (1, 18), (2, 17), (3, 16), (4, 15), (5, 23), (6, 22), (7, 21),
    (8, 20), (9, 19), (10, 27), (11, 26), (12, 25), (13, 24), (14, 14),
]}


def _nak_index(lon: float) -> int:
    return int((lon % 360.0) / NAKSHATRA_SPAN) % 27


def _sign_index(lon: float) -> int:
    return int((lon % 360.0) // 30) % 12


def _count_from(a: int, b: int, n: int = 27) -> int:
    """Inclusive count from star a to star b (1..n)."""
    return (b - a) % n + 1


def ashtakoot(boy_moon: float, girl_moon: float) -> Dict:
    """North Indian 36-guna match from the two Moon longitudes."""
    bn, gn = _nak_index(boy_moon), _nak_index(girl_moon)
    bs, gs = _sign_index(boy_moon), _sign_index(girl_moon)
    kootas: List[Dict] = []

    bv, gv = _VARNA[bs], _VARNA[gs]
    varna = 1 if _VARNA_RANK[bv] >= _VARNA_RANK[gv] else 0
    kootas.append({"koota": "Varna", "max": 1, "points": varna,
                   "boy": bv, "girl": gv,
                   "meaning": "spiritual compatibility / ego"})

    bva, gva = _VASHYA[bs], _VASHYA[gs]
    vashya = _VASHYA_SCORE[bva][gva]
    kootas.append({"koota": "Vashya", "max": 2, "points": vashya,
                   "boy": bva, "girl": gva,
                   "meaning": "mutual influence and control"})

    t1 = _count_from(gn, bn) % 9  # girl -> boy
    t2 = _count_from(bn, gn) % 9
    bad = {3, 5, 7, 0}  # Vipat, Pratyari, Naidhana (0 == 9th? 9 % 9 -> 0 is Ati-mitra, good)
    bad = {3, 5, 7}
    good1, good2 = (t1 % 9) not in bad, (t2 % 9) not in bad
    tara = 3 if good1 and good2 else 1.5 if good1 or good2 else 0
    kootas.append({"koota": "Tara", "max": 3, "points": tara,
                   "boy": NAKSHATRAS[bn], "girl": NAKSHATRAS[gn],
                   "meaning": "destiny and health of the couple"})

    by, gy = _YONI[bn], _YONI[gn]
    if by == gy:
        yoni = 4
    elif _YONI_ENEMY.get(by) == gy:
        yoni = 0
    elif frozenset((by, gy)) in _YONI_FRIENDS:
        yoni = 3
    else:
        yoni = 2
    kootas.append({"koota": "Yoni", "max": 4, "points": yoni,
                   "boy": by, "girl": gy, "meaning": "physical/instinctive harmony"})

    bl, gl = SIGN_LORDS[bs], SIGN_LORDS[gs]
    def _rel(p, q):
        if p == q:
            return "same"
        if q in _FRIENDS[p]:
            return "friend"
        if q in _ENEMIES[p]:
            return "enemy"
        return "neutral"
    r1, r2 = _rel(bl, gl), _rel(gl, bl)
    rels = {r1, r2}
    if r1 in ("same", "friend") and r2 in ("same", "friend"):
        maitri = 5
    elif "friend" in rels and "neutral" in rels:
        maitri = 4
    elif rels == {"neutral"}:
        maitri = 3
    elif "friend" in rels and "enemy" in rels:
        maitri = 1
    elif "neutral" in rels and "enemy" in rels:
        maitri = 0.5
    else:
        maitri = 0
    kootas.append({"koota": "Graha Maitri", "max": 5, "points": maitri,
                   "boy": bl, "girl": gl,
                   "meaning": "mental compatibility (Moon-sign lords)"})

    bg, gg = _GANA[bn], _GANA[gn]
    gana = _GANA_SCORE[bg][gg]
    kootas.append({"koota": "Gana", "max": 6, "points": gana,
                   "boy": bg, "girl": gg, "meaning": "temperament match"})

    d1 = (gs - bs) % 12 + 1  # boy -> girl inclusive
    d2 = (bs - gs) % 12 + 1
    bhakoot = 0 if {d1, d2} in ({2, 12}, {5, 9}, {6, 8}) else 7
    kootas.append({"koota": "Bhakoot", "max": 7, "points": bhakoot,
                   "boy": SIGNS[bs], "girl": SIGNS[gs],
                   "meaning": "emotional bond, family growth"})

    bnadi, gnadi = _NADI[_NADI_OF_NAK[bn]], _NADI[_NADI_OF_NAK[gn]]
    nadi = 0 if bnadi == gnadi else 8
    kootas.append({"koota": "Nadi", "max": 8, "points": nadi,
                   "boy": bnadi, "girl": gnadi,
                   "meaning": "health and progeny (most weighted)"})

    total = sum(k["points"] for k in kootas)
    verdict = ("Excellent match" if total >= 33 else
               "Very good match" if total >= 25 else
               "Acceptable match" if total >= 18 else
               "Not recommended without remedies")
    return {"system": "Ashtakoot (36 guna)", "kootas": kootas,
            "total": total, "max": 36, "verdict": verdict,
            "cautions": [c for c in [
                "Nadi dosha (same nadi)" if nadi == 0 else None,
                "Bhakoot dosha (%d/%d)" % (d1, d2) if bhakoot == 0 else None,
                "Gana mismatch" if gana <= 1 else None,
            ] if c]}


def dashakoot(boy_moon: float, girl_moon: float) -> Dict:
    """South Indian 10-porutham match (pass/fail with notes)."""
    bn, gn = _nak_index(boy_moon), _nak_index(girl_moon)
    bs, gs = _sign_index(boy_moon), _sign_index(girl_moon)
    cnt = _count_from(gn, bn)  # girl -> boy inclusive
    poruthams: List[Dict] = []

    def add(name, ok, note):
        poruthams.append({"porutham": name, "ok": bool(ok), "note": note})

    rem = cnt % 9
    add("Dina", rem not in (3, 5, 7),
        "count girl→boy %d (rem %d); 3/5/7 afflicted" % (cnt, rem))
    bg, gg = _GANA[bn], _GANA[gn]
    add("Gana", _GANA_SCORE[bg][gg] >= 5, "%s + %s" % (bg, gg))
    add("Mahendra", cnt in (4, 7, 10, 13, 16, 19, 22, 25),
        "count girl→boy %d; 4,7,10,... favour lineage" % cnt)
    add("Stree Deergha", cnt > 13, "count girl→boy %d; > 13 preferred" % cnt)
    by, gy = _YONI[bn], _YONI[gn]
    add("Yoni", _YONI_ENEMY.get(by) != gy, "%s + %s" % (by, gy))
    d1 = (gs - bs) % 12 + 1
    d2 = (bs - gs) % 12 + 1
    add("Rasi", {d1, d2} not in ({2, 12}, {5, 9}, {6, 8}),
        "signs %s / %s (%d-%d)" % (SIGNS[bs], SIGNS[gs], d1, d2))
    bl, gl = SIGN_LORDS[bs], SIGN_LORDS[gs]
    add("Rasyadhipati", gl not in _ENEMIES[bl] and bl not in _ENEMIES[gl],
        "lords %s + %s" % (bl, gl))
    add("Vasya", _VASHYA_SCORE[_VASHYA[bs]][_VASHYA[gs]] >= 1,
        "%s + %s" % (_VASHYA[bs], _VASHYA[gs]))
    add("Rajju", _RAJJU[bn] != _RAJJU[gn],
        "boy %s, girl %s — same rajju afflicts longevity"
        % (_RAJJU_NAMES[_RAJJU[bn]], _RAJJU_NAMES[_RAJJU[gn]]))
    add("Vedha", frozenset((bn + 1, gn + 1)) not in _VEDHA_PAIRS,
        "%s + %s" % (NAKSHATRAS[bn], NAKSHATRAS[gn]))

    passed = sum(1 for p in poruthams if p["ok"])
    verdict = ("Excellent match" if passed >= 8 else
               "Good match" if passed >= 6 else
               "Average — consult further" if passed >= 5 else
               "Not recommended")
    # Rajju is considered essential in the South tradition
    if not poruthams[8]["ok"]:
        verdict += " (Rajju dosha present — traditionally a strong objection)"
    return {"system": "Dashakoot (10 porutham)", "poruthams": poruthams,
            "passed": passed, "max": 10, "verdict": verdict}


def match(boy_moon: float, girl_moon: float,
          boy_positions: Dict = None, girl_positions: Dict = None,
          boy_asc: float = None, girl_asc: float = None) -> Dict:
    """Full match report: Ashtakoot + Dashakoot (+ Manglik cross-check when
    full positions are supplied)."""
    out = {
        "ashtakoot": ashtakoot(boy_moon, girl_moon),
        "dashakoot": dashakoot(boy_moon, girl_moon),
    }
    if boy_positions and girl_positions and boy_asc is not None and girl_asc is not None:
        from . import doshas
        bm = doshas.manglik(boy_positions, boy_asc)
        gm = doshas.manglik(girl_positions, girl_asc)
        both = bm["is_manglik"] == gm["is_manglik"]
        out["manglik_match"] = {
            "boy": bm, "girl": gm,
            "compatible": both,
            "note": ("Both share the same Manglik status — dosha is mutually "
                     "cancelled." if both and bm["is_manglik"] else
                     "Neither is Manglik." if both else
                     "One partner is Manglik and the other is not — "
                     "traditionally needs remedies or further review."),
        }
    return out
