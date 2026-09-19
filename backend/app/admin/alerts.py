"""Hourly cost / error-rate watch that pings the operators.

Triggered by Cloud Scheduler -> POST /internal/cron/cost-watch. Posts a plain
`{"text": ...}` JSON to ALERT_WEBHOOK_URL (Google Chat and Slack incoming
webhooks both accept that). Repeats of the same alert are suppressed for
ALERT_REPEAT_MINUTES.
"""

import json
import logging
import os
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Dict, List

from .. import store
from . import data, metrics

log = logging.getLogger("udhyath.alerts")


def _env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return int(default)


def thresholds() -> Dict:
    flags = store.get_flags()
    ceiling = int(flags.get("cost_ceiling_units") or 500)
    return {
        "warn_units": _env_int("ALERT_AVG_COST_WARN_UNITS", ceiling * 9 // 10),
        "breach_units": _env_int("ALERT_AVG_COST_BREACH_UNITS", ceiling),
        "error_rate_pct": float(os.environ.get("ALERT_ERROR_RATE_PCT", "5")),
        "min_queries": _env_int("ALERT_MIN_QUERIES", 5),
        "repeat_minutes": _env_int("ALERT_REPEAT_MINUTES", 180),
        "ceiling_units": ceiling,
    }


def evaluate(traces: List[Dict], th: Dict) -> Dict:
    s = metrics.summarize_traces(traces, th["ceiling_units"])
    queries = s["answered"] + s["free_turns"] + s["errors"]
    problems, keys = [], []
    level = metrics.watch_level(s["avg_cost_units"], th["warn_units"], th["breach_units"])
    if s["answered"] >= th["min_queries"] and level != "ok":
        problems.append("avg cost/query Rs %.2f (%s; ceiling Rs %.2f) over %d queries" % (
            metrics.rs(s["avg_cost_units"]), level, metrics.rs(th["ceiling_units"]),
            s["answered"]))
        keys.append("cost_" + level)
    if queries >= th["min_queries"] and (s["error_rate_pct"] or 0) > th["error_rate_pct"]:
        problems.append("error rate %.1f%% (%d of %d queries)" % (
            s["error_rate_pct"], s["errors"], queries))
        keys.append("errors")
    return {"summary": s, "level": level, "problems": problems, "keys": keys,
            "queries": queries}


def post_webhook(text: str) -> bool:
    url = os.environ.get("ALERT_WEBHOOK_URL", "")
    if not url:
        log.warning("ALERT_WEBHOOK_URL not set; alert not sent: %s", text)
        return False
    req = urllib.request.Request(url, data=json.dumps({"text": text}).encode(),
                                 headers={"Content-Type": "application/json; charset=UTF-8"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return 200 <= resp.status < 300
    except Exception as e:
        log.error("Alert webhook failed: %s", e)
        return False


def run_cost_watch(hours: int = 1) -> Dict:
    th = thresholds()
    traces = data.recent_traces(data.iso_ago(hours=hours), limit=data.MAX_SCAN)
    res = evaluate(traces, th)
    out = {"window_hours": hours, "level": res["level"], "problems": res["problems"],
           "queries": res["queries"], "avg_cost_units": res["summary"]["avg_cost_units"],
           "p95_cost_units": res["summary"]["p95_cost_units"],
           "error_rate_pct": res["summary"]["error_rate_pct"], "sent": False}
    if not res["problems"]:
        return out

    state_ref = store.fs().collection("admin_alerts").document("cost_watch")
    snap = state_ref.get()
    state = snap.to_dict() if snap.exists else {}
    key = "|".join(res["keys"])
    last = state.get("last_sent_at") or ""
    recent = last and last > (datetime.now(timezone.utc)
                              - timedelta(minutes=th["repeat_minutes"])).isoformat()
    if recent and state.get("key") == key:
        out["suppressed"] = True
        return out

    base = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
    text = "Prashna alert (last %dh): %s" % (hours, "; ".join(res["problems"]))
    if base:
        text += "\n%s/admin#/cost" % base
    out["sent"] = post_webhook(text)
    state_ref.set({"key": key, "last_sent_at": store.now_iso(), "text": text,
                   "sent": out["sent"]})
    return out
