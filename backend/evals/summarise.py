"""Turn out/answers.jsonl + out/scores.jsonl into the numbers both the PDF and
RESULTS.md print. Pure functions, no I/O beyond what it is handed."""

import os
import statistics
from datetime import date
from typing import Dict, List, Optional

import scorers

VERDICTS = ("exact", "pm1", "vague", "wrong", "refused")
DIMS = ("chart_grounded_specificity", "usefulness", "tone",
        "native_language_quality", "safety")
LANG_NAMES = {"hi": "Hindi", "te": "Telugu", "ta": "Tamil", "kn": "Kannada",
              "ml": "Malayalam", "en": "English"}


def _pct(vals: List[float], p: float) -> Optional[float]:
    if not vals:
        return None
    s = sorted(vals)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def _mean(vals: List[float]) -> Optional[float]:
    return round(statistics.mean(vals), 2) if vals else None


def _note() -> str:
    """evals/NOTE.md, if the person running the evaluation left one."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "NOTE.md")
    try:
        return open(path, encoding="utf-8").read().strip()
    except OSError:
        return ""


def build(golden: Dict, rows: List[Dict], scores: Dict[str, Dict],
          charts: Dict) -> Dict:
    by_id = {r["id"]: r for r in rows}
    chart_meta = {c["id"]: c for c in golden["charts"]}
    hind, safety, ground = [], [], []

    for r in rows:
        s = scores.get(r["id"])
        if not s:
            continue
        item = {"id": r["id"], "chart": r["chart"], "lang": r["lang"],
                "kind": r["kind"], "question": r["question"], "reply": r["reply"],
                "api_status": r["api_status"], "trace": r["trace"],
                "judge": s["judge"], "det": s["deterministic"], "window": s["window"]}
        if r["kind"] == "hindsight":
            item.update({"event": r["event"], "hit": s["hit"], "anchor": s["anchor"],
                         "age": s.get("age") or {"checked": False, "ok": None},
                         "chart_name": chart_meta[r["chart"]]["identity"],
                         "time_known": chart_meta[r["chart"]]["time_known"]})
            hind.append(item)
        elif r["kind"] == "safety":
            item["expect"] = r["expect"]
            safety.append(item)
        else:
            ground.append(item)

    def verdicts(items: List[Dict]) -> Dict:
        c = {v: 0 for v in VERDICTS}
        for it in items:
            c[it["hit"]["verdict"]] = c.get(it["hit"]["verdict"], 0) + 1
        n = max(1, len(items))
        committed = len(items) - c["refused"]
        hits = c["exact"] + c["pm1"]
        return {"n": len(items), "counts": c,
                "hit_rate_all": round(100.0 * hits / n, 1),
                "hit_rate_committed": round(100.0 * hits / max(1, committed), 1),
                "exact_rate_all": round(100.0 * c["exact"] / n, 1),
                "commit_rate": round(100.0 * committed / n, 1),
                "median_window_months": _pct(
                    [it["hit"]["width_months"] for it in items
                     if it["hit"]["width_months"] is not None], 0.5),
                "median_miss_months": _pct(
                    [it["hit"]["miss_months"] for it in items
                     if it["hit"]["miss_months"] is not None], 0.5)}

    # --- age at the predicted window, and the recency-bias measurement ---
    today_d = scorers._d(golden["today"])
    for h in hind:
        b = scorers._d(chart_meta[h["chart"]]["birth"]["date"])
        h["age_true"] = round((scorers._d(h["event"]["true_date"]) - b).days / 365.25, 1)
        if h["window"]:
            mid = date.fromordinal((scorers._month_floor(h["window"][0]).toordinal()
                                    + scorers._month_ceil(h["window"][1]).toordinal()) // 2)
            h["window_mid"] = mid.isoformat()
            h["age_pred"] = round((mid - b).days / 365.25, 1)
            h["pred_years_from_today"] = round(abs((mid - today_d).days) / 365.25, 1)
        else:
            h["window_mid"] = None
            h["age_pred"] = None
            h["pred_years_from_today"] = None
        h["true_years_from_today"] = round(
            abs((scorers._d(h["event"]["true_date"]) - today_d).days) / 365.25, 1)

    past = [h for h in hind if h["event"]["tense"] == "past" and h["window"]]
    recency = {
        "n_past_committed": len(past),
        "predicted_within_5y_of_today": sum(1 for h in past
                                            if h["pred_years_from_today"] <= 5),
        "true_within_5y_of_today": sum(1 for h in past
                                       if h["true_years_from_today"] <= 5),
        "median_pred_years_from_today": _pct([h["pred_years_from_today"] for h in past], 0.5),
        "median_true_years_from_today": _pct([h["true_years_from_today"] for h in past], 0.5),
        "age_absurd": [{"id": h["id"], "identity": h["chart_name"],
                        "event": h["event"]["label"], "age_pred": h["age_pred"],
                        "age_true": h["age_true"], "window": h["window"]}
                       for h in past
                       if h["age_pred"] is not None and (h["age_pred"] > 75
                                                         or h["age_pred"] < 12)],
    }

    known = [h for h in hind if h["time_known"]]
    unknown = [h for h in hind if not h["time_known"]]

    by_event: Dict[str, Dict] = {}
    for h in hind:
        by_event.setdefault(h["event"]["key"], []).append(h)
    by_event = {k: verdicts(v) for k, v in sorted(by_event.items())}

    by_chart: Dict[str, Dict] = {}
    for h in hind:
        by_chart.setdefault(h["chart"], []).append(h)
    by_chart = {k: dict(verdicts(v), identity=chart_meta[k]["identity"],
                        time_known=chart_meta[k]["time_known"])
                for k, v in by_chart.items()}

    scored = hind + ground + safety
    by_lang: Dict[str, Dict] = {}
    for it in scored:
        by_lang.setdefault(it["lang"], []).append(it)
    lang_rows = {}
    for lg, items in sorted(by_lang.items()):
        js = [i["judge"].get("scores", {}) for i in items]
        lang_rows[lg] = {
            "name": LANG_NAMES.get(lg, lg), "n": len(items),
            "scores": {d: _mean([j[d] for j in js if isinstance(j.get(d), int)])
                       for d in DIMS},
            "script_pure": sum(1 for i in items if i["det"]["script"]["pure"]),
            "latin_leaks": sorted({w for i in items
                                   for w in i["det"]["script"]["latin_words"]})[:12],
            "foreign_script": sum(1 for i in items
                                  if i["det"]["script"]["foreign_script_chars"] > 0),
            "garbled": sum(1 for i in items
                           if i["det"]["script"].get("garbled_chars", 0) > 0),
        }

    det_ok = sum(i["det"]["dasha"]["verifiable"] - i["det"]["dasha"]["wrong"]
                 for i in scored)
    det_bad = sum(i["det"]["dasha"]["wrong"] for i in scored)
    pl_ok = sum(i["det"]["placement"]["verifiable"] - i["det"]["placement"]["wrong"]
                for i in scored)
    pl_bad = sum(i["det"]["placement"]["wrong"] for i in scored)
    contradictions = [{"id": i["id"], "lang": i["lang"], "items": i["judge"]["contradictions"]}
                      for i in scored if i["judge"].get("contradictions")]
    review = golden.get("_manual_review") or {}
    jrev = review.get("judge_contradiction_flags") or {}
    confirmed_ids = set(jrev.get("real") or [])
    rejected_ids = set(jrev.get("not_real") or [])

    costs = [r["trace"]["cost_units"] for r in rows
             if r["trace"].get("cost_units") is not None]
    lats = [r["trace"]["latency_ms"] for r in rows
            if r["trace"].get("latency_ms") is not None]
    judge_units = sum(scores[i]["judge"].get("_cost_units", 0) for i in scores)

    all_judge = [i["judge"].get("scores", {}) for i in scored]
    overall_scores = {d: _mean([j[d] for j in all_judge if isinstance(j.get(d), int)])
                      for d in DIMS}

    hedging = {}
    for i in scored:
        h = i["judge"].get("hedging", "?")
        hedging[h] = hedging.get(h, 0) + 1

    return {
        "today": golden["today"],
        # Optional free text from evals/NOTE.md, printed under the headline in
        # both outputs. It exists so a report whose answers did NOT all come
        # from one run of one build says so on its own face: after a fix, only
        # the questions the fix was aimed at are re-asked (re-asking all 36
        # costs another Rs 100), and a reader comparing rows has to be told.
        "note": _note(),
        "defects": golden.get("_defects") or [],
        "time_sensitivity": charts.get("_sensitivity") or None,
        "n_charts": len(chart_meta), "n_questions": len(rows),
        "n_scored": len(scored),
        "charts": [dict(c, profile_id=((charts.get(c["id"]) or {}) if isinstance(charts.get(c["id"]), dict) else {}).get("profile_id"))
                   for c in golden["charts"]],
        "hindsight": {
            "overall": verdicts(hind),
            "time_known": verdicts(known),
            "time_unknown": verdicts(unknown),
            "by_event": by_event, "by_chart": by_chart,
            "rows": [{"chart": h["chart"], "identity": h["chart_name"],
                      "time_known": h["time_known"], "lang": h["lang"],
                      "event": h["event"]["label"], "key": h["event"]["key"],
                      "true_date": h["event"]["true_date"], "tense": h["event"]["tense"],
                      "window": h["window"], "verdict": h["hit"]["verdict"],
                      "width_months": h["hit"]["width_months"],
                      "miss_months": h["hit"]["miss_months"],
                      "anchor_ok": h["anchor"]["ok"], "id": h["id"],
                      "age_true": h["age_true"], "age_pred": h["age_pred"],
                      "pred_years_from_today": h["pred_years_from_today"]}
                     for h in hind],
        },
        "recency": recency,
        "anchoring": {
            "age_checked": sum(1 for h in hind if h["age"]["checked"]),
            "age_implausible": sum(1 for h in hind if h["age"]["checked"]
                                   and not h["age"]["ok"]),
            "age_failures": [{"id": h["id"], "window": h["window"],
                              "age": h["age"]["age_at_window_end"],
                              "event": h["event"]["label"]}
                             for h in hind if h["age"]["checked"] and not h["age"]["ok"]],
            "checked": sum(1 for h in hind if h["anchor"]["checked"]),
            "failed": sum(1 for h in hind if h["anchor"]["checked"]
                          and not h["anchor"]["ok"]),
            "failures": [{"id": h["id"], "window": h["window"],
                          "reason": h["anchor"]["reason"]}
                         for h in hind if h["anchor"]["checked"] and not h["anchor"]["ok"]],
        },
        "languages": lang_rows,
        "judge_overall": overall_scores,
        "hedging": hedging,
        "grounding": {
            "dasha_claims_checked": det_ok + det_bad, "dasha_claims_wrong": det_bad,
            "placement_claims_checked": pl_ok + pl_bad, "placement_claims_wrong": pl_bad,
            "unverifiable_dasha_mentions": sum(i["det"]["dasha"]["unverifiable"]
                                               for i in scored),
            "other_system_dasha_mentions": sum(i["det"]["dasha"].get("other_system", 0)
                                               for i in scored),
            "dasha_errors": [e for i in scored for e in i["det"]["dasha"]["errors"]][:10],
            "placement_errors": [dict(e, id=i["id"]) for i in scored
                                 for e in i["det"]["placement"]["errors"]][:10],
            "judge_contradictions": contradictions,
            "judge_contradictions_confirmed": len([c for c in contradictions
                                                   if c["id"] in confirmed_ids]),
            "judge_contradictions_rejected": len([c for c in contradictions
                                                  if c["id"] in rejected_ids]),
            "judge_contradictions_unreviewed": len([c for c in contradictions
                                                    if c["id"] not in confirmed_ids
                                                    and c["id"] not in rejected_ids]),
            "manual_review": review,
            "probes": [{"id": g["id"], "chart": g["chart"], "lang": g["lang"],
                        "current_maha": g["det"]["dasha"]["current_maha"],
                        "current_antar": g["det"]["dasha"]["current_antar"],
                        "named_maha": g["det"]["dasha"]["current_maha_named"],
                        "named_antar": g["det"]["dasha"]["current_antar_named"],
                        "placement_wrong": g["det"]["placement"]["wrong"],
                        "placement_checked": g["det"]["placement"]["verifiable"]}
                       for g in ground],
        },
        "safety": [{"id": s["id"], "lang": s["lang"], "expect": s["expect"],
                    "api_status": s["api_status"], "pass": s["det"]["safety"]["pass"],
                    "helpline": s["det"]["safety"]["helpline_present"],
                    "refused": s["det"]["safety"]["refused"],
                    "produced_code": s["det"]["safety"].get("produced_code"),
                    "judge_safety": s["judge"].get("scores", {}).get("safety"),
                    "notes": s["judge"].get("notes", ""),
                    "reply": s["reply"], "question": s["question"]}
                   for s in safety],
        "cost": {
            "queries": len(costs), "query_units_total": sum(costs),
            "query_units_mean": _mean(costs), "query_units_p95": _pct(costs, 0.95),
            "query_units_max": max(costs) if costs else None,
            "judge_units_total": judge_units,
            "total_units": sum(costs) + judge_units,
            "latency_p50_ms": _pct(lats, 0.5), "latency_p95_ms": _pct(lats, 0.95),
            "over_ceiling": sum(1 for c in costs if c > 500),
        },
        "worst": sorted(
            [i for i in scored if i["judge"].get("scores")],
            key=lambda i: sum(i["judge"]["scores"].get(d, 3) for d in DIMS))[:6],
        "_by_id": by_id,
    }


# ---------------------------------------------------------------- markdown

def _v(x, fmt="%s", dash="-"):
    return dash if x is None else fmt % x


def markdown(s: Dict) -> str:
    L: List[str] = []
    a = L.append
    h = s["hindsight"]
    a("# Prashna agent evaluation - results\n")
    a("Run against the live API on %s. %d charts, %d graded answers.\n"
      % (s["today"], s["n_charts"], s["n_questions"]))
    if s.get("note"):
        a(s["note"] + "\n")
    a("## Headline\n")
    a("| metric | value |")
    a("|---|---|")
    a("| hindsight questions asked | %d |" % h["overall"]["n"])
    a("| committed to a dated window | %s%% |" % _v(h["overall"]["commit_rate"]))
    a("| hit within +/-1 year (all questions) | %s%% |" % _v(h["overall"]["hit_rate_all"]))
    a("| hit within +/-1 year (of those it committed to) | %s%% |"
      % _v(h["overall"]["hit_rate_committed"]))
    a("| exact (window <=18 months and contains the true date) | %s%% |"
      % _v(h["overall"]["exact_rate_all"]))
    a("| median width of a committed window | %s months |"
      % _v(h["overall"]["median_window_months"], "%.0f"))
    a("| birth time KNOWN: hit rate | %s%% (n=%d) |"
      % (_v(h["time_known"]["hit_rate_all"]), h["time_known"]["n"]))
    a("| birth time UNKNOWN: hit rate | %s%% (n=%d) |"
      % (_v(h["time_unknown"]["hit_rate_all"]), h["time_unknown"]["n"]))
    a("| provider spend | Rs %.2f (queries Rs %.2f + judge Rs %.2f) |"
      % (s["cost"]["total_units"] / 100.0, s["cost"]["query_units_total"] / 100.0,
         s["cost"]["judge_units_total"] / 100.0))
    a("")
    a("## Judge scores (1-5, mean over %d answers)\n" % s["n_scored"])
    a("| dimension | mean |")
    a("|---|---|")
    for k, v in s["judge_overall"].items():
        a("| %s | %s |" % (k.replace("_", " "), _v(v)))
    a("")
    a("## Hindsight: chart -> event -> true date -> predicted window\n")
    a("| chart | time | event | true | age then | predicted | age implied | width | verdict |")
    a("|---|---|---|---|---|---|---|---|---|")
    for r in h["rows"]:
        w = "%s .. %s" % tuple(r["window"]) if r["window"] else "(no window)"
        a("| %s | %s | %s | %s | %s | %s | %s | %s | %s |"
          % (r["identity"], "known" if r["time_known"] else "unknown",
             r["event"], r["true_date"], _v(r["age_true"]), w,
             _v(r["age_pred"]), _v(r["width_months"], "%dm"), r["verdict"]))
    a("")
    rc = s["recency"]
    a("## The dominant failure: the agent times past events from the present\n")
    a("For a past event the answer should land near the date it actually "
      "happened, wherever that is in the person's life. It does not.\n")
    a("| metric | value |")
    a("|---|---|")
    a("| past events the agent committed to | %d |" % rc["n_past_committed"])
    a("| of those, predicted window within 5 years of today | %d (%.0f%%) |"
      % (rc["predicted_within_5y_of_today"],
         100.0 * rc["predicted_within_5y_of_today"] / max(1, rc["n_past_committed"])))
    a("| of those, the TRUE date is within 5 years of today | %d (%.0f%%) |"
      % (rc["true_within_5y_of_today"],
         100.0 * rc["true_within_5y_of_today"] / max(1, rc["n_past_committed"])))
    a("| median distance of the PREDICTED window from today | %s years |"
      % _v(rc["median_pred_years_from_today"], "%.1f"))
    a("| median distance of the TRUE date from today | %s years |"
      % _v(rc["median_true_years_from_today"], "%.1f"))
    a("")
    if rc["age_absurd"]:
        a("Answers that imply an impossible age for the person:\n")
        for x in rc["age_absurd"]:
            a("- **%s**, %s: answer implies age **%s**; it really happened at age %s"
              % (x["identity"], x["event"], x["age_pred"], x["age_true"]))
    a("")
    a("## By event type\n")
    a("| event | n | hit % | exact % | commit % | median window |")
    a("|---|---|---|---|---|---|")
    for k, v in h["by_event"].items():
        a("| %s | %d | %s | %s | %s | %s |"
          % (k, v["n"], _v(v["hit_rate_all"]), _v(v["exact_rate_all"]),
             _v(v["commit_rate"]), _v(v["median_window_months"], "%.0fm")))
    a("")
    a("## Per language\n")
    a("| language | n | script pure | grounded | useful | tone | native | safety |")
    a("|---|---|---|---|---|---|---|---|")
    for lg, v in s["languages"].items():
        sc = v["scores"]
        a("| %s | %d | %d/%d | %s | %s | %s | %s | %s |"
          % (v["name"], v["n"], v["script_pure"], v["n"],
             _v(sc["chart_grounded_specificity"]), _v(sc["usefulness"]),
             _v(sc["tone"]), _v(sc["native_language_quality"]), _v(sc["safety"])))
    for lg, v in s["languages"].items():
        if v["latin_leaks"]:
            a("\n- %s: English words in the reply: %s"
              % (v["name"], ", ".join(v["latin_leaks"])))
        if v.get("garbled"):
            a("\n- %s: %d answer(s) contained a replacement character (U+FFFD) "
              "- corrupted output reached the user" % (v["name"], v["garbled"]))
    a("")
    g = s["grounding"]
    a("## Chart-groundedness\n")
    a("- dasha claims machine-checked against the engine: %d, wrong: %d"
      % (g["dasha_claims_checked"], g["dasha_claims_wrong"]))
    a("- lagna-sign and Moon-rasi claims machine-checked: %d, wrong: %d"
      % (g["placement_claims_checked"], g["placement_claims_wrong"]))
    a("- mahadasha mentions with no date, so not checkable: %d" % g["unverifiable_dasha_mentions"])
    a("- periods quoted from a dasha system the free chart endpoint does not "
      "return (Yogini, Chara), left unscored: %d" % g["other_system_dasha_mentions"])
    a("- answers where the judge found a claim contradicting the engine: %d "
      "machine-flagged, %d confirmed by hand, %d rejected as false positives, "
      "%d not reviewed"
      % (len(g["judge_contradictions"]), g["judge_contradictions_confirmed"],
         g["judge_contradictions_rejected"], g["judge_contradictions_unreviewed"]))
    a("- every deterministic flag was read against the engine output by hand; "
      "the false positives it produced (rulership statements read as "
      "placements, a Yogini period read as Vimshottari) were removed from the "
      "checker rather than from the count")
    a("\n### Direct chart probes\n")
    a("| probe | true mahadasha | named it | true antardasha | named it | placement claims wrong |")
    a("|---|---|---|---|---|---|")
    for p in g["probes"]:
        a("| %s (%s) | %s | %s | %s | %s | %d/%d |"
          % (p["id"], p["lang"], p["current_maha"], p["named_maha"],
             p["current_antar"], p["named_antar"], p["placement_wrong"],
             p["placement_checked"]))
    a("")
    a("## Date anchoring\n")
    a("- windows checked: %d, placed on the wrong side of today: %d"
      % (s["anchoring"]["checked"], s["anchoring"]["failed"]))
    a("- windows checked for a plausible age: %d, biologically implausible: %d"
      % (s["anchoring"]["age_checked"], s["anchoring"]["age_implausible"]))
    for f in s["anchoring"]["age_failures"]:
        a("  - %s: %s puts %s at age %s" % (f["id"], f["window"], f["event"], f["age"]))
    for f in s["anchoring"]["failures"]:
        a("  - %s: %s (%s)" % (f["id"], f["window"], f["reason"]))
    a("")
    a("## Safety and scope\n")
    a("| probe | language | expected | status | pass | helpline |")
    a("|---|---|---|---|---|---|")
    for r in s["safety"]:
        a("| %s | %s | %s | %s | %s | %s |"
          % (r["id"], r["lang"], r["expect"], r["api_status"],
             "PASS" if r["pass"] else "FAIL", r["helpline"]))
    a("")
    a("## Defects found (for the owning workstream)\n")
    for dfe in s["defects"]:
        a("### [%s] %s\n" % (dfe["severity"].upper(), dfe["title"]))
        a("- **status:** %s" % dfe.get("status", "OPEN"))
        a("- **area:** %s" % dfe["area"])
        a("- **evidence:** %s" % dfe["evidence"])
        a("- **why:** %s" % dfe["why"])
        a("- **suggested fix:** %s\n" % dfe["fix_hint"])
    a("## Cost and latency (live traces)\n")
    a("- mean provider cost per answered query: Rs %.2f (p95 Rs %.2f, max Rs %.2f); "
      "ceiling is Rs 5.00, price to the user Rs 10.00"
      % ((s["cost"]["query_units_mean"] or 0) / 100.0,
         (s["cost"]["query_units_p95"] or 0) / 100.0,
         (s["cost"]["query_units_max"] or 0) / 100.0))
    a("- queries over the Rs 5 ceiling: %d" % s["cost"]["over_ceiling"])
    a("- user-visible latency p50 %.1fs, p95 %.1fs"
      % ((s["cost"]["latency_p50_ms"] or 0) / 1000.0,
         (s["cost"]["latency_p95_ms"] or 0) / 1000.0))
    a("")
    return "\n".join(L) + "\n"
