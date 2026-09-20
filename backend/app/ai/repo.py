"""Firestore access for the AI workstream (sessions, messages, traces,
per-profile memory). Kept in one module so tests and the cost probe can
monkeypatch storage without an emulator.

Collections written here (CONTRACT.md): sessions, sessions/{sid}/messages,
traces, reports (+ reports/{id}/sections), users/{uid}/ai_memory/{pid}.
Read-only here: users/{uid}/profiles (features), astro_brand (features).
"""

import logging
from typing import Dict, List, Optional

from .. import store

log = logging.getLogger("udhyath.ai.repo")


def _col(name):
    return store.fs().collection(name)


# ---------------- profiles (owned by features; read only) ----------------

def get_profile(uid: str, pid: str) -> Optional[Dict]:
    if not pid:
        return None
    snap = _col("users").document(uid).collection("profiles").document(pid).get()
    if not snap.exists:
        return None
    d = snap.to_dict() or {}
    d["id"] = pid
    return d


def list_profiles(uid: str, limit: int = 12) -> List[Dict]:
    out = []
    for snap in _col("users").document(uid).collection("profiles").limit(limit).stream():
        d = snap.to_dict() or {}
        out.append({"id": snap.id, "name": d.get("name", ""),
                    "relation": d.get("relation", "")})
    return out


def birth_of(profile: Dict) -> Dict:
    """Profile birth{date,time,tz,lat,lon} -> engine birth kwargs."""
    b = profile.get("birth") or {}
    y, m, d = (int(x) for x in str(b["date"])[:10].split("-"))
    hh, mm = 12, 0
    if profile.get("time_known", True) and b.get("time"):
        parts = str(b["time"]).split(":")
        hh, mm = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
    return {"year": y, "month": m, "day": d, "hour": hh, "minute": mm,
            "latitude": float(b["lat"]), "longitude": float(b["lon"]),
            "tz_name": b.get("tz") or "Asia/Kolkata"}


def get_brand(uid: str) -> Optional[Dict]:
    snap = _col("astro_brand").document(uid).get()
    return (snap.to_dict() or None) if snap.exists else None


# ---------------- sessions ----------------

def create_session(uid: str, profile_id: str, lang: str, mode: str) -> str:
    ref = _col("sessions").document()
    ref.set({"uid": uid, "profile_id": profile_id, "lang": lang, "mode": mode,
             "created_at": store.now_iso(), "summary": "", "query_count": 0,
             "free_turns": 0})
    return ref.id


def get_session(sid: str) -> Optional[Dict]:
    snap = _col("sessions").document(sid).get()
    if not snap.exists:
        return None
    d = snap.to_dict() or {}
    d["id"] = sid
    return d


def list_sessions(uid: str, limit: int = 20) -> List[Dict]:
    q = _col("sessions").where("uid", "==", uid)
    try:
        from google.cloud import firestore
        snaps = list(q.order_by("created_at", direction=firestore.Query.DESCENDING)
                     .limit(limit).stream())
    except Exception as exc:  # composite index missing: sort in memory
        log.warning("sessions index missing (%s); sorting in memory", exc)
        snaps = sorted(q.limit(500).stream(),
                       key=lambda s: (s.to_dict() or {}).get("created_at", ""),
                       reverse=True)[:limit]
    return [dict(s.to_dict() or {}, id=s.id) for s in snaps]


def update_session(sid: str, fields: Dict) -> None:
    from google.cloud import firestore
    data = {}
    for k, v in fields.items():
        if isinstance(v, tuple) and v and v[0] == "incr":
            data[k] = firestore.Increment(v[1])
        else:
            data[k] = v
    _col("sessions").document(sid).set(data, merge=True)


def add_message(sid: str, role: str, text: str, charged_units: int = 0,
                trace_id: str = "") -> None:
    _col("sessions").document(sid).collection("messages").document().set({
        "role": role, "text": text, "charged_units": int(charged_units),
        "trace_id": trace_id, "created_at": store.now_iso()})


def list_messages(sid: str, limit: int = 200) -> List[Dict]:
    snaps = (_col("sessions").document(sid).collection("messages")
             .order_by("created_at").limit(limit).stream())
    return [dict(s.to_dict() or {}, id=s.id) for s in snaps]


# ---------------- long-term memory per profile ----------------

# Facts written before memory.grounded() existed have no provenance: nothing
# says whether the client stated them or the astrologer invented them, and in
# practice many were the agent's own predictions and chart placements, read
# back to the client as their own history (backend/evals/RESULTS.md). They are
# therefore not used. The documents are left alone rather than deleted - the
# next answered turn rewrites them, grounded this time.
MEMORY_VERSION = 2


def get_memory(uid: str, pid: str) -> List[str]:
    if not pid:
        return []
    snap = (_col("users").document(uid).collection("ai_memory").document(pid).get())
    if not snap.exists:
        return []
    doc = snap.to_dict() or {}
    if int(doc.get("v") or 1) < MEMORY_VERSION:
        n = len(doc.get("facts") or [])
        if n:
            log.info("ignoring %d ungrounded memory fact(s) for profile %s", n, pid)
        return []
    return list(doc.get("facts") or [])


def save_memory(uid: str, pid: str, facts: List[str]) -> None:
    (_col("users").document(uid).collection("ai_memory").document(pid)
     .set({"facts": facts, "v": MEMORY_VERSION, "updated_at": store.now_iso()}))


# ---------------- traces / rollups / balance ----------------

def write_trace(doc: Dict) -> None:
    _col("traces").document(doc["trace_id"]).set(doc)


def incr_rollup(fields: Dict) -> None:
    store.incr_rollup(fields)


def get_balance(uid: str) -> int:
    user = store.get_user(uid) or {}
    return int(user.get("balance_units", 0) or 0)


def get_user(uid: str) -> Optional[Dict]:
    return store.get_user(uid)
