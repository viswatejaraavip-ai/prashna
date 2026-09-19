"""Pure cost/usage math for the operator dashboard (no Firestore here).

Money is integer paise (`*_units`); the helpers return rupees only where the
name says so (`*_rs`). Everything takes plain dicts shaped like the `traces`
and `rollups_daily` documents in docs/launch/CONTRACT.md.
"""

from typing import Dict, Iterable, List, Optional

ANSWERED = ("ok", "over_ceiling")          # charged query outcomes
FREE = ("refused", "clarify")              # free turns (still cost money)
STAGE_BUCKETS = ("plan", "brief", "reason", "speech", "other")
LANGS = ("hi", "te", "ta", "kn", "ml", "en")

ROLLUP_FIELDS = ("queries", "voice_queries", "revenue_units", "cost_units",
                 "over_ceiling", "errors", "refusals", "signups",
                 "topups_units", "reports")


def rs(units) -> float:
    """Paise -> rupees, rounded to paise."""
    return round((units or 0) / 100.0, 2)


def percentile(values: Iterable[float], p: float) -> Optional[float]:
    """Linear-interpolated percentile (same as numpy's default). p in 0..100."""
    xs = sorted(float(v) for v in values)
    if not xs:
        return None
    if len(xs) == 1:
        return xs[0]
    k = (len(xs) - 1) * (p / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def margin_pct(revenue_units, cost_units) -> Optional[float]:
    """Gross margin % = (revenue - cost) / revenue. None when there is no revenue."""
    if not revenue_units:
        return None
    return round((revenue_units - (cost_units or 0)) * 100.0 / revenue_units, 1)


def stage_bucket(name: str) -> str:
    name = (name or "").lower()
    if name in ("plan", "brief", "reason"):
        return name
    if name in ("stt", "tts", "speech") or name.startswith(("stt", "tts")):
        return "speech"
    return "other"


def trace_cost(t: Dict) -> int:
    """Total provider cost of a trace; falls back to the sum of its stages."""
    c = t.get("cost_units")
    if c is None:
        c = sum(int(s.get("cost_units") or 0) for s in t.get("stages") or [])
    return int(c or 0)


def is_over_ceiling(t: Dict, ceiling_units: int) -> bool:
    return t.get("status") == "over_ceiling" or trace_cost(t) > ceiling_units


def _r1(x):
    return None if x is None else round(x, 1)


def summarize_traces(traces: List[Dict], ceiling_units: int = 500) -> Dict:
    """Per-query cost statistics over a sample of trace docs.

    Cost-per-query stats (avg, P50, P95, over-ceiling %) use *answered* user
    queries (kind=query, status ok|over_ceiling) because those are what the
    user pays Rs 10 for. Free turns and errors are reported separately so their
    cost is still visible.
    """
    queries = [t for t in traces if (t.get("kind") or "query") == "query"]
    answered = [t for t in queries if t.get("status") in ANSWERED]
    costs = [trace_cost(t) for t in answered]
    lat = [t.get("latency_ms") for t in answered if t.get("latency_ms") is not None]
    over = [t for t in answered if is_over_ceiling(t, ceiling_units)]

    by_stage = {b: 0 for b in STAGE_BUCKETS}
    by_model: Dict[str, Dict] = {}
    stage_lat: Dict[str, List[float]] = {}
    for t in answered:
        for s in t.get("stages") or []:
            b = stage_bucket(s.get("name"))
            c = int(s.get("cost_units") or 0)
            by_stage[b] += c
            if s.get("latency_ms") is not None:
                stage_lat.setdefault(b, []).append(s["latency_ms"])
            m = s.get("model")
            if m:
                row = by_model.setdefault(m, {"calls": 0, "cost_units": 0,
                                              "in_tok": 0, "out_tok": 0})
                row["calls"] += 1
                row["cost_units"] += c
                row["in_tok"] += int(s.get("in_tok") or 0)
                row["out_tok"] += int(s.get("out_tok") or 0)

    def split(key, keys=None):
        out: Dict[str, Dict] = {}
        for t in answered:
            k = t.get(key) or "unknown"
            row = out.setdefault(k, {"queries": 0, "cost_units": 0,
                                     "revenue_units": 0, "over_ceiling": 0})
            row["queries"] += 1
            row["cost_units"] += trace_cost(t)
            row["revenue_units"] += int(t.get("charged_units") or 0)
            row["over_ceiling"] += 1 if is_over_ceiling(t, ceiling_units) else 0
        for k in keys or ():
            out.setdefault(k, {"queries": 0, "cost_units": 0,
                               "revenue_units": 0, "over_ceiling": 0})
        for row in out.values():
            n = row["queries"]
            row["avg_cost_units"] = _r1(row["cost_units"] / n) if n else None
            row["margin_pct"] = margin_pct(row["revenue_units"], row["cost_units"])
        return out

    free = [t for t in queries if t.get("status") in FREE]
    errors = [t for t in queries if t.get("status") == "error"]
    reports = [t for t in traces if t.get("kind") == "report_chapter"]
    other_kinds: Dict[str, Dict] = {}
    for t in traces:
        k = t.get("kind") or "query"
        if k == "query":
            continue
        row = other_kinds.setdefault(k, {"count": 0, "cost_units": 0})
        row["count"] += 1
        row["cost_units"] += trace_cost(t)

    n = len(answered)
    revenue = sum(int(t.get("charged_units") or 0) for t in answered)
    total_cost = sum(costs)
    return {
        "answered": n,
        "free_turns": len(free),
        "free_turn_cost_units": sum(trace_cost(t) for t in free),
        "errors": len(errors),
        "error_cost_units": sum(trace_cost(t) for t in errors),
        "error_rate_pct": round(len(errors) * 100.0 / len(queries), 2) if queries else None,
        "revenue_units": revenue,
        "cost_units": total_cost,
        "margin_pct": margin_pct(revenue, total_cost),
        "avg_cost_units": _r1(total_cost / n) if n else None,
        "p50_cost_units": _r1(percentile(costs, 50)),
        "p95_cost_units": _r1(percentile(costs, 95)),
        "max_cost_units": max(costs) if costs else None,
        "p50_latency_ms": _r1(percentile(lat, 50)),
        "p95_latency_ms": _r1(percentile(lat, 95)),
        "over_ceiling": len(over),
        "over_ceiling_pct": round(len(over) * 100.0 / n, 2) if n else None,
        "ceiling_units": ceiling_units,
        "by_stage": by_stage,
        "stage_p95_latency_ms": {k: _r1(percentile(v, 95)) for k, v in stage_lat.items()},
        "by_model": by_model,
        "by_lang": split("lang", LANGS),
        "by_mode": split("mode", ("text", "voice")),
        "reports": {"chapters": len(reports),
                    "cost_units": sum(trace_cost(t) for t in reports)},
        "by_kind": other_kinds,
        "cost_histogram": cost_histogram(costs, ceiling_units),
    }


def cost_histogram(costs: List[int], ceiling_units: int = 500, step: int = 50) -> List[Dict]:
    """Buckets of `step` paise up to 1.5x the ceiling, then one overflow bucket."""
    top = max(step, int(ceiling_units * 1.5) // step * step)
    buckets = [{"from": lo, "to": lo + step, "count": 0} for lo in range(0, top, step)]
    buckets.append({"from": top, "to": None, "count": 0})
    for c in costs:
        idx = min(int(c) // step, len(buckets) - 1) if c >= 0 else 0
        buckets[idx]["count"] += 1
    return buckets


def rollup_series(days: List[str], docs: Dict[str, Dict]) -> List[Dict]:
    """One row per day (oldest first) with derived margin and avg cost/query."""
    out = []
    for d in days:
        doc = docs.get(d) or {}
        row = {"day": d}
        for f in ROLLUP_FIELDS:
            row[f] = int(doc.get(f) or 0)
        row["by_lang"] = {k: int(v or 0) for k, v in (doc.get("by_lang") or {}).items()}
        row["margin_pct"] = margin_pct(row["revenue_units"], row["cost_units"])
        row["avg_cost_units"] = (_r1(row["cost_units"] / row["queries"])
                                 if row["queries"] else None)
        out.append(row)
    return out


def rollup_totals(series: List[Dict]) -> Dict:
    tot = {f: sum(r[f] for r in series) for f in ROLLUP_FIELDS}
    by_lang: Dict[str, int] = {}
    for r in series:
        for k, v in r.get("by_lang", {}).items():
            by_lang[k] = by_lang.get(k, 0) + v
    tot["by_lang"] = by_lang
    tot["margin_pct"] = margin_pct(tot["revenue_units"], tot["cost_units"])
    tot["avg_cost_units"] = _r1(tot["cost_units"] / tot["queries"]) if tot["queries"] else None
    tot["over_ceiling_pct"] = (round(tot["over_ceiling"] * 100.0 / tot["queries"], 2)
                               if tot["queries"] else None)
    return tot


def watch_level(avg_cost_units: Optional[float], warn_units: int = 450,
                breach_units: int = 500) -> str:
    """ok | warning | breach for the rolling average cost per query."""
    if avg_cost_units is None:
        return "ok"
    if avg_cost_units > breach_units:
        return "breach"
    if avg_cost_units > warn_units:
        return "warning"
    return "ok"
