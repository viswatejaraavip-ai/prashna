"""Muhurta finder: rank days in a range for an event using classical
panchanga rules (nakshatra, vara, tithi, paksha, yoga, karana), personal
tarabala/chandrabala when a profile is given, and pick the best daytime
window clear of Rahu kalam / Yamagandam / Gulika."""

from datetime import date, timedelta
from typing import Dict, List, Optional

from . import daily
from .common import invalid, jc, nak, t, weekday

EVENTS = ("marriage", "griha_pravesam", "vehicle", "business", "travel", "naming")
MAX_DAYS = 180

_GOOD_NAK = {
    "marriage": ["Rohini", "Mrigashira", "Magha", "Uttara Phalguni", "Hasta", "Swati",
                 "Anuradha", "Mula", "Uttara Ashadha", "Uttara Bhadrapada", "Revati"],
    "griha_pravesam": ["Rohini", "Mrigashira", "Uttara Phalguni", "Chitra", "Anuradha",
                       "Uttara Ashadha", "Dhanishta", "Shatabhisha", "Uttara Bhadrapada", "Revati"],
    "vehicle": ["Ashwini", "Mrigashira", "Punarvasu", "Pushya", "Hasta", "Chitra", "Swati",
                "Anuradha", "Shravana", "Dhanishta", "Shatabhisha", "Revati"],
    "business": ["Ashwini", "Rohini", "Pushya", "Uttara Phalguni", "Hasta", "Chitra",
                 "Anuradha", "Uttara Ashadha", "Shravana", "Uttara Bhadrapada", "Revati"],
    "travel": ["Ashwini", "Mrigashira", "Punarvasu", "Pushya", "Hasta", "Anuradha",
               "Shravana", "Dhanishta", "Revati"],
    "naming": ["Ashwini", "Rohini", "Mrigashira", "Punarvasu", "Pushya", "Uttara Phalguni",
               "Hasta", "Chitra", "Swati", "Anuradha", "Uttara Ashadha", "Shravana",
               "Dhanishta", "Shatabhisha", "Uttara Bhadrapada", "Revati"],
}
# Fierce/sharp stars avoided for auspicious beginnings.
_BAD_NAK = {"Bharani", "Krittika", "Ardra", "Ashlesha", "Jyeshtha",
            "Purva Phalguni", "Purva Ashadha", "Purva Bhadrapada"}
_GOOD_DAYS = {
    "marriage": {"Monday", "Wednesday", "Thursday", "Friday"},
    "griha_pravesam": {"Monday", "Wednesday", "Thursday", "Friday"},
    "vehicle": {"Monday", "Wednesday", "Thursday", "Friday"},
    "business": {"Wednesday", "Thursday", "Friday"},
    "travel": {"Monday", "Wednesday", "Thursday", "Friday"},
    "naming": {"Monday", "Wednesday", "Thursday", "Friday"},
}
_BAD_DAYS = {"Tuesday", "Saturday"}
_GOOD_TITHI = {2, 3, 5, 7, 10, 11, 13}
_RIKTA = {4, 9, 14}
_BAD_YOGAS = {"Vishkambha", "Atiganda", "Shula", "Ganda", "Vyaghata", "Vajra",
              "Vyatipata", "Parigha", "Vaidhriti"}


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _hhmm(mins: int) -> str:
    return "%02d:%02d" % (mins // 60, mins % 60)


def best_window(timings: Dict) -> Optional[Dict]:
    """Longest daytime stretch free of Rahu/Yamagandam/Gulika (Abhijit
    preferred when it is clear)."""
    if not timings or not timings.get("sunrise") or not timings.get("sunset"):
        return None
    rise, sset = _minutes(timings["sunrise"]), _minutes(timings["sunset"])
    bad = sorted((_minutes(w["start"]), _minutes(w["end"]))
                 for w in timings["inauspicious"].values())
    ab = timings["auspicious"].get("abhijit_muhurta")
    if ab:
        a0, a1 = _minutes(ab["start"]), _minutes(ab["end"])
        if all(a1 <= b0 or a0 >= b1 for b0, b1 in bad):
            return {"start": ab["start"], "end": ab["end"], "abhijit": True}
    free, cur = [], rise
    for b0, b1 in bad:
        if b0 > cur:
            free.append((cur, min(b0, sset)))
        cur = max(cur, b1)
    if cur < sset:
        free.append((cur, sset))
    if not free:
        return None
    s, e = max(free, key=lambda w: w[1] - w[0])
    return {"start": _hhmm(s), "end": _hhmm(e), "abhijit": False}


def evaluate_day(day: date, event: str, lat: float, lon: float, tz: str, lang: str,
                 person: Optional[Dict] = None) -> Dict:
    p = daily.day_panchanga(day, lat, lon, tz, lang)
    timings = p.pop("_raw_timings", None)
    ev = t(lang, "events." + event)
    score = 0.0
    reasons: List[Dict] = []
    blockers: List[str] = []

    def add(delta: float, key: str, **kw):
        nonlocal score
        score += delta
        reasons.append({"key": key, "good": delta > 0, "text": t(lang, "muhurta." + key, **kw)})

    n_en = p["nakshatra"]["name"]
    if n_en in _GOOD_NAK[event]:
        add(3, "nak_good", nakshatra=nak(lang, n_en), event=ev)
    elif n_en in _BAD_NAK:
        add(-3, "nak_bad", nakshatra=nak(lang, n_en), event=ev)
    vara = p["vara"]["name"]
    if vara in _GOOD_DAYS[event]:
        add(2, "weekday_good", weekday=weekday(lang, vara), event=ev)
    elif vara in _BAD_DAYS:
        add(-2, "weekday_bad", weekday=weekday(lang, vara), event=ev)
    tnum = p["tithi"]["number"]
    tin = tnum if tnum <= 15 else tnum - 15
    tname = p["tithi"]["local"]
    if tnum == 30:
        add(-5, "amavasya")
        blockers.append("amavasya")
    elif tin in _RIKTA:
        add(-3, "tithi_rikta", tithi=tname)
        blockers.append("rikta")
    elif tin in _GOOD_TITHI or tnum == 15:
        add(2, "tithi_good", tithi=tname)
    if tnum <= 15 and event in ("marriage", "griha_pravesam", "naming", "business"):
        add(1, "shukla")
    if p["karana"]["name"] == "Vishti":
        add(-3, "vishti")
        blockers.append("vishti")
    y = p["yoga"]["name"]
    if y in _BAD_YOGAS:
        add(-2, "yoga_bad", yoga=p["yoga"]["local"])
    elif y in ("Siddhi", "Siddha", "Shubha", "Saubhagya", "Shobhana", "Sukarma",
               "Dhruva", "Harshana", "Amrita", "Priti", "Ayushman", "Vriddhi"):
        add(1, "yoga_good", yoga=p["yoga"]["local"])

    if person and person.get("derived"):
        dv = person["derived"]
        t_nak = jc.NAKSHATRAS.index(n_en)
        t_sign = jc.SIGNS.index(p["moon_sign"]["name"])
        tara = daily.tara_of(int(dv["nakshatra"]), t_nak)
        house = daily.chandra_house(int(dv["moon_sign"]), t_sign)
        who = person.get("name", "")
        if daily.tara_score(tara) > 0:
            add(2, "tara_good", name=who)
        elif daily.tara_score(tara) < 0:
            add(-3, "tara_bad", name=who)
            if tara == 7:
                blockers.append("naidhana_tara")
        if daily.chandra_score(house) > 0:
            add(1, "chandra_good", name=who)
        elif daily.chandra_score(house) < 0:
            add(-2, "chandra_bad", name=who)
            if house == 8:
                blockers.append("chandrashtama")

    window = best_window(timings)
    return {"date": day.isoformat(), "score": score, "blocked": bool(blockers),
            "blockers": blockers, "reasons": reasons, "panchanga": p,
            "window": window,
            "window_text": (t(lang, "muhurta.best_time", start=window["start"], end=window["end"])
                            if window else None)}


def find(event: str, start: date, end: date, lat: float, lon: float, tz: str,
         lang: str, person: Optional[Dict] = None, limit: int = 10) -> Dict:
    if event not in EVENTS:
        raise invalid("event must be one of: %s" % ", ".join(EVENTS))
    if end < start:
        raise invalid("'to' must be on or after 'from'")
    if (end - start).days + 1 > MAX_DAYS:
        raise invalid("Date range is limited to %d days" % MAX_DAYS)
    days = []
    d = start
    while d <= end:
        days.append(evaluate_day(d, event, lat, lon, tz, lang, person))
        d += timedelta(days=1)
    ranked = sorted([x for x in days if not x["blocked"] and x["score"] > 0],
                    key=lambda x: (-x["score"], x["date"]))[:max(1, min(int(limit), 50))]
    for i, x in enumerate(ranked):
        x["rank"] = i + 1
    return {"event": event, "event_name": t(lang, "events." + event),
            "from": start.isoformat(), "to": end.isoformat(),
            "days_checked": len(days), "windows": ranked,
            "note": t(lang, "muhurta.note")}
