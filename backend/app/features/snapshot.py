"""Free first reading: lagna, Moon sign, nakshatra, running dasha, from
localized templates (no LLM)."""

from typing import Dict

from .common import (birth_dict, fmt_date, jc, japi, nak, planet, sign, t)


def _moon_range(profile: Dict):
    """Moon sign / nakshatra at the start and end of the birth day (local),
    to tell whether they are certain when the birth time is unknown."""
    from jyotish import ephemeris
    base = birth_dict(profile)
    out = []
    for hh, mm in ((0, 0), (23, 59)):
        b = dict(base, hour=hh, minute=mm)
        bd = japi.BirthData.from_dict(b)
        moon = ephemeris.planet_positions(bd.jd, bd.ayanamsa)["Moon"]["longitude"]
        out.append((int(moon // 30), int(moon / jc.NAKSHATRA_SPAN) % 27))
    return out


def snapshot(profile: Dict, lang: str) -> Dict:
    birth = birth_dict(profile)
    chart = japi.birth_chart(birth)
    cur = japi.current_dasha(birth)
    time_known = bool(profile.get("time_known", True))

    lagna_en = chart["ascendant"]["sign"]
    moon = chart["planets"]["Moon"]
    moon_en = moon["sign"]
    nk = moon["nakshatra"]
    nak_en, pada = nk["name"], nk["pada"]

    moon_uncertain = nak_uncertain = False
    if not time_known:
        (s0, n0), (s1, n1) = _moon_range(profile)
        moon_uncertain = s0 != s1
        nak_uncertain = n0 != n1

    lines = [t(lang, "snapshot.intro", name=profile.get("name", ""))]
    lagna_line = t(lang, "lagna." + lagna_en)
    moon_line = t(lang, "moon_sign." + moon_en)
    nak_line = t(lang, "nakshatra." + nak_en)
    out = {
        "profile_id": profile.get("id"),
        "lang": lang,
        "time_known": time_known,
        "approximate": not time_known,
        "lagna": {
            "sign": lagna_en, "name": sign(lang, lagna_en),
            "title": t(lang, "snapshot.lagna_line", sign=sign(lang, lagna_en)),
            "text": lagna_line, "approximate": not time_known,
        },
        "moon_sign": {
            "sign": moon_en, "name": sign(lang, moon_en),
            "title": t(lang, "snapshot.moon_line", sign=sign(lang, moon_en)),
            "text": moon_line, "approximate": moon_uncertain,
        },
        "nakshatra": {
            "nakshatra": nak_en, "name": nak(lang, nak_en), "pada": pada,
            "lord": jc.DASHA_SEQUENCE[(nk["index"] - 1) % 9][0],
            "title": t(lang, "snapshot.nakshatra_line", nakshatra=nak(lang, nak_en), pada=pada),
            "text": nak_line, "approximate": nak_uncertain,
        },
    }
    dasha = None
    if "mahadasha" in cur:
        maha, antar = cur["mahadasha"], cur.get("antardasha") or {}
        m_lord, a_lord = maha["lord"], antar.get("lord")
        dasha = {
            "maha": {"lord": m_lord, "name": planet(lang, m_lord),
                     "start": maha["start"], "end": maha["end"],
                     "text": t(lang, "maha." + m_lord)},
            "antar": ({"lord": a_lord, "name": planet(lang, a_lord),
                       "start": antar["start"], "end": antar["end"],
                       "text": t(lang, "antar." + a_lord)} if a_lord else None),
            "title": t(lang, "snapshot.dasha_line",
                       maha=planet(lang, m_lord), maha_end=fmt_date(maha["end"]),
                       antar=planet(lang, a_lord) if a_lord else "-",
                       antar_end=fmt_date(antar["end"]) if a_lord else "-"),
            "approximate": nak_uncertain,
        }
    out["dasha"] = dasha

    lines += [out["lagna"]["title"] + " " + lagna_line,
              out["moon_sign"]["title"] + " " + moon_line,
              out["nakshatra"]["title"] + " " + nak_line]
    if dasha:
        lines.append(dasha["title"])
        lines.append(dasha["maha"]["text"])
        if dasha["antar"]:
            lines.append(dasha["antar"]["text"])
    notes = []
    if not time_known:
        notes.append(t(lang, "snapshot.time_unknown"))
    if moon_uncertain:
        notes.append(t(lang, "snapshot.moon_uncertain"))
    if nak_uncertain:
        notes.append(t(lang, "snapshot.nakshatra_uncertain"))
    out["notes"] = notes
    out["lines"] = lines + notes + [t(lang, "snapshot.next_step")]
    out["disclaimer"] = t(lang, "labels.disclaimer")
    return out
