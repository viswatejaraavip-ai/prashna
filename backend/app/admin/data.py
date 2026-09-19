"""Bounded Firestore reads for the operator dashboard.

Every query here has a limit and, where it scans time, a date range. At most
one equality filter is pushed to Firestore together with the `created_at`
range/order; the remaining filters are applied in memory over the bounded
scan. That keeps the composite-index list short (see ADMIN_INDEXES).
"""

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from .. import store

DESC = "DESCENDING"  # == google.cloud.firestore.Query.DESCENDING

# Composite indexes these queries need (collection, fields). The platform
# workstream owns Terraform; this list is the source for it.
ADMIN_INDEXES = [
    ("traces", [("uid", "ASC"), ("created_at", "DESC")]),
    ("traces", [("status", "ASC"), ("created_at", "DESC")]),
    ("sessions", [("uid", "ASC"), ("created_at", "DESC")]),
]

MAX_SCAN = 5000


def doc_dict(snap) -> Dict:
    d = snap.to_dict() or {}
    d["id"] = snap.id
    return d


def iso_ago(**kw) -> str:
    return (datetime.now(timezone.utc) - timedelta(**kw)).isoformat()


def ist_day_bounds(day: str) -> Tuple[str, str]:
    """UTC ISO bounds [start, end) of an IST calendar day YYYY-MM-DD."""
    start = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=store.IST)
    return (start.astimezone(timezone.utc).isoformat(),
            (start + timedelta(days=1)).astimezone(timezone.utc).isoformat())


def last_days(n: int) -> List[str]:
    """IST day keys, oldest first, ending today."""
    now = datetime.now(timezone.utc)
    return [store.today_key(now - timedelta(days=i)) for i in range(n - 1, -1, -1)]


# ---------- rollups ----------

def rollups(days: List[str]) -> Dict[str, Dict]:
    db = store.fs()
    refs = [db.collection("rollups_daily").document(d) for d in days]
    out = {}
    for snap in db.get_all(refs):
        if snap.exists:
            out[snap.id] = snap.to_dict() or {}
    return out


# ---------- traces ----------

def recent_traces(since_iso: str, limit: int = MAX_SCAN, until_iso: Optional[str] = None,
                  eq: Optional[Tuple[str, str]] = None) -> List[Dict]:
    """Traces with created_at in [since, until), newest first, bounded."""
    q = store.fs().collection("traces")
    if eq:
        q = q.where(eq[0], "==", eq[1])
    if since_iso:
        q = q.where("created_at", ">=", since_iso)
    if until_iso:
        q = q.where("created_at", "<", until_iso)
    q = q.order_by("created_at", direction=DESC).limit(min(limit, MAX_SCAN))
    return [doc_dict(s) for s in q.stream()]


def search_traces(status: str = "", uid: str = "", lang: str = "", mode: str = "",
                  kind: str = "", min_cost: int = 0, day: str = "",
                  before: str = "", limit: int = 50, scan: int = 1000) -> Dict:
    """Trace explorer. One equality filter (uid, else status) goes to Firestore;
    the rest are applied in memory over at most `scan` docs."""
    since, until = ("", "")
    if day:
        since, until = ist_day_bounds(day)
    if before and (not until or before < until):
        until = before
    if not since and not (uid or status):
        since = iso_ago(days=30)  # bound open-ended scans
    eq = ("uid", uid) if uid else (("status", status) if status else None)
    docs = recent_traces(since, limit=scan, until_iso=until or None, eq=eq)

    def keep(t):
        if status and t.get("status") != status:
            return False
        if lang and t.get("lang") != lang:
            return False
        if mode and t.get("mode") != mode:
            return False
        if kind and (t.get("kind") or "query") != kind:
            return False
        if min_cost and int(t.get("cost_units") or 0) < min_cost:
            return False
        return True

    rows = [t for t in docs if keep(t)][:limit]
    last = rows[-1]["created_at"] if len(rows) == limit else (
        docs[-1]["created_at"] if len(docs) == scan and docs else "")
    return {"traces": [trace_row(t) for t in rows], "scanned": len(docs),
            "next_before": last}


def trace_row(t: Dict) -> Dict:
    """Compact list row (no stage details)."""
    keys = ("id", "trace_id", "uid", "session_id", "lang", "mode", "kind", "status",
            "question_chars", "created_at", "latency_ms", "cost_units",
            "charged_units", "error")
    row = {k: t.get(k) for k in keys}
    row["models"] = sorted({s.get("model") for s in t.get("stages") or [] if s.get("model")})
    return row


def get_trace(trace_id: str) -> Optional[Dict]:
    db = store.fs()
    snap = db.collection("traces").document(trace_id).get()
    if snap.exists:
        return doc_dict(snap)
    for s in db.collection("traces").where("trace_id", "==", trace_id).limit(1).stream():
        return doc_dict(s)
    return None


def session_messages(sid: str, limit: int = 200) -> List[Dict]:
    q = (store.fs().collection("sessions").document(sid).collection("messages")
         .order_by("created_at").limit(limit))
    return [doc_dict(s) for s in q.stream()]


def trace_conversation(trace: Dict) -> Dict:
    """Question + answer text for a trace from its session's messages."""
    sid = trace.get("session_id")
    if not sid:
        return {"question": None, "answer": None}
    msgs = session_messages(sid)
    tid = trace.get("trace_id") or trace.get("id")
    answer_idx = None
    for i, m in enumerate(msgs):
        if m.get("trace_id") in (tid, trace.get("id")) and m.get("role") != "user":
            answer_idx = i
            break
    question = answer = None
    if answer_idx is not None:
        answer = msgs[answer_idx]
        for m in reversed(msgs[:answer_idx]):
            if m.get("role") == "user":
                question = m
                break
    else:
        for m in msgs:
            if m.get("trace_id") in (tid, trace.get("id")) and m.get("role") == "user":
                question = m
    return {"question": question, "answer": answer}


# ---------- users ----------

def find_users(q: str, limit: int = 20) -> List[Dict]:
    q = (q or "").strip()
    if not q:
        return []
    db = store.fs()
    users = db.collection("users")
    found: Dict[str, Dict] = {}
    snap = users.document(q).get() if "/" not in q else None
    if snap is not None and snap.exists:
        found[snap.id] = doc_dict(snap)
    candidates = []
    if "@" in q:
        candidates.append(("email", q.lower()))
        if q.lower() != q:
            candidates.append(("email", q))
    digits = "".join(ch for ch in q if ch.isdigit())
    if len(digits) >= 6:
        for p in {q, digits, "+" + digits, "+91" + digits[-10:], digits[-10:]}:
            candidates.append(("phone", p))
    for field, val in candidates:
        for s in users.where(field, "==", val).limit(limit).stream():
            found[s.id] = doc_dict(s)
    return list(found.values())[:limit]


def _sorted_newest(rows: List[Dict], limit: int) -> List[Dict]:
    rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return rows[:limit]


def by_uid(collection: str, uid: str, limit: int = 100) -> List[Dict]:
    """Small per-user collections: equality only (no composite index), newest
    first after an in-memory sort."""
    q = store.fs().collection(collection).where("uid", "==", uid).limit(500)
    return _sorted_newest([doc_dict(s) for s in q.stream()], limit)


def user_detail(uid: str) -> Optional[Dict]:
    db = store.fs()
    snap = db.collection("users").document(uid).get()
    if not snap.exists:
        return None
    user = doc_dict(snap)
    uref = db.collection("users").document(uid)
    profiles = [doc_dict(s) for s in uref.collection("profiles").limit(50).stream()]
    ledger = [doc_dict(s) for s in uref.collection("ledger")
              .order_by("created_at", direction=DESC).limit(100).stream()]
    sessions = [doc_dict(s) for s in db.collection("sessions").where("uid", "==", uid)
                .order_by("created_at", direction=DESC).limit(20).stream()]
    traces = [trace_row(t) for t in recent_traces("", limit=50, eq=("uid", uid))]
    return {
        "user": user,
        "profiles": profiles,
        "ledger": ledger,
        "sessions": sessions,
        "traces": traces,
        "tickets": by_uid("support_tickets", uid, 50),
        "refunds": by_uid("refunds", uid, 50),
        "payments": by_uid("payments", uid, 50),
        "devices": {"device_hashes": user.get("device_hashes") or [],
                    "fcm_tokens": len(user.get("fcm_tokens") or [])},
    }


# ---------- generic ----------

def newest(collection: str, limit: int = 100, eq: Optional[Tuple[str, str]] = None,
           since_iso: str = "") -> List[Dict]:
    """Newest docs in a collection. With `eq`, uses equality only and sorts in
    memory (queue-sized collections such as open tickets), avoiding an index."""
    q = store.fs().collection(collection)
    if eq:
        q = q.where(eq[0], "==", eq[1]).limit(1000)
        return _sorted_newest([doc_dict(s) for s in q.stream()], limit)
    if since_iso:
        q = q.where("created_at", ">=", since_iso)
    q = q.order_by("created_at", direction=DESC).limit(limit)
    return [doc_dict(s) for s in q.stream()]
