"""Birth-time rectification helper (heuristic estimate, no LLM).

For each candidate time in the window, build the lagna and the Vimshottari
tree, then score how well the maha/antar/pratyantar lords running at each
life event connect to the houses and karakas of that event (whole-sign
occupation or lordship from the candidate lagna), plus a small bonus when
transiting Jupiter/Saturn occupy or aspect the event's main house.
"""

from datetime import date, datetime, timezone
from typing import Dict, List, Optional

from .common import birth_dict, fmt_date, invalid, japi, jc, planet, sign, t

EVENT_RULES = {
    "marriage": ([7, 2, 11], ["Venus", "Jupiter"]),
    "child_birth": ([5, 2, 11], ["Jupiter"]),
    "career_start": ([10, 6, 11, 2], ["Sun", "Saturn", "Mercury"]),
    "promotion": ([10, 11, 2], ["Sun", "Jupiter"]),
    "job_change": ([10, 6, 3, 12], ["Saturn", "Rahu"]),
    "business_start": ([7, 10, 11], ["Mercury"]),
    "education": ([4, 5, 9], ["Mercury", "Jupiter"]),
    "property": ([4, 11, 2], ["Mars"]),
    "vehicle": ([4, 11], ["Venus"]),
    "relocation": ([12, 9, 3], ["Rahu"]),
    "health": ([6, 8, 12], ["Saturn", "Mars"]),
    "parent_loss": ([8, 12, 3, 10], ["Saturn"]),
    "accident": ([6, 8, 12], ["Mars", "Rahu"]),
    "other": ([1], []),
}
LEVEL_WEIGHTS = (1.0, 2.0, 3.0)  # maha, antar, pratyantar
_ASPECTS = {"Jupiter": {1, 5, 7, 9}, "Saturn": {1, 3, 7, 10}}
MAX_CANDIDATES = 180


def _find(periods: List[Dict], at: str) -> Optional[Dict]:
    for p in periods:
        if p["start"] <= at < p["end"]:
            return p
    return None


def _transit_signs(day: date) -> Dict[str, int]:
    from jyotish import ephemeris
    dt = datetime(day.year, day.month, day.day, 6, 30, tzinfo=timezone.utc)
    pos = ephemeris.planet_positions(ephemeris.julian_day(dt), "lahiri")
    return {p: int(pos[p]["longitude"] // 30) for p in ("Jupiter", "Saturn")}


def _signif(lord: str, houses: List[int], karakas: List[str], lagna: int,
            signs: Dict[str, int]) -> float:
    occ = (signs[lord] - lagna) % 12 + 1
    owned = {(s - lagna) % 12 + 1 for s in range(12) if jc.SIGN_LORDS[s] == lord}
    if occ in houses or owned & set(houses):
        return 1.0
    return 0.5 if lord in karakas else 0.0


def rectify(profile: Dict, events: List[Dict], lang: str,
            window_minutes: Optional[int] = None, step_minutes: Optional[int] = None,
            from_time: Optional[str] = None, to_time: Optional[str] = None) -> Dict:
    from jyotish import dasha as jdasha, ephemeris

    if not events:
        raise invalid("Give at least one life event with its date")
    parsed = []
    for ev in events[:20]:
        try:
            d = date.fromisoformat(str(ev.get("date", ""))[:10])
        except ValueError:
            raise invalid("Each event needs a date in YYYY-MM-DD")
        typ = ev.get("type") or "other"
        if typ not in EVENT_RULES:
            raise invalid("event type must be one of: %s" % ", ".join(EVENT_RULES))
        parsed.append({"date": d, "type": typ})

    base = birth_dict(profile)
    bdate = date(base["year"], base["month"], base["day"])
    if any(e["date"] <= bdate for e in parsed):
        raise invalid("Events must be after the birth date")

    # Candidate window in local minutes-of-day.
    if from_time and to_time:
        lo = int(from_time[:2]) * 60 + int(from_time[3:5])
        hi = int(to_time[:2]) * 60 + int(to_time[3:5])
    elif profile.get("time_known", True):
        w = int(window_minutes or 60)
        mid = base["hour"] * 60 + base["minute"]
        lo, hi = mid - w, mid + w
    else:
        lo, hi = 0, 24 * 60 - 1
    lo, hi = max(0, lo), min(24 * 60 - 1, hi)
    if hi <= lo:
        raise invalid("Empty time window")
    step = int(step_minutes or max(2, -(-(hi - lo) // MAX_CANDIDATES)))
    step = max(step, -(-(hi - lo) // MAX_CANDIDATES), 1)

    transits = {e["date"]: _transit_signs(e["date"]) for e in parsed}
    max_score = sum(sum(LEVEL_WEIGHTS) + 2 for _ in parsed)

    cands = []
    m = lo
    while m <= hi:
        b = dict(base, hour=m // 60, minute=m % 60)
        bd = japi.BirthData.from_dict(b)
        pos = ephemeris.planet_positions(bd.jd, bd.ayanamsa)
        signs = {k: int(v["longitude"] // 30) for k, v in pos.items()}
        lagna = int(ephemeris.ascendant(bd.jd, bd.latitude, bd.longitude, bd.ayanamsa) // 30)
        tree = jdasha.vimshottari(pos["Moon"]["longitude"], bd.utc, levels=3)
        score, detail = 0.0, []
        for e in parsed:
            houses, karakas = EVENT_RULES[e["type"]]
            at = datetime(e["date"].year, e["date"].month, e["date"].day, 12,
                          tzinfo=timezone.utc).isoformat()
            maha = _find(tree["mahadashas"], at)
            antar = _find(maha.get("antardashas", []), at) if maha else None
            praty = _find(antar.get("sub_periods", []), at) if antar else None
            lords = [x["lord"] if x else None for x in (maha, antar, praty)]
            s = 0.0
            for w, lord in zip(LEVEL_WEIGHTS, lords):
                if lord:
                    s += w * _signif(lord, houses, karakas, lagna, signs)
            tr = transits[e["date"]]
            main_house_sign = (lagna + houses[0] - 1) % 12
            hit = False
            for p_name, asp in _ASPECTS.items():
                if (main_house_sign - tr[p_name]) % 12 + 1 in asp:
                    s += 1.0
                    hit = True
            score += s
            detail.append({"event": e["type"], "date": e["date"].isoformat(),
                           "maha": lords[0], "antar": lords[1], "pratyantar": lords[2],
                           "transit_hit": hit, "score": round(s, 2)})
        cands.append({"minute": m, "lagna": lagna, "score": score, "detail": detail})
        m += step

    # Merge neighbouring candidates with the same lagna and score into ranges.
    ranges = []
    for c in cands:
        if ranges and ranges[-1]["lagna"] == c["lagna"] and abs(ranges[-1]["score"] - c["score"]) < 1e-9 \
                and c["minute"] - ranges[-1]["end"] <= step:
            ranges[-1]["end"] = c["minute"]
        else:
            ranges.append({"start": c["minute"], "end": c["minute"], "lagna": c["lagna"],
                           "score": c["score"], "detail": c["detail"]})
    ranges.sort(key=lambda r: (-r["score"], r["start"]))

    out = []
    for r in ranges[:5]:
        mid = (r["start"] + r["end"]) // 2
        reasons = [t(lang, "rectify.reason_lagna", sign=sign(lang, jc.SIGNS[r["lagna"]]))]
        for d in r["detail"]:
            ev_name = t(lang, "event_types." + d["event"])
            if d["score"] >= 3:
                reasons.append(t(lang, "rectify.reason_dasha", event=ev_name,
                                 date=fmt_date(d["date"]), maha=planet(lang, d["maha"]),
                                 antar=planet(lang, d["antar"]),
                                 pratyantar=planet(lang, d["pratyantar"])))
            if d["transit_hit"]:
                reasons.append(t(lang, "rectify.reason_transit", event=ev_name,
                                 date=fmt_date(d["date"])))
        out.append({
            "time": "%02d:%02d" % (mid // 60, mid % 60),
            "from": "%02d:%02d" % (r["start"] // 60, r["start"] % 60),
            "to": "%02d:%02d" % (r["end"] // 60, r["end"] % 60),
            "lagna": jc.SIGNS[r["lagna"]], "lagna_local": sign(lang, jc.SIGNS[r["lagna"]]),
            "score": round(100.0 * r["score"] / max_score, 1),
            "events": r["detail"], "reasons": reasons,
        })
    return {"profile_id": profile.get("id"), "estimate": True,
            "window": {"from": "%02d:%02d" % (lo // 60, lo % 60),
                       "to": "%02d:%02d" % (hi // 60, hi % 60), "step_minutes": step},
            "candidates_checked": len(cands), "candidates": out,
            "disclaimer": t(lang, "rectify.disclaimer")}
