"""Upcoming transit alerts for a profile (default next 180 days):
Sade Sati / Dhaiya phase changes, Vimshottari maha/antar changes, eclipses
(flagged when they fall in the natal Moon sign or lagna), and Jupiter/Saturn
sign changes judged from the natal Moon."""

from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import swisseph as swe

from .common import (birth_dict, fmt_date, japi, jc, ordinal, planet, sign, t)

IST = timezone(timedelta(hours=5, minutes=30))
JUPITER_GOOD = {2, 5, 7, 9, 11}
SATURN_GOOD = {3, 6, 11}


def _jd(dt: datetime) -> float:
    from jyotish import ephemeris
    return ephemeris.julian_day(dt.astimezone(timezone.utc))


def _dt(jd: float) -> datetime:
    y, m, d, h = swe.revjul(jd)
    return (datetime(y, m, d, tzinfo=timezone.utc) + timedelta(hours=h))


def _lon(jd: float, body: int) -> float:
    from jyotish import ephemeris
    ephemeris.set_ayanamsa("lahiri")
    vals, _ = swe.calc_ut(jd, body, ephemeris.SIDEREAL_FLAGS)
    return vals[0] % 360.0


def ingresses(body: int, start: datetime, end: datetime, step_days: float = 2.0) -> List[Dict]:
    """Sign changes of a slow planet between start and end (UTC)."""
    out = []
    jd, jd_end = _jd(start), _jd(end)
    sign_now = int(_lon(jd, body) // 30)
    while jd < jd_end:
        jd2 = min(jd + step_days, jd_end)
        s2 = int(_lon(jd2, body) // 30)
        if s2 != sign_now:
            lo, hi = jd, jd2
            for _ in range(30):
                mid = (lo + hi) / 2
                if int(_lon(mid, body) // 30) == sign_now:
                    lo = mid
                else:
                    hi = mid
            out.append({"when": _dt(hi), "from": sign_now, "to": s2})
            sign_now = s2
        jd = jd2
    return out


def eclipses(start: datetime, end: datetime) -> List[Dict]:
    out = []
    jd_end = _jd(end)
    for kind in ("solar", "lunar"):
        jd = _jd(start)
        for _ in range(12):
            try:
                if kind == "solar":
                    res = swe.sol_eclipse_when_glob(jd, swe.FLG_MOSEPH)
                else:
                    res = swe.lun_eclipse_when(jd, swe.FLG_MOSEPH)
            except Exception:
                break
            tret = res[1]
            jmax = tret[0]
            if jmax <= 0 or jmax > jd_end:
                break
            body = swe.SUN if kind == "solar" else swe.MOON
            lon = _lon(jmax, body)
            out.append({"kind": kind, "when": _dt(jmax), "sign": int(lon // 30),
                        "nakshatra": int(lon / jc.NAKSHATRA_SPAN) % 27})
            jd = jmax + 10
    out.sort(key=lambda e: e["when"])
    return out


_GLOBAL: Dict[Tuple[str, int], Dict] = {}


def global_events(start_day: date, days: int) -> Dict:
    """Saturn/Jupiter ingresses + eclipses; the same for everyone, memoised."""
    key = (start_day.isoformat(), days)
    if key not in _GLOBAL:
        start = datetime.combine(start_day, datetime.min.time(), timezone.utc)
        end = start + timedelta(days=days)
        _GLOBAL.clear()
        _GLOBAL[key] = {
            "saturn_sign_now": int(_lon(_jd(start), swe.SATURN) // 30),
            "saturn": ingresses(swe.SATURN, start, end),
            "jupiter": ingresses(swe.JUPITER, start, end, 1.0),
            "eclipses": eclipses(start, end),
        }
    return _GLOBAL[key]


def _ist_date(dt: datetime) -> date:
    return dt.astimezone(IST).date()


def _mk(kind: str, when: datetime, today: date, title_key: str, text: str,
        lang: str, ident: str, data: Dict) -> Dict:
    d = _ist_date(when)
    return {"id": ident, "type": kind, "date": d.isoformat(),
            "days_away": (d - today).days,
            "title": t(lang, "alerts." + title_key), "text": text, "data": data}


def compute(profile: Dict, lang: str, days: int = 180,
            today: Optional[date] = None) -> List[Dict]:
    today = today or datetime.now(IST).date()
    d = profile.get("derived") or {}
    from .common import derive
    if not d:
        d = derive(profile)
    moon_sign = int(d["moon_sign"])
    lagna_sign = int(d["lagna_sign"])
    time_known = profile.get("time_known", True)
    g = global_events(today, days)
    alerts: List[Dict] = []

    # Saturn: Sade Sati / Dhaiya phases, else a generic transit line.
    for ing in g["saturn"]:
        h_new = (ing["to"] - moon_sign) % 12 + 1
        h_old = (ing["from"] - moon_sign) % 12 + 1
        sname = sign(lang, jc.SIGNS[ing["to"]])
        dstr = fmt_date(_ist_date(ing["when"]))
        key, title = None, "title_sade_sati"
        if h_new == 12 and h_old == 11:
            key = "sade_sati_start"
        elif h_new == 1 and h_old == 12:
            key = "sade_sati_peak"
        elif h_new == 2 and h_old == 1:
            key = "sade_sati_final"
        elif h_new == 3 and h_old == 2:
            key = "sade_sati_end"
        elif h_new == 4 and h_old == 3:
            key = "dhaiya_4"
        elif h_new == 8 and h_old == 7:
            key = "dhaiya_8"
        if key:
            text = t(lang, "alerts." + key, date=dstr, sign=sname)
            kind = "sade_sati" if key.startswith("sade") else "dhaiya"
        else:
            key = "saturn_good" if h_new in SATURN_GOOD else "saturn_hard"
            text = t(lang, "alerts." + key, date=dstr, sign=sname, ord=ordinal(lang, h_new))
            kind, title = "saturn_transit", "title_transit"
        alerts.append(_mk(kind, ing["when"], today, title, text, lang,
                          "saturn_%s_%s" % (_ist_date(ing["when"]).isoformat(), jc.SIGNS[ing["to"]]),
                          {"planet": "Saturn", "sign": jc.SIGNS[ing["to"]],
                           "house_from_moon": h_new, "phase": key}))

    for ing in g["jupiter"]:
        h_new = (ing["to"] - moon_sign) % 12 + 1
        key = "jupiter_good" if h_new in JUPITER_GOOD else "jupiter_hard"
        text = t(lang, "alerts." + key, date=fmt_date(_ist_date(ing["when"])),
                 sign=sign(lang, jc.SIGNS[ing["to"]]), ord=ordinal(lang, h_new))
        alerts.append(_mk("jupiter_transit", ing["when"], today, "title_transit", text, lang,
                          "jupiter_%s_%s" % (_ist_date(ing["when"]).isoformat(), jc.SIGNS[ing["to"]]),
                          {"planet": "Jupiter", "sign": jc.SIGNS[ing["to"]],
                           "house_from_moon": h_new}))

    for ec in g["eclipses"]:
        touch = ""
        touches = []
        if ec["sign"] == moon_sign:
            touch = t(lang, "alerts.eclipse_touch_moon")
            touches.append("moon")
        elif time_known and ec["sign"] == lagna_sign:
            touch = t(lang, "alerts.eclipse_touch_lagna")
            touches.append("lagna")
        text = t(lang, "alerts.eclipse_" + ec["kind"], date=fmt_date(_ist_date(ec["when"])),
                 sign=sign(lang, jc.SIGNS[ec["sign"]]), touch=touch)
        alerts.append(_mk("eclipse", ec["when"], today, "title_eclipse", text, lang,
                          "eclipse_%s_%s" % (ec["kind"], _ist_date(ec["when"]).isoformat()),
                          {"kind": ec["kind"], "sign": jc.SIGNS[ec["sign"]],
                           "nakshatra": jc.NAKSHATRAS[ec["nakshatra"]],
                           "touches": touches, "personal": bool(touches)}))

    # Vimshottari changes inside the window.
    birth = birth_dict(profile)
    tree = japi.dasha_periods(birth, 2, "vimshottari")
    start = datetime.combine(today, datetime.min.time(), IST)
    end = start + timedelta(days=days)
    prev_maha = None
    for maha in tree["mahadashas"]:
        ms = datetime.fromisoformat(maha["start"])
        if start <= ms < end and prev_maha:
            text = t(lang, "alerts.maha_change", lord=planet(lang, maha["lord"]),
                     prev=planet(lang, prev_maha), date=fmt_date(_ist_date(ms)))
            alerts.append(_mk("maha_change", ms, today, "title_dasha", text, lang,
                              "maha_%s_%s" % (_ist_date(ms).isoformat(), maha["lord"]),
                              {"lord": maha["lord"], "previous": prev_maha}))
        for antar in maha.get("antardashas", []):
            a_s = datetime.fromisoformat(antar["start"])
            if start <= a_s < end and antar["start"] != maha["start"]:
                text = t(lang, "alerts.antar_change", lord=planet(lang, antar["lord"]),
                         maha=planet(lang, maha["lord"]), date=fmt_date(_ist_date(a_s)))
                alerts.append(_mk("antar_change", a_s, today, "title_dasha", text, lang,
                                  "antar_%s_%s" % (_ist_date(a_s).isoformat(), antar["lord"]),
                                  {"maha": maha["lord"], "lord": antar["lord"]}))
        prev_maha = maha["lord"]

    alerts = [a for a in alerts if 0 <= a["days_away"] <= days]
    alerts.sort(key=lambda a: (a["date"], a["type"]))
    return alerts
