"""Kundali matching between two profiles: engine Ashtakoot + Dashakoot +
Manglik, with a verdict and caution lines from the language templates."""

from typing import Dict, Tuple

from .common import birth_dict, japi, jc, nak, sign, t


def order_pair(a: Dict, b: Dict) -> Tuple[Dict, Dict]:
    """(groom, bride). Uses gender when known; otherwise a is the groom."""
    if a.get("gender") == "female" and b.get("gender") != "female":
        return b, a
    return a, b


def _verdict_key(total: float) -> str:
    return ("excellent" if total >= 33 else "very_good" if total >= 25
            else "acceptable" if total >= 18 else "not_recommended")


def match(profile_a: Dict, profile_b: Dict, lang: str) -> Dict:
    groom, bride = order_pair(profile_a, profile_b)
    raw = japi.match_making(birth_dict(groom), birth_dict(bride))
    ak = raw["ashtakoot"]
    total = ak["total"]
    vkey = _verdict_key(total)
    cautions = []
    kootas = {k["koota"]: k for k in ak["kootas"]}
    if kootas["Nadi"]["points"] == 0:
        cautions.append(t(lang, "matching.nadi_dosha"))
    if kootas["Bhakoot"]["points"] == 0:
        b_i = jc.SIGNS.index(kootas["Bhakoot"]["boy"])
        g_i = jc.SIGNS.index(kootas["Bhakoot"]["girl"])
        d1, d2 = (g_i - b_i) % 12 + 1, (b_i - g_i) % 12 + 1
        cautions.append(t(lang, "matching.bhakoot_dosha", d1=d1, d2=d2))
    if kootas["Gana"]["points"] <= 1:
        cautions.append(t(lang, "matching.gana_mismatch"))
    rajju_fail = any(p["porutham"] == "Rajju" and not p["ok"]
                     for p in raw["dashakoot"]["poruthams"])
    if rajju_fail:
        cautions.append(t(lang, "matching.rajju_dosha"))
    mm = raw.get("manglik_match") or {}
    manglik_line = None
    if mm:
        bm, gm = mm["boy"]["is_manglik"], mm["girl"]["is_manglik"]
        manglik_line = t(lang, "matching.manglik_both" if bm and gm else
                         "matching.manglik_none" if not bm and not gm else "matching.manglik_one")
    approx = not (groom.get("time_known", True) and bride.get("time_known", True))

    koota_rows = []
    for k in ak["kootas"]:
        koota_rows.append({"koota": k["koota"], "name": t(lang, "koota_names." + k["koota"]),
                           "points": k["points"], "max": k["max"],
                           "groom": k["boy"], "bride": k["girl"]})
    porutham_rows = [{"porutham": p["porutham"],
                      "name": t(lang, "porutham_names." + p["porutham"]),
                      "ok": p["ok"], "note": p["note"]}
                     for p in raw["dashakoot"]["poruthams"]]
    summary = t(lang, "matching.summary", a=groom.get("name", ""), b=bride.get("name", ""),
                score=_num(total))
    lines = [summary, t(lang, "matching." + vkey)] + cautions
    if manglik_line:
        lines.append(manglik_line)
    if approx:
        lines.append(t(lang, "matching.time_unknown"))

    def person(p: Dict, side: str) -> Dict:
        info = raw[side]
        nk = info["moon_nakshatra"]["name"]
        moon_sign = kootas["Bhakoot"]["boy" if side == "boy" else "girl"]
        return {"profile_id": p.get("id"), "name": p.get("name"),
                "moon_sign": moon_sign, "moon_sign_local": sign(lang, moon_sign),
                "nakshatra": nk, "nakshatra_local": nak(lang, nk),
                "pada": info["moon_nakshatra"]["pada"],
                "manglik": (mm.get(side) or {}).get("is_manglik"),
                "manglik_severity": (mm.get(side) or {}).get("severity"),
                "time_known": p.get("time_known", True)}

    return {
        "groom": person(groom, "boy"), "bride": person(bride, "girl"),
        "guna_milan": {"total": total, "max": 36, "kootas": koota_rows},
        "dashakoot": {"passed": raw["dashakoot"]["passed"], "max": 10,
                      "poruthams": porutham_rows},
        "manglik": {"compatible": mm.get("compatible"), "text": manglik_line},
        "verdict": {"key": vkey, "text": t(lang, "matching." + vkey)},
        "cautions": cautions,
        "approximate": approx,
        "lines": lines,
        "disclaimer": t(lang, "labels.disclaimer"),
    }


def _num(x) -> str:
    return ("%g" % x)
