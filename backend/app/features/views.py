"""Display-ready, fully localized views of engine results for the app.

Every chart endpoint returns `view` next to the raw `data`:

    {"chart":  {"lagna": 0-11, "planets": [{"key": "Sun", "sign": 0-11, "retro": bool}]},
     "charts": [{"title": str, "chart": {...}}],          # all vargas
     "sections": [{"title": str, "rows": [[label, value], ...]}
                 |{"title": str, "table": {"columns": [...], "rows": [[...], ...]}}
                 |{"title": str, "items": [{"title", "text", "badge", "tone"}]}
                 |{"title": str, "text": str}]}

Planet/sign/nakshatra names come from the engine locale. Every other English
phrase goes through `c.t(...)`: the view is built once to collect phrases,
they are translated in one cached batch (translate.py), and the view is
built again with the translations, so the app never shows engine English.
"""

import logging
import re
from typing import Any, Dict, List, Optional

from jyotish import constants as jc

from .common import fmt_date, names

log = logging.getLogger("udhyath.features.views")
SIGNS = list(jc.SIGNS)
PLANETS = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Rahu", "Ketu"]


class _Ctx:
    def __init__(self, lang: str, tr: Optional[Dict[str, str]] = None):
        self.lang = lang
        self.n = names(lang)
        self.tr = tr          # None = collecting pass
        self.seen: List[str] = []

    def t(self, text: str) -> str:
        text = str(text or "")
        if not text.strip() or self.lang == "en":
            return text
        if self.tr is None:
            self.seen.append(text)
            return text
        return self.tr.get(text, text)

    def planet(self, p: str) -> str:
        return self.n["planets"].get(p, self.t(p) if p else "")

    def sign(self, s) -> str:
        if isinstance(s, int):
            s = SIGNS[s % 12]
        return self.n["signs"].get(s, s)

    def nak(self, n: str) -> str:
        return self.n["nakshatras"].get(n, n)

    def weekday(self, w: str) -> str:
        return self.n["weekdays"].get(w, w)

    def term(self, kind: str, v: str) -> str:
        return self.n.get(kind, {}).get(v, self.t(v))


def _sign_index(v) -> Optional[int]:
    if isinstance(v, int):
        return v % 12
    if isinstance(v, dict):
        if isinstance(v.get("sign_index"), int):
            return v["sign_index"] % 12
        v = v.get("sign")
    if isinstance(v, str) and v in SIGNS:
        return SIGNS.index(v)
    return None


def _date(v) -> str:
    try:
        return fmt_date(v)
    except Exception:
        return str(v)


def _deg(v) -> str:
    return v.get("dms") or ("%.2f°" % v["degrees_in_sign"] if "degrees_in_sign" in v else "")


def _chart(lagna, placements: Dict[str, Any]) -> Optional[Dict]:
    li = _sign_index(lagna)
    planets = []
    for p in PLANETS:
        if p in placements:
            si = _sign_index(placements[p])
            if si is not None:
                retro = bool(placements[p].get("retrograde")) if isinstance(placements[p], dict) else False
                planets.append({"key": p, "sign": si, "retro": retro})
    if li is None or len(planets) < 5:
        return None
    return {"lagna": li, "planets": planets}


# ---------------- per-kind builders ----------------

def _rasi(d: Dict, c: _Ctx) -> Dict:
    asc = d.get("ascendant") or {}
    pl = d.get("planets") or {}
    rows = [[c.t("Lagna"), c.sign(asc.get("sign", "")), _deg(asc), "", "1"]]
    for p in PLANETS:
        v = pl.get(p)
        if not v:
            continue
        nk = v.get("nakshatra") or {}
        nk_txt = ("%s %s" % (c.nak(nk.get("name", "")), nk.get("pada", ""))).strip() if isinstance(nk, dict) else c.nak(str(nk))
        rows.append([c.planet(p) + (" (" + c.t("R") + ")" if v.get("retrograde") else ""),
                     c.sign(v.get("sign", "")), _deg(v), nk_txt, str(v.get("house_whole_sign", ""))])
    return {"chart": _chart(asc, pl),
            "sections": [{"title": c.t("Planet positions"),
                          "table": {"columns": [c.t("Planet"), c.t("Sign"), c.t("Degree in sign"), c.t("Nakshatra"), c.t("House")],
                                    "rows": rows}}]}


def _varga(d: Dict, c: _Ctx) -> Dict:
    pl = d.get("placements") or {}
    rows = [[c.planet(p), c.sign(pl[p].get("sign", "")), str(pl[p].get("house_from_varga_lagna", ""))]
            for p in PLANETS if isinstance(pl.get(p), dict)]
    sections = []
    if d.get("signification"):
        sections.append({"title": c.t(d.get("varga", "")) if d.get("varga") else "", "text": c.t(d["signification"])})
    sections.append({"title": c.t("Planet positions"),
                     "table": {"columns": [c.t("Planet"), c.t("Sign"), c.t("House")], "rows": rows}})
    return {"chart": _chart(d.get("ascendant_sign"), pl), "sections": sections}


_VARGA_NAMES = {"D1": "Rasi", "D2": "Hora", "D3": "Drekkana", "D4": "Chaturthamsa", "D7": "Saptamsa",
                "D9": "Navamsa", "D10": "Dasamsa", "D12": "Dwadasamsa", "D16": "Shodasamsa",
                "D20": "Vimsamsa", "D24": "Chaturvimsamsa", "D27": "Saptavimsamsa", "D30": "Trimsamsa",
                "D40": "Khavedamsa", "D45": "Akshavedamsa", "D60": "Shashtiamsa"}


def _all_vargas(d: Dict, c: _Ctx) -> Dict:
    charts = []
    for code, pos in (d.get("charts") or {}).items():
        ch = _chart(pos.get("Lagna"), pos)
        if ch:
            charts.append({"title": "%s · %s" % (code, c.t(_VARGA_NAMES.get(code, code))), "chart": ch})
    return {"charts": charts, "sections": []}


def _bhava(d: Dict, c: _Ctx) -> Dict:
    pl = d.get("placements") or {}
    by_house: Dict[int, List[str]] = {}
    for p in PLANETS:
        if isinstance(pl.get(p), int):
            by_house.setdefault(pl[p], []).append(c.planet(p))
    rows = [[str(h), ", ".join(by_house.get(h, [])) or "—"] for h in range(1, 13)]
    return {"sections": [{"title": c.t("Bhava chalit (house placements)"),
                          "table": {"columns": [c.t("House"), c.t("Planets")], "rows": rows}}]}


def _dashas(d: Dict, c: _Ctx) -> Dict:
    cur = d.get("current") or {}
    rows = []
    for key, label in (("mahadasha", "Mahadasha"), ("antardasha", "Antardasha"),
                       ("pratyantardasha", "Pratyantardasha")):
        v = cur.get(key)
        if v:
            rows.append([c.t(label), "%s (%s – %s)" % (c.planet(v["lord"]), _date(v["start"]), _date(v["end"]))])
    sections = [{"title": c.t("Running now"), "rows": rows}] if rows else []
    now_lord = (cur.get("mahadasha") or {}).get("lord")
    items = []
    for m in d.get("mahadashas") or []:
        is_now = m.get("lord") == now_lord and cur.get("mahadasha", {}).get("start") == m.get("start")
        antar = ", ".join("%s %s" % (c.planet(a["lord"]), _date(a["end"])) for a in (m.get("antardashas") or [])[:9])
        items.append({"title": "%s · %s – %s" % (c.planet(m["lord"]), _date(m["start"]), _date(m["end"])),
                      "text": (c.t("Antardashas end") + ": " + antar) if antar else "",
                      "badge": c.t("Running now") if is_now else "%s %s" % (m.get("years", ""), c.t("years")),
                      "tone": "good" if is_now else ""})
    sections.append({"title": c.t("Vimshottari mahadashas"), "items": items})
    return {"sections": sections}


def _plain_list(s: str) -> str:
    """Engine factor strings embed Python lists ("... ['Mercury', 'Saturn']")."""
    return re.sub(r"\[([^\]]*)\]", lambda m: m.group(1).replace("'", "").replace('"', ""), s)


def _yogas(d: Dict, c: _Ctx) -> Dict:
    items = [{"title": c.t(y.get("yoga", "")), "text": c.t(y.get("description", "")),
              "badge": c.t(_plain_list(y["factors"])) if isinstance(y.get("factors"), str) else ""}
             for y in d.get("yogas") or []]
    sec = [{"title": c.t("Yogas in your chart"), "items": items}] if items else \
        [{"title": c.t("Yogas in your chart"), "text": c.t("No classical yogas were detected.")}]
    return {"sections": sec}


def _doshas(d: Dict, c: _Ctx) -> Dict:
    items = []
    m = d.get("manglik") or {}
    if m:
        present = m.get("is_manglik")
        txt = [c.t("Severity") + ": " + c.t(str(m.get("severity", "")))] if present else []
        if m.get("cancellations"):
            txt.append(c.t("Cancellations") + ": " + "; ".join(c.t(x) for x in m["cancellations"]))
        items.append({"title": c.t(m.get("dosha", "Manglik")), "text": "\n".join(txt),
                      "badge": c.t("Present") if present else c.t("Not present"),
                      "tone": "bad" if present else "good"})
    k = d.get("kaal_sarpa") or {}
    if k:
        present, partial = k.get("present"), k.get("partial")
        items.append({"title": c.t(k.get("dosha", "Kaal Sarpa")),
                      "text": c.t(k["type"]) if (present or partial) and k.get("type") else "",
                      "badge": c.t("Present") if present else c.t("Partial") if partial else c.t("Not present"),
                      "tone": "bad" if present else "warn" if partial else "good"})
    s = d.get("sadhe_sati") or {}
    if s:
        cur = s.get("currently_active")
        text = ""
        if cur:
            text = "%s (%s – %s)" % (c.t(cur.get("phase", "")), _date(cur["start"]), _date(cur["end"]))
        upcoming = [w for w in s.get("windows") or [] if str(w.get("start", "")) > (cur or {}).get("end", "")][:3]
        if upcoming:
            text += ("\n" if text else "") + c.t("Next") + ": " + "; ".join(
                "%s %s – %s" % (c.t(w.get("phase", "")), _date(w["start"]), _date(w["end"])) for w in upcoming)
        items.append({"title": c.t(s.get("dosha", "Sadhe Sati")), "text": text,
                      "badge": c.t("Running now") if cur else c.t("Not running"),
                      "tone": "warn" if cur else "good"})
    return {"sections": [{"title": c.t("Doshas"), "items": items}]}


def _houses(xs) -> str:
    return ", ".join(str(h) for h in (xs or []))


def _kp(d: Dict, c: _Ctx) -> Dict:
    """KP: Placidus cusps, planets and the house significators, as the three
    tables an astrologer reads them in (never the generic key/value dump)."""
    cols = [c.t("Sign"), c.t("Sign lord"), c.t("Star"), c.t("Star lord"),
            c.t("Sub lord"), c.t("Sub sub lord")]

    def cells(v: Dict) -> List[str]:
        return [c.sign(v.get("sign", "")), c.planet(v.get("sign_lord", "")),
                c.nak(v.get("star", "")), c.planet(v.get("star_lord", "")),
                c.planet(v.get("sub_lord", "")), c.planet(v.get("sub_sub_lord", ""))]

    cusps = d.get("cusps") or []
    pl = d.get("planets") or {}
    sections = [
        {"title": c.t("KP cusps"), "table": {
            "columns": [c.t("Cusp")] + cols,
            "rows": [[str(x.get("cusp", i + 1))] + cells(x) for i, x in enumerate(cusps)]}},
        {"title": c.t("KP planets"), "table": {
            "columns": [c.t("Planet")] + cols,
            "rows": [[c.planet(p) + (" (" + c.t("R") + ")" if pl[p].get("retrograde") else "")]
                     + cells(pl[p]) for p in PLANETS if isinstance(pl.get(p), dict)]}},
    ]
    sig = (d.get("significators") or {}).get("planets") or {}
    if sig:
        sections.append({"title": c.t("House significators"), "table": {
            "columns": [c.t("Planet"), c.t("Star lord"), c.t("Star lord sits in"),
                        c.t("Houses owned by the star lord"), c.t("Sits in"), c.t("Houses owned")],
            "rows": [[c.planet(p), c.planet(v.get("star_lord", "")),
                      str(v.get("star_lord_house", "")), _houses(v.get("star_lord_owns")),
                      str(v.get("own_house", "")), _houses(v.get("owns"))]
                     for p, v in sig.items() if isinstance(v, dict)]}})
    if d.get("system"):
        sections.append({"title": c.t("Method"), "text": c.t(d["system"])})
    return {"chart": _chart(cusps[0] if cusps else None, pl), "sections": sections}


# (engine key, label) for the six sources of strength, in the classical order.
_SHADBALA_PARTS = (("sthana_total", "Sthana bala"), ("dig", "Dig bala"),
                   ("kala_total", "Kala bala"), ("chesta", "Chesta bala"),
                   ("naisargika", "Naisargika bala"), ("drik", "Drik bala"))


def _num(v) -> str:
    try:
        return ("%.2f" % float(v)).rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return ""


def _shadbala(d: Dict, c: _Ctx) -> Dict:
    pl = d.get("planets") or {}
    rows = []
    for p in PLANETS:
        v = pl.get(p)
        if not isinstance(v, dict):
            continue
        rows.append([c.planet(p)] + [_num(v.get(k)) for k, _ in _SHADBALA_PARTS]
                    + [_num(v.get("total_virupas")), _num(v.get("rupas")),
                       _num(v.get("required_virupas")),
                       c.t("Strong") if v.get("strong") else c.t("Weak")])
    sections = [{"title": c.t("Shadbala (six sources of strength)"), "table": {
        "columns": [c.t("Planet")] + [c.t(label) for _, label in _SHADBALA_PARTS]
                   + [c.t("Total (virupas)"), c.t("Rupas"), c.t("Needed"), c.t("Verdict")],
        "rows": rows}}]
    if d.get("ranking"):
        sections.append({"title": c.t("Strongest to weakest"),
                         "rows": [["%d." % (i + 1), c.planet(p)]
                                  for i, p in enumerate(d["ranking"])]})
    if d.get("system"):
        sections.append({"title": c.t("Method"), "text": c.t(d["system"])})
    return {"sections": sections}


def _ashtakavarga(d: Dict, c: _Ctx) -> Dict:
    """One table the way it is drawn on paper: 12 signs down, the seven
    planets' bindus across, Sarvashtakavarga in the last column."""
    bav = d.get("bav") or {}
    sav = d.get("sav") or {}
    planets = [p for p in PLANETS if isinstance(bav.get(p), dict)]
    rows = [[c.sign(s)] + [str(bav[p].get(s, "")) for p in planets] + [str(sav.get(s, ""))]
            for s in SIGNS]
    totals = d.get("bav_totals") or {}
    rows.append([c.t("Total")] + [str(totals.get(p, "")) for p in planets]
                + [str(d.get("sav_total", ""))])
    return {"sections": [{"title": c.t("Ashtakavarga (bindus per sign)"), "table": {
        "columns": [c.t("Sign")] + [c.planet(p) for p in planets] + [c.t("SAV")],
        "rows": rows}}]}


def _panchanga(d: Dict, c: _Ctx) -> Dict:
    th = d.get("tithi") or {}
    nk = d.get("nakshatra") or {}
    rows = [[c.t("Tithi"), "%s %s" % (c.t(th.get("paksha", "") + " paksha"),
                                     c.term("tithis", th.get("name", "")))],
            [c.t("Weekday"), c.weekday(d.get("vara", ""))],
            [c.t("Nakshatra"), "%s %s" % (c.nak(nk.get("name", "")), nk.get("pada", ""))],
            [c.t("Yoga"), c.term("yogas", (d.get("yoga") or {}).get("name", ""))],
            [c.t("Karana"), c.term("karanas", (d.get("karana") or {}).get("name", ""))]]
    return {"sections": [{"title": c.t("Birth panchanga"), "rows": rows}]}


def _gemstones(d: Dict, c: _Ctx) -> Dict:
    items = []
    for g in d.get("recommended") or []:
        lines = [c.t(g.get("note", ""))] if g.get("note") else []
        lines.append(c.t("Metal") + ": " + c.t(g.get("metal", "")) + " · " + c.t("Finger") + ": " + c.t(g.get("finger", "")))
        lines.append(c.t("Day") + ": " + c.weekday(g.get("day", "")) + " · " + c.t("Weight") + ": " + str(g.get("carats", "")))
        if g.get("mantra"):
            lines.append(c.t("Mantra") + ": " + c.t(g["mantra"]))  # rendered in the user's script
        if g.get("substitutes"):
            lines.append(c.t("Substitutes") + ": " + ", ".join(c.t(x) for x in g["substitutes"]))
        items.append({"title": "%s (%s)" % (c.t(g.get("gem", "")), c.planet(g.get("planet", ""))),
                      "text": "\n".join(lines), "badge": c.t(g.get("role", "")), "tone": "good"})
    sections = [{"title": c.t("Recommended gemstones"), "items": items}]
    avoid = [[c.t(a.get("gem", "")), c.planet(a.get("planet", "")), str(a.get("house", ""))]
             for a in d.get("avoid") or []]
    if avoid:
        sections.append({"title": c.t("Gemstones to avoid"),
                         "table": {"columns": [c.t("Gemstone"), c.t("Planet"), c.t("House")], "rows": avoid}})
    if d.get("note"):
        sections.append({"title": "", "text": c.t(d["note"])})
    return {"sections": sections}


# ---------------- generic fallback (astrologer-grade kinds) ----------------

_SKIP = {"meta", "sign_index", "index", "longitude", "speed", "julian_day", "sign_lord_index"}
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}")


def _humanize(k) -> str:
    return str(k).replace("_", " ").strip().capitalize()


def _val(v, c: _Ctx) -> str:
    if isinstance(v, bool):
        return c.t("Yes") if v else c.t("No")
    if isinstance(v, float):
        return ("%.2f" % v).rstrip("0").rstrip(".")
    if isinstance(v, int):
        return str(v)
    if isinstance(v, str):
        if v in c.n["planets"]:
            return c.planet(v)
        if v in SIGNS:
            return c.sign(v)
        if v in c.n["nakshatras"]:
            return c.nak(v)
        if _ISO.match(v):
            return _date(v)
        return c.t(v) if re.search(r"[A-Za-z]{2}", v) else v
    if isinstance(v, list):
        return ", ".join(_val(x, c) for x in v if not isinstance(x, (dict, list)))
    return str(v)


def _key(k, c: _Ctx) -> str:
    if not isinstance(k, str) or k.isdigit():
        return str(k)
    if k in c.n["planets"]:
        return c.planet(k)
    if k in SIGNS:
        return c.sign(k)
    return c.t(_humanize(k))


def _generic(d: Dict, c: _Ctx, title: str = "") -> List[Dict]:
    sections: List[Dict] = []
    rows = []
    for k, v in d.items():
        if k in _SKIP:
            continue
        if isinstance(v, dict):
            vals = list(v.values())
            if vals and all(isinstance(x, dict) for x in vals):
                cols = [k2 for k2 in vals[0].keys() if k2 not in _SKIP and not isinstance(vals[0][k2], (dict, list))][:6]
                if cols:
                    sections.append({"title": _key(k, c), "table": {
                        "columns": [""] + [_key(x, c) for x in cols],
                        "rows": [[_key(rk, c)] + [_val(rv.get(x, ""), c) for x in cols] for rk, rv in v.items()]}})
                    continue
            if vals and all(not isinstance(x, (dict, list)) for x in vals):
                sections.append({"title": _key(k, c), "rows": [[_key(k2, c), _val(v2, c)] for k2, v2 in v.items() if k2 not in _SKIP]})
                continue
            sections.extend(_generic(v, c, title=_key(k, c)))
        elif isinstance(v, list) and v and isinstance(v[0], dict):
            cols = [k2 for k2 in v[0].keys() if k2 not in _SKIP and not isinstance(v[0][k2], (dict, list))][:6]
            sections.append({"title": _key(k, c), "table": {
                "columns": [_key(x, c) for x in cols],
                "rows": [[_val(item.get(x, ""), c) for x in cols] for item in v[:40]]}})
        else:
            rows.append([_key(k, c), _val(v, c)])
    if rows:
        sections.insert(0, {"title": title, "rows": rows})
    return sections


_BUILDERS = {"rasi": _rasi, "navamsa": _varga, "bhava": _bhava, "dashas": _dashas, "yogas": _yogas,
             "doshas": _doshas, "panchanga": _panchanga, "gemstones": _gemstones,
             "kp": _kp, "shadbala": _shadbala, "ashtakavarga": _ashtakavarga}


def _build_once(kind: str, division: Optional[str], data: Dict, c: _Ctx) -> Dict:
    try:
        if kind == "varga" and division == "all":
            return _all_vargas(data, c)
        if kind == "varga":
            return _varga(data, c)
        if kind in _BUILDERS:
            return _BUILDERS[kind](data, c)
        view = {"sections": _generic(data, c)}
        if kind == "varshphal" and data.get("varsha_lagna"):
            view["chart"] = _chart(data["varsha_lagna"], data.get("planets") or {})
        return view
    except Exception:  # never fail the screen: fall back to the generic view
        log.exception("view %s failed; using the generic view", kind)
        return {"sections": _generic(data, c)}


def build(kind: str, division: Optional[str], data: Dict, lang: str) -> Dict:
    first = _Ctx(lang)
    view = _build_once(kind, division, data, first)
    if lang == "en" or not first.seen:
        return view
    from .translate import translate_many
    uniq = list(dict.fromkeys(first.seen))
    tr = dict(zip(uniq, translate_many(uniq, lang)))
    return _build_once(kind, division, data, _Ctx(lang, tr))


# ---------------- tools: matching, muhurta, birth-time ----------------

def _two_pass(builder, res: Dict, lang: str) -> Dict:
    first = _Ctx(lang)
    view = builder(res, first)
    if lang == "en" or not first.seen:
        return view
    from .translate import translate_many
    uniq = list(dict.fromkeys(first.seen))
    return builder(res, _Ctx(lang, dict(zip(uniq, translate_many(uniq, lang)))))


def _matching(r: Dict, c: _Ctx) -> Dict:
    gm = r.get("guna_milan") or {}
    total, mx = gm.get("total", 0), gm.get("max", 36)
    verdict = (r.get("verdict") or {})
    tone = {"excellent": "good", "very_good": "good", "acceptable": "warn"}.get(verdict.get("key", ""), "bad")
    head = {"title": "%s: %s / %s" % (c.t("Guna milan"), ("%g" % total), mx), "items": [
        {"title": verdict.get("text", ""), "text": "\n".join(r.get("cautions") or []),
         "badge": "%s / %s" % (("%g" % total), mx), "tone": tone}]}
    people = []
    for side in ("groom", "bride"):
        p = r.get(side) or {}
        people.append([p.get("name", ""), p.get("moon_sign_local", ""),
                       "%s %s" % (p.get("nakshatra_local", ""), p.get("pada", "")),
                       c.t("Yes") if p.get("manglik") else c.t("No")])
    sections = [head,
                {"title": c.t("Birth details"), "table": {
                    "columns": [c.t("Name"), c.t("Moon sign"), c.t("Nakshatra"), c.t("Kuja dosha")],
                    "rows": people}},
                {"title": c.t("Ashtakoota (8 kootas)"), "table": {
                    "columns": [c.t("Koota"), c.t("Points")],
                    "rows": [[k.get("name", ""), "%g / %g" % (k.get("points", 0), k.get("max", 0))]
                             for k in gm.get("kootas") or []]}}]
    dk = r.get("dashakoot") or {}
    if dk.get("poruthams"):
        sections.append({"title": "%s (%s / %s)" % (c.t("Dasha porutham"), dk.get("passed", 0), dk.get("max", 10)),
                         "items": [{"title": p.get("name", ""), "text": c.t(p.get("note", "")) if p.get("note") else "",
                                    "badge": c.t("Matches") if p.get("ok") else c.t("Does not match"),
                                    "tone": "good" if p.get("ok") else "bad"}
                                   for p in dk["poruthams"]]})
    if (r.get("manglik") or {}).get("text"):
        sections.append({"title": c.t("Kuja dosha"), "text": r["manglik"]["text"]})
    if r.get("disclaimer"):
        sections.append({"title": "", "text": r["disclaimer"]})
    return {"sections": sections}


def _muhurta(r: Dict, c: _Ctx) -> Dict:
    items = []
    for w in r.get("windows") or []:
        items.append({"title": "%s. %s" % (w.get("rank", ""), _date(w["date"])),
                      "text": "\n".join(filter(None, [w.get("window_text")] + [
                          (x.get("text") if isinstance(x, dict) else str(x)) for x in (w.get("reasons") or [])])),
                      "badge": "%s %s" % (c.t("Score"), w.get("score", "")), "tone": "good"})
    sections = [{"title": r.get("event_name", ""),
                 "items": items} if items else
                {"title": r.get("event_name", ""), "text": c.t("No suitable days in this range. Try a longer range.")}]
    if r.get("note"):
        sections.append({"title": "", "text": r["note"]})
    return {"sections": sections}


def _rectify(r: Dict, c: _Ctx) -> Dict:
    items = [{"title": "%s  (%s – %s)" % (x.get("time", ""), x.get("from", ""), x.get("to", "")),
              "text": "\n".join(x.get("reasons") or []),
              "badge": "%s · %s%%" % (x.get("lagna_local", ""), x.get("score", "")),
              "tone": "good" if i == 0 else ""}
             for i, x in enumerate(r.get("candidates") or [])]
    sections = [{"title": c.t("Most likely birth times"), "items": items}]
    if r.get("disclaimer"):
        sections.append({"title": "", "text": r["disclaimer"]})
    return {"sections": sections}


def tool_view(kind: str, res: Dict, lang: str) -> Dict:
    builder = {"matching": _matching, "muhurta": _muhurta, "rectify": _rectify}[kind]
    try:
        return _two_pass(builder, res, lang)
    except Exception:
        log.exception("tool view %s failed; using the generic view", kind)
        return _two_pass(lambda r, c: {"sections": _generic(r, c)}, res, lang)
