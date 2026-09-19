"""Operator dashboard: admin API (`/api/admin/*`), the SPA at `/admin`, and
the cost-watch cron (`/internal/cron/cost-watch`).

Every `/api/admin/*` route except `/config` is guarded by `store.require_admin`
(admin JWT with an `adm` claim listed in ADMIN_EMAILS). Every mutating action
writes an `admin_audit` doc. Wallet changes go through billing.adjust/credit/
refund only - this module never writes `balance_units`.
"""

import inspect
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import store
from .admin import alerts, data, metrics
from .admin.audit import new_audit_id, write_audit

log = logging.getLogger("udhyath.admin")

router = APIRouter(tags=["Operator"])
internal_router = APIRouter(tags=["Operator cron"])

STATIC_DIR = Path(__file__).resolve().parent.parent / "static" / "admin"
ASSETS = {"admin.js": "application/javascript", "admin.css": "text/css",
          "favicon.svg": "image/svg+xml"}
NO_CACHE = {"Cache-Control": "no-cache"}

ADJUST_MAX_UNITS = int(os.environ.get("ADMIN_ADJUST_MAX_UNITS", "500000"))  # Rs 5,000

Admin = Depends(store.require_admin)


def _err(status: int, detail: str, code: str):
    # `code` goes in a header so `detail` stays a plain string for the SPA.
    raise HTTPException(status, detail=detail, headers={"X-Error-Code": code})


# ---------- SPA ----------

@router.get("/admin", include_in_schema=False)
@router.get("/admin/", include_in_schema=False)
def admin_page():
    return FileResponse(STATIC_DIR / "index.html", media_type="text/html", headers=NO_CACHE)


@router.get("/admin/assets/{name}", include_in_schema=False)
def admin_asset(name: str):
    if name not in ASSETS:
        raise HTTPException(404, "Not found")
    return FileResponse(STATIC_DIR / name, media_type=ASSETS[name], headers=NO_CACHE)


@router.get("/api/admin/config")
def admin_config():
    """Public Firebase web config for the dashboard's Google sign-in."""
    project = os.environ.get("FIREBASE_PROJECT_ID") or store.GCP_PROJECT
    cfg = {"apiKey": os.environ.get("FIREBASE_WEB_API_KEY", ""),
           "authDomain": os.environ.get("FIREBASE_AUTH_DOMAIN",
                                        "%s.firebaseapp.com" % project if project else ""),
           "projectId": project}
    if os.environ.get("FIREBASE_WEB_APP_ID"):
        cfg["appId"] = os.environ["FIREBASE_WEB_APP_ID"]
    return {"firebase": cfg}


@router.get("/api/admin/me")
def admin_me(admin: str = Admin):
    return {"email": admin}


# ---------- Overview & cost watch ----------

def _ceiling() -> int:
    return int(store.get_flags().get("cost_ceiling_units") or 500)


def _warn_units(ceiling: int) -> int:
    return int(os.environ.get("ALERT_AVG_COST_WARN_UNITS", ceiling * 9 // 10))


@router.get("/api/admin/overview")
def overview(days: int = Query(30, ge=1, le=90), admin: str = Admin):
    flags = store.get_flags()
    ceiling = int(flags.get("cost_ceiling_units") or 500)
    keys = data.last_days(days)
    series = metrics.rollup_series(keys, data.rollups(keys))
    totals = metrics.rollup_totals(series)

    # Percentiles / splits from a bounded sample of recent traces.
    sample_days = min(days, 7)
    since = data.iso_ago(days=sample_days)
    traces = data.recent_traces(since, limit=data.MAX_SCAN)
    truncated = len(traces) >= data.MAX_SCAN
    sample = metrics.summarize_traces(traces, ceiling)
    sample.update(window_days=sample_days, size=len(traces), truncated=truncated,
                  oldest=traces[-1]["created_at"] if traces else None)

    today_start, _ = data.ist_day_bounds(keys[-1])
    today_traces = [t for t in traces if (t.get("created_at") or "") >= today_start]
    day_ago = data.iso_ago(hours=24)
    last24 = metrics.summarize_traces(
        [t for t in traces if (t.get("created_at") or "") >= day_ago], ceiling)

    refunds = data.newest("refunds", limit=1000, since_iso=data.ist_day_bounds(keys[0])[0])
    ref_sum = {"count": len(refunds), "requested": 0, "approved": 0, "rejected": 0,
               "approved_units": 0}
    for r in refunds:
        st = r.get("status") or "requested"
        ref_sum[st] = ref_sum.get(st, 0) + 1
        if st == "approved":
            ref_sum["approved_units"] += int(r.get("refunded_units") or r.get("amount_units") or 0)

    return {
        "days": days,
        "price_units": int(flags.get("query_price_units") or 1000),
        "ceiling_units": ceiling,
        "warn_units": _warn_units(ceiling),
        "series": series,
        "totals": totals,
        "today": {"rollup": series[-1], "traces": metrics.summarize_traces(today_traces, ceiling)},
        "sample": sample,
        "watch": {"avg_cost_units": last24["avg_cost_units"], "answered": last24["answered"],
                  "level": metrics.watch_level(last24["avg_cost_units"],
                                               _warn_units(ceiling), ceiling)},
        "refunds": ref_sum,
    }


@router.get("/api/admin/costwatch")
def costwatch(hours: int = Query(24, ge=1, le=168), limit: int = Query(50, ge=1, le=200),
              admin: str = Admin):
    ceiling = _ceiling()
    traces = data.recent_traces(data.iso_ago(hours=hours), limit=data.MAX_SCAN)
    s = metrics.summarize_traces(traces, ceiling)
    answered = [t for t in traces if (t.get("kind") or "query") == "query"]
    top = sorted(answered, key=metrics.trace_cost, reverse=True)[:limit]
    over = [t for t in traces if metrics.is_over_ceiling(t, ceiling)]
    # Older over-ceiling traces beyond the window (status-flagged by the AI stage).
    older = data.recent_traces("", limit=100, eq=("status", "over_ceiling"))
    seen = {t["id"] for t in over}
    over += [t for t in older if t["id"] not in seen]
    over.sort(key=lambda t: t.get("created_at") or "", reverse=True)
    return {
        "hours": hours, "ceiling_units": ceiling, "warn_units": _warn_units(ceiling),
        "avg_cost_units": s["avg_cost_units"], "p95_cost_units": s["p95_cost_units"],
        "answered": s["answered"], "scanned": len(traces),
        "level": metrics.watch_level(s["avg_cost_units"], _warn_units(ceiling), ceiling),
        "most_expensive": [data.trace_row(t) for t in top],
        "over_ceiling": [data.trace_row(t) for t in over[:200]],
    }


# ---------- Traces ----------

@router.get("/api/admin/traces")
def list_traces(status: str = "", uid: str = "", lang: str = "", mode: str = "",
                kind: str = "", min_cost: int = Query(0, ge=0),
                date: str = Query("", description="IST day YYYY-MM-DD"),
                before: str = Query("", description="created_at cursor from next_before"),
                limit: int = Query(50, ge=1, le=200), admin: str = Admin):
    if date:
        try:
            datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            _err(400, "date must be YYYY-MM-DD", "invalid")
    return data.search_traces(status=status, uid=uid, lang=lang, mode=mode, kind=kind,
                              min_cost=min_cost, day=date, before=before, limit=limit)


@router.get("/api/admin/traces/{trace_id}")
def trace_detail(trace_id: str, admin: str = Admin):
    t = data.get_trace(trace_id)
    if not t:
        _err(404, "Trace not found", "not_found")
    ceiling = _ceiling()
    conv = data.trace_conversation(t)
    user = store.fs().collection("users").document(t["uid"]).get() if t.get("uid") else None
    return {
        "trace": t,
        "over_ceiling": metrics.is_over_ceiling(t, ceiling),
        "ceiling_units": ceiling,
        "question": conv["question"],
        "answer": conv["answer"],
        "user": ({k: (user.to_dict() or {}).get(k) for k in
                  ("uid", "name", "phone", "email", "lang", "role", "balance_units")}
                 if user is not None and user.exists else None),
    }


# ---------- Users ----------

@router.get("/api/admin/users")
def search_users(q: str = Query(..., min_length=2), admin: str = Admin):
    return {"users": data.find_users(q)}


@router.get("/api/admin/users/{uid}")
def user_detail(uid: str, admin: str = Admin):
    d = data.user_detail(uid)
    if not d:
        _err(404, "User not found", "not_found")
    return d


@router.get("/api/admin/sessions/{sid}/messages")
def session_messages(sid: str, admin: str = Admin):
    return {"messages": data.session_messages(sid)}


class AdjustIn(BaseModel):
    delta_units: int
    reason: str = Field(..., min_length=3, max_length=500)


def _billing():
    from . import billing  # platform workstream; imported lazily
    return billing


@router.post("/api/admin/users/{uid}/adjust")
def adjust_balance(uid: str, body: AdjustIn, admin: str = Admin):
    if body.delta_units == 0 or abs(body.delta_units) > ADJUST_MAX_UNITS:
        _err(400, "delta_units must be non-zero and at most %d" % ADJUST_MAX_UNITS, "invalid")
    snap = store.fs().collection("users").document(uid).get()
    if not snap.exists:
        _err(404, "User not found", "not_found")
    before = int((snap.to_dict() or {}).get("balance_units") or 0)
    if before + body.delta_units < 0:
        _err(400, "Adjustment would make the balance negative", "invalid")
    audit_id = new_audit_id()
    billing = _billing()
    try:
        if hasattr(billing, "adjust"):  # signed, ledger type "adjust"
            after = billing.adjust(uid, body.delta_units, body.reason, admin)
        elif body.delta_units > 0:
            after = billing.credit(uid, body.delta_units, "adjust", "admin:" + audit_id)
        else:
            after = billing.charge(uid, -body.delta_units, "adjust", "admin:" + audit_id)
    except ValueError as e:
        _err(400, str(e) or "Invalid adjustment", "invalid")
    except Exception as e:  # e.g. billing.InsufficientBalance / AccountNotFound
        if type(e).__name__ in ("InsufficientBalance", "AccountNotFound"):
            _err(400, type(e).__name__, "insufficient_balance"
                 if type(e).__name__ == "InsufficientBalance" else "not_found")
        raise
    write_audit(admin, "balance_adjust", "users/" + uid,
                before={"balance_units": before},
                after={"balance_units": after, "delta_units": body.delta_units},
                reason=body.reason, doc_id=audit_id)
    return {"uid": uid, "balance_units": after, "audit_id": audit_id}


# ---------- Refunds ----------

@router.get("/api/admin/refunds")
def list_refunds(status: str = "requested", limit: int = Query(100, ge=1, le=500),
                 admin: str = Admin):
    if status and status != "all":
        rows = data.newest("refunds", limit=limit, eq=("status", status))
    else:
        rows = data.newest("refunds", limit=limit)
    return {"refunds": rows}


class RefundDecisionIn(BaseModel):
    decision: str
    note: str = Field("", max_length=500)
    amount_units: Optional[int] = Field(None, ge=1)


@router.post("/api/admin/refunds/{rid}")
def decide_refund(rid: str, body: RefundDecisionIn, admin: str = Admin):
    decision = {"approve": "approved", "approved": "approved",
                "reject": "rejected", "rejected": "rejected"}.get(body.decision.lower())
    if not decision:
        _err(400, "decision must be approve or reject", "invalid")
    ref = store.fs().collection("refunds").document(rid)
    snap = ref.get()
    if not snap.exists:
        _err(404, "Refund not found", "not_found")
    doc = snap.to_dict() or {}
    if doc.get("status", "requested") != "requested":
        _err(409, "Refund already %s" % doc.get("status"), "invalid")
    update: Dict[str, Any] = {"status": decision, "decided_by": admin,
                              "decided_at": store.now_iso(), "note": body.note}
    if decision == "approved":
        requested = int(doc.get("amount_units") or 0)
        units = body.amount_units or requested
        if units <= 0:
            _err(400, "amount_units required (the request has no amount)", "invalid")
        if requested and units > requested:
            _err(400, "Cannot refund more than requested", "invalid")
        balance = _billing().refund(doc["uid"], units, "refund:" + rid,
                                         idem_key="refund_" + rid)
        update.update(refunded_units=units, balance_after=balance)
    ref.update(update)
    write_audit(admin, "refund_" + decision, "refunds/" + rid,
                before={"status": doc.get("status", "requested"),
                        "amount_units": doc.get("amount_units")},
                after=update, reason=body.note, extra={"uid": doc.get("uid")})
    return {"id": rid, **update}


# ---------- Support ----------

@router.get("/api/admin/support")
def list_support(status: str = "open", limit: int = Query(100, ge=1, le=500),
                 admin: str = Admin):
    if status and status != "all":
        rows = data.newest("support_tickets", limit=limit, eq=("status", status))
    else:
        rows = data.newest("support_tickets", limit=limit)
    return {"tickets": rows}


class ReplyIn(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    resolve: bool = False


@router.post("/api/admin/support/{tid}/reply")
def reply_support(tid: str, body: ReplyIn, admin: str = Admin):
    ref = store.fs().collection("support_tickets").document(tid)
    snap = ref.get()
    if not snap.exists:
        _err(404, "Ticket not found", "not_found")
    doc = snap.to_dict() or {}
    reply = {"from": "support", "admin": admin, "message": body.message,
             "created_at": store.now_iso()}
    replies = list(doc.get("replies") or []) + [reply]
    update = {"replies": replies, "updated_at": reply["created_at"]}
    if body.resolve:
        update["status"] = "resolved"
    ref.update(update)
    write_audit(admin, "support_reply", "support_tickets/" + tid,
                before={"status": doc.get("status"), "replies": len(doc.get("replies") or [])},
                after={"status": update.get("status", doc.get("status")),
                       "replies": len(replies), "message": body.message},
                extra={"uid": doc.get("uid")})
    return {"id": tid, "status": update.get("status", doc.get("status")), "replies": replies}


# ---------- Flags ----------

FLAG_TYPES = {"voice_cloud_enabled": bool, "opus_enabled": bool,
              "query_price_units": int, "cost_ceiling_units": int,
              "maintenance_message": str}


def _validate_flags(body: Dict, current: Dict) -> Dict:
    out = {}
    for k, v in body.items():
        if k not in FLAG_TYPES:
            _err(400, "Unknown flag: %s" % k, "invalid")
        t = FLAG_TYPES[k]
        if t is bool and not isinstance(v, bool):
            _err(400, "%s must be true/false" % k, "invalid")
        if t is int and (isinstance(v, bool) or not isinstance(v, int)):
            _err(400, "%s must be an integer (paise)" % k, "invalid")
        if t is str:
            if not isinstance(v, str) or len(v) > 500:
                _err(400, "%s must be text up to 500 chars" % k, "invalid")
            v = v.strip()
        out[k] = v
    price = out.get("query_price_units", current.get("query_price_units"))
    ceiling = out.get("cost_ceiling_units", current.get("cost_ceiling_units"))
    if "query_price_units" in out and not 100 <= price <= 100000:
        _err(400, "query_price_units must be between 100 and 100000 paise", "invalid")
    if "cost_ceiling_units" in out and not 10 <= ceiling <= 100000:
        _err(400, "cost_ceiling_units must be between 10 and 100000 paise", "invalid")
    if ceiling and price and ceiling >= price:
        _err(400, "cost ceiling must stay below the query price", "invalid")
    return out


@router.get("/api/admin/flags")
def get_flags(admin: str = Admin):
    snap = store.fs().collection("config_flags").document("global").get()
    stored = snap.to_dict() if snap.exists else {}
    effective = dict(store._FLAG_DEFAULTS)
    effective.update(stored or {})
    return {"flags": effective, "stored": stored or {}, "cache_seconds": 60}


@router.put("/api/admin/flags")
def put_flags(body: Dict[str, Any] = Body(...), admin: str = Admin):
    ref = store.fs().collection("config_flags").document("global")
    snap = ref.get()
    stored = (snap.to_dict() if snap.exists else {}) or {}
    current = dict(store._FLAG_DEFAULTS)
    current.update(stored)
    changes = _validate_flags(body, current)
    changed = {k: v for k, v in changes.items() if current.get(k) != v}
    if not changed:
        return {"flags": current, "changed": {}}
    changed_at = store.now_iso()
    ref.set(dict(changed, updated_at=changed_at, updated_by=admin), merge=True)
    store.clear_flags_cache()
    write_audit(admin, "flags_update", "config_flags/global",
                before={k: current.get(k) for k in changed}, after=changed)
    current.update(changed)
    return {"flags": current, "changed": changed}


# ---------- Errors & audit ----------

@router.get("/api/admin/errors")
def list_errors(limit: int = Query(100, ge=1, le=500), admin: str = Admin):
    traces = data.recent_traces("", limit=limit, eq=("status", "error"))
    return {"traces": [data.trace_row(t) for t in traces],
            "app_errors": data.newest("app_errors", limit=limit)}


@router.get("/api/admin/audit")
def list_audit(limit: int = Query(100, ge=1, le=500), admin: str = Admin):
    return {"audit": data.newest("admin_audit", limit=limit)}


# ---------- Cron ----------

async def _cron_guard(request: Request) -> None:
    """Delegates to platform_cron.verify_cron (Cloud Scheduler OIDC), imported
    lazily. Fails closed if that module is missing."""
    try:
        from .platform_cron import verify_cron
    except ImportError:
        log.error("platform_cron.verify_cron unavailable; refusing cron call")
        raise HTTPException(503, "Cron auth unavailable")
    kwargs = {}
    for name, p in inspect.signature(verify_cron).parameters.items():
        if name == "request" or p.annotation is Request:
            kwargs[name] = request
        elif name == "authorization":
            kwargs[name] = request.headers.get("authorization")
        elif p.default is inspect.Parameter.empty:
            kwargs[name] = request.headers.get(name.replace("_", "-"))
    res = verify_cron(**kwargs)
    if inspect.isawaitable(res):
        await res


@internal_router.post("/internal/cron/cost-watch", dependencies=[Depends(_cron_guard)])
def cron_cost_watch(hours: int = Query(1, ge=1, le=24)):
    return alerts.run_cost_watch(hours)
