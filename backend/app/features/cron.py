"""Scheduled pushes: the morning day forecast and upcoming transit alerts.

Both jobs stream the users who opted in, work out each user's primary
profile, reuse cached/memoised astrology (the forecast is shared per
date/lang/Moon rasi; eclipses and ingresses are shared by everyone) and fan
the pushes out over a small thread pool. A marker document in
users/{uid}/alerts_sent makes both jobs safe to retry (Cloud Scheduler
retries on failure)."""

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from .. import store
from . import alerts as alerts_mod
from . import daily, profiles
from .common import LANGS, t

log = logging.getLogger("udhyath.features.cron")
IST = timezone(timedelta(hours=5, minutes=30))
PUSH_WORKERS = int(os.environ.get("FEATURES_PUSH_WORKERS", "8"))
TIME_BUDGET_S = float(os.environ.get("FEATURES_CRON_BUDGET_S", "500"))
LEAD_DAYS = sorted({int(x) for x in os.environ.get("FEATURES_ALERT_LEAD_DAYS", "7,1").split(",")
                    if x.strip().isdigit()})


def _send_push(uid: str, title: str, body: str, data: Dict, category: str) -> Optional[int]:
    """Devices reached (0 = no registered device), or None on failure."""
    from .. import platform_push  # platform workstream; imported lazily
    try:
        return int(platform_push.send_push(uid, title, body, data, category=category) or 0)
    except Exception:
        log.exception("push failed for %s", uid)
        return None


def _sent_ref(uid: str, key: str):
    return (store.fs().collection("users").document(uid)
            .collection("alerts_sent").document(key))


def _opted_in(pref: str, page: int = 300):
    """Opted-in users, fetched in pages (no long-lived stream while we work)."""
    query = store.fs().collection("users").where("notif_prefs.%s" % pref, "==", True)
    last = None
    while True:
        q = query.limit(page)
        if last is not None:
            q = q.start_after(last)
        snaps = list(q.stream())
        for snap in snaps:
            user = snap.to_dict() or {}
            if not user.get("deleted_at"):
                yield snap.id, user
        if len(snaps) < page:
            return
        last = snaps[-1]


def _lang(user: Dict) -> str:
    lang = user.get("lang")
    return lang if lang in LANGS else store.DEFAULT_LANG


def _run(jobs: List[Dict], category: str) -> int:
    """Send a batch concurrently; returns how many reached a device. A marker
    is written whenever the send did not fail, so retries don't repeat it."""
    sent = 0
    with ThreadPoolExecutor(max_workers=PUSH_WORKERS) as pool:
        results = list(pool.map(
            lambda j: (j, _send_push(j["uid"], j["title"], j["body"], j["data"], category)), jobs))
    for job, devices in results:
        if devices is None:
            continue
        sent += 1 if devices > 0 else 0
        try:
            _sent_ref(job["uid"], job["key"]).set(
                {"at": store.now_iso(), "type": job["data"].get("type"), "devices": devices})
        except Exception:
            log.exception("could not record push marker")
    return sent


def daily_push(today=None, batch_size: int = 200) -> Dict:
    today = today or datetime.now(IST).date()
    started = time.time()
    stats = {"date": today.isoformat(), "considered": 0, "sent": 0, "skipped": 0, "errors": 0}
    batch: List[Dict] = []
    for uid, user in _opted_in("daily"):
        if time.time() - started > TIME_BUDGET_S:
            stats["stopped_early"] = True
            break
        stats["considered"] += 1
        key = "daily_%s" % today.isoformat()
        try:
            if _sent_ref(uid, key).get().exists:
                stats["skipped"] += 1
                continue
            prof = profiles.primary(uid)
            if not prof:
                stats["skipped"] += 1
                continue
            lang = _lang(user)
            derived = profiles.ensure_derived(uid, prof)
            fc = daily.personal(today, lang, derived, prof.get("name", ""))
            title = t(lang, "daily.push_title", name=prof.get("name", ""), rating=fc["rating_text"])
            batch.append({"uid": uid, "key": key, "title": title, "body": fc["lines"][0],
                          "data": {"type": "daily", "date": today.isoformat(),
                                   "profile_id": prof["id"], "rating": fc["rating"]}})
        except Exception:
            stats["errors"] += 1
            log.exception("daily push prep failed for %s", uid)
        if len(batch) >= batch_size:
            stats["sent"] += _run(batch, "daily")
            batch = []
    if batch:
        stats["sent"] += _run(batch, "daily")
    return stats


def transit_alerts(today=None, lead_days: Optional[List[int]] = None, batch_size: int = 200) -> Dict:
    today = today or datetime.now(IST).date()
    leads = sorted(set(lead_days or LEAD_DAYS)) or [7, 1]
    started = time.time()
    stats = {"date": today.isoformat(), "lead_days": leads, "considered": 0, "sent": 0,
             "skipped": 0, "errors": 0}
    horizon = max(leads) + 1
    batch: List[Dict] = []
    for uid, user in _opted_in("transits"):
        if time.time() - started > TIME_BUDGET_S:
            stats["stopped_early"] = True
            break
        stats["considered"] += 1
        try:
            prof = profiles.primary(uid)
            if not prof:
                stats["skipped"] += 1
                continue
            lang = _lang(user)
            profiles.ensure_derived(uid, prof)
            for a in alerts_mod.compute(prof, lang, days=horizon, today=today):
                if a["days_away"] not in leads:
                    continue
                if a["type"] == "eclipse" and not a["data"].get("personal"):
                    continue
                key = "%s_%d" % (a["id"], a["days_away"])
                if _sent_ref(uid, key).get().exists:
                    continue
                when = t(lang, "alerts.tomorrow") if a["days_away"] == 1 else \
                    t(lang, "alerts.in_days", days=a["days_away"])
                batch.append({"uid": uid, "key": key,
                              "title": t(lang, "alerts.push_title", title=a["title"]) + " (%s)" % when,
                              "body": a["text"],
                              "data": {"type": "transit_alert", "alert_id": a["id"],
                                       "alert_type": a["type"], "date": a["date"],
                                       "profile_id": prof["id"]}})
        except Exception:
            stats["errors"] += 1
            log.exception("transit alert prep failed for %s", uid)
        if len(batch) >= batch_size:
            stats["sent"] += _run(batch, "transits")
            batch = []
    if batch:
        stats["sent"] += _run(batch, "transits")
    return stats
