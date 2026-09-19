"""Daily panchanga + inauspicious periods for a place, and the personal day
forecast from tarabala (transit Moon star vs birth star) and chandrabala
(transit Moon sign vs natal Moon sign). Template text, cached per
date/lang/natal Moon rasi in daily_content."""

from datetime import date, datetime, time as dtime, timedelta, timezone
from typing import Dict, Optional

from .. import store
from .common import fmt_date, japi, jc, names, sign, nak, t, weekday

GOOD_TARAS = {2, 4, 6, 8, 9}
BAD_TARAS = {3, 5, 7}
GOOD_CHANDRA = {1, 3, 6, 7, 10, 11}
BAD_CHANDRA = {4, 8, 12}
IST = timezone(timedelta(hours=5, minutes=30))


def tara_of(natal_nak: int, transit_nak: int) -> int:
    """1..9: Janma, Sampat, Vipat, Kshema, Pratyak, Sadhana, Naidhana, Mitra, Parama mitra."""
    count = (transit_nak - natal_nak) % 27  # 0-based count from birth star
    return count % 9 + 1


def chandra_house(natal_sign: int, transit_sign: int) -> int:
    return (transit_sign - natal_sign) % 12 + 1


def tara_score(tara: int) -> int:
    return 1 if tara in GOOD_TARAS else -1 if tara in BAD_TARAS else 0


def chandra_score(house: int) -> int:
    return 1 if house in GOOD_CHANDRA else -1 if house in BAD_CHANDRA else 0


def rating_of(tara: int, house: int) -> str:
    s = tara_score(tara) + chandra_score(house)
    if house == 8 or tara == 7:
        s = min(s, -1)  # Chandrashtama / Naidhana: always go gently
    return "good" if s >= 1 else "careful" if s <= -1 else "mixed"


def moon_at(dt_utc: datetime) -> float:
    from jyotish import ephemeris
    return ephemeris.planet_positions(ephemeris.julian_day(dt_utc), "lahiri")["Moon"]["longitude"]


def _forecast_moment(day: date) -> datetime:
    """06:00 IST on `day`: the Moon used for everyone's morning forecast."""
    return datetime.combine(day, dtime(6, 0), IST).astimezone(timezone.utc)


def build_forecast(day: date, lang: str, moon_rasi: int) -> Dict:
    """Forecast texts for every birth star inside one natal Moon rasi."""
    moon = moon_at(_forecast_moment(day))
    t_sign = int(moon // 30)
    t_nak = int(moon / jc.NAKSHATRA_SPAN) % 27
    house = chandra_house(moon_rasi, t_sign)
    first = int(moon_rasi * 30 / jc.NAKSHATRA_SPAN)
    last = int((moon_rasi * 30 + 29.9999) / jc.NAKSHATRA_SPAN)
    by_nak = {}
    for n in range(first, last + 1):
        tara = tara_of(n, t_nak)
        rating = rating_of(tara, house)
        by_nak[str(n)] = {
            "rating": rating,
            "rating_text": t(lang, "labels.rating_" + rating),
            "tara": tara, "tara_name": t(lang, "tara_name.%d" % tara),
            "chandra_house": house,
            "lines": [t(lang, "tara.%d" % tara), t(lang, "chandra.%d" % house)],
        }
    return {"date": day.isoformat(), "lang": lang, "moon_rasi": moon_rasi,
            "transit_moon": {"sign": jc.SIGNS[t_sign], "name": sign(lang, jc.SIGNS[t_sign]),
                             "nakshatra": jc.NAKSHATRAS[t_nak],
                             "nakshatra_name": nak(lang, jc.NAKSHATRAS[t_nak])},
            "by_nak": by_nak, "created_at": store.now_iso()}


_MEM: Dict[str, Dict] = {}


def cached_forecast(day: date, lang: str, moon_rasi: int) -> Dict:
    key = "%s_%s_%d" % (day.isoformat(), lang, moon_rasi)
    if key in _MEM:
        return _MEM[key]
    ref = store.fs().collection("daily_content").document(key)
    doc = None
    try:
        snap = ref.get()
        doc = snap.to_dict() if snap.exists else None
    except Exception:
        doc = None
    if not doc:
        doc = build_forecast(day, lang, moon_rasi)
        try:
            ref.set(doc)
        except Exception:
            pass
    if len(_MEM) > 2000:
        _MEM.clear()
    _MEM[key] = doc
    return doc


def personal(day: date, lang: str, derived: Dict, name: str,
             timings: Optional[Dict] = None) -> Dict:
    doc = cached_forecast(day, lang, int(derived["moon_sign"]))
    entry = doc["by_nak"].get(str(int(derived["nakshatra"])))
    if entry is None:  # derived nakshatra outside rasi span (shouldn't happen)
        entry = next(iter(doc["by_nak"].values()))
    lines = list(entry["lines"])
    if timings and timings.get("inauspicious", {}).get("rahu_kalam"):
        rk = timings["inauspicious"]["rahu_kalam"]
        lines.append(t(lang, "daily.rahu_tip", start=rk["start"], end=rk["end"]))
    return {
        "title": t(lang, "daily.title", name=name, date=fmt_date(day)),
        "rating": entry["rating"], "rating_text": entry["rating_text"],
        "tara": entry["tara"], "tara_name": entry["tara_name"],
        "chandra_house": entry["chandra_house"],
        "transit_moon": doc["transit_moon"],
        "lines": lines,
    }


def day_panchanga(day: date, lat: float, lon: float, tz: str, lang: str) -> Dict:
    """Panchanga at local sunrise + day timings, with localized names."""
    from jyotish import ephemeris, panchanga as pmod
    timings = None
    try:
        timings = japi.muhurta_of_day(day.isoformat(), lat, lon, tz)
    except Exception:
        timings = None
    try:
        from zoneinfo import ZoneInfo
        zone = ZoneInfo(tz)
    except Exception:
        zone = IST
    hh, mm = 6, 0
    if timings and timings.get("sunrise"):
        hh, mm = (int(x) for x in timings["sunrise"].split(":"))
    local = datetime.combine(day, dtime(hh, mm), zone)
    utc = local.astimezone(timezone.utc)
    pos = ephemeris.planet_positions(ephemeris.julian_day(utc), "lahiri")
    p = pmod.panchanga(pos["Sun"]["longitude"], pos["Moon"]["longitude"],
                       local.replace(tzinfo=None))
    nm = names(lang)
    tithi = p["tithi"]
    tithi_key = tithi["name"]
    out = {
        "date": day.isoformat(),
        "at": "sunrise",
        "tithi": {"name": tithi_key, "local": nm["tithis"].get(tithi_key, tithi_key),
                  "number": tithi["number"], "paksha": tithi["paksha"],
                  "paksha_local": t(lang, "labels.paksha_" + tithi["paksha"].lower())},
        "vara": {"name": p["vara"], "local": weekday(lang, p["vara"])},
        "nakshatra": {"name": p["nakshatra"]["name"], "local": nak(lang, p["nakshatra"]["name"]),
                      "pada": p["nakshatra"]["pada"]},
        "yoga": {"name": p["yoga"]["name"], "local": nm["yogas"].get(p["yoga"]["name"], p["yoga"]["name"])},
        "karana": {"name": p["karana"]["name"],
                   "local": nm["karanas"].get(p["karana"]["name"], p["karana"]["name"])},
        "moon_sign": {"name": jc.SIGNS[int(pos["Moon"]["longitude"] // 30)],
                      "local": sign(lang, jc.SIGNS[int(pos["Moon"]["longitude"] // 30)])},
    }
    if timings:
        inn = timings["inauspicious"]
        out["timings"] = {
            "sunrise": timings["sunrise"], "sunset": timings["sunset"],
            "moonrise": timings.get("moonrise"), "moonset": timings.get("moonset"),
            "rahu_kalam": inn["rahu_kalam"], "yamagandam": inn["yamaganda"],
            "gulika": inn["gulika_kalam"],
            "abhijit": timings["auspicious"].get("abhijit_muhurta"),
            "brahma_muhurta": timings["auspicious"].get("brahma_muhurta"),
        }
    out["_raw_timings"] = timings
    return out
