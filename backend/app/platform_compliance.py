"""Refund requests, support tickets, DPDP data export and account erasure.

Functions the operator dashboard calls:
    decide_refund(refund_id: str, decision: "approved"|"rejected", admin_email: str,
                  note: str = "") -> dict
    reply_ticket(ticket_id: str, message: str, admin_email: str,
                 resolve: bool = True) -> dict
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List

from . import billing, store

log = logging.getLogger("udhyath.compliance")

PURGE_AFTER_DAYS = 30
SUPPORT_CATEGORIES = ("payment", "refund", "report", "answer_quality", "account",
                      "technical", "privacy", "other")
MAX_OPEN_REFUNDS = 5


def _uid_query(collection: str, uid: str, limit: int = 0, order: bool = True):
    from google.cloud.firestore_v1.base_query import FieldFilter
    q = store.fs().collection(collection).where(filter=FieldFilter("uid", "==", uid))
    if order:
        q = q.order_by("created_at", direction="DESCENDING")
    if limit:
        q = q.limit(limit)
    return q


def _docs(query) -> List[Dict]:
    return [dict(d.to_dict() or {}, id=d.id) for d in query.stream()]


# ---------------- Refunds ----------------

def request_refund(uid: str, ref: str, reason: str) -> Dict:
    """``ref`` is a ledger entry id or the ``ref`` of a debit (trace/report
    id). The refundable amount is that debit's value."""
    ledger = store.fs().collection("users").document(uid).collection("ledger")
    entry = None
    snap = ledger.document(ref).get() if "/" not in ref else None
    if snap is not None and snap.exists:
        entry = dict(snap.to_dict() or {}, id=snap.id)
    else:
        from google.cloud.firestore_v1.base_query import FieldFilter
        for d in ledger.where(filter=FieldFilter("ref", "==", ref)).limit(5).stream():
            data = d.to_dict() or {}
            if int(data.get("delta_units", 0)) < 0:
                entry = dict(data, id=d.id)
                break
    if not entry or int(entry.get("delta_units", 0)) >= 0:
        raise store.ApiError(404, "No charge found for this reference", "not_found")
    mine = _docs(_uid_query("refunds", uid, order=False))
    if any(r.get("ledger_id") == entry["id"] and r.get("status") != "rejected" for r in mine):
        raise store.ApiError(409, "A refund was already requested for this charge", "invalid")
    if sum(1 for r in mine if r.get("status") == "requested") >= MAX_OPEN_REFUNDS:
        raise store.ApiError(429, "Too many open refund requests", "rate_limited")
    doc = {"uid": uid, "ref": ref, "ledger_id": entry["id"],
           "charge_type": entry.get("type", ""),
           "amount_units": -int(entry["delta_units"]), "reason": (reason or "")[:2000],
           "status": "requested", "created_at": store.now_iso(), "decided_by": None}
    ref_doc = store.fs().collection("refunds").document()
    ref_doc.set(doc)
    return dict(doc, id=ref_doc.id)


def list_refunds(uid: str, limit: int = 50) -> List[Dict]:
    return _docs(_uid_query("refunds", uid, limit))


def decide_refund(refund_id: str, decision: str, admin_email: str, note: str = "") -> Dict:
    """Admin decision. Approval credits the wallet (idempotent per refund)."""
    if decision not in ("approved", "rejected"):
        raise store.ApiError(400, "decision must be approved or rejected", "invalid")
    rref = store.fs().collection("refunds").document(refund_id)
    now = store.now_iso()

    def _txn(txn):
        snap = rref.get(transaction=txn)
        if not snap.exists:
            raise store.ApiError(404, "Refund not found", "not_found")
        r = snap.to_dict() or {}
        if r.get("status") == "requested":
            txn.update(rref, {"status": decision, "decided_by": admin_email,
                              "decided_at": now, "decision_note": note[:1000]})
            r.update(status=decision, decided_by=admin_email)
        elif r.get("status") != decision or r.get("credited_at"):
            raise store.ApiError(409, "Refund already %s" % r.get("status"), "invalid")
        return r

    r = store.run_transaction(_txn)
    out = dict(r, id=refund_id)
    if decision == "approved":
        out["balance_units"] = billing.refund(
            r["uid"], int(r["amount_units"]), refund_id, note or r.get("reason", ""),
            idem_key="refund_" + refund_id)
        rref.update({"credited_at": store.now_iso()})
    return out


# ---------------- Support ----------------

def create_ticket(uid: str, category: str, message: str) -> Dict:
    if category not in SUPPORT_CATEGORIES:
        category = "other"
    doc = {"uid": uid, "category": category, "message": message[:5000],
           "status": "open", "replies": [], "created_at": store.now_iso()}
    ref = store.fs().collection("support_tickets").document()
    ref.set(doc)
    return dict(doc, id=ref.id)


def list_tickets(uid: str, limit: int = 50) -> List[Dict]:
    return _docs(_uid_query("support_tickets", uid, limit))


def reply_ticket(ticket_id: str, message: str, admin_email: str, resolve: bool = True) -> Dict:
    from google.cloud import firestore
    ref = store.fs().collection("support_tickets").document(ticket_id)
    snap = ref.get()
    if not snap.exists:
        raise store.ApiError(404, "Ticket not found", "not_found")
    reply = {"by": admin_email, "text": message[:5000], "at": store.now_iso()}
    updates = {"replies": firestore.ArrayUnion([reply])}
    if resolve:
        updates["status"] = "resolved"
    ref.update(updates)
    t = snap.to_dict() or {}
    try:
        from .platform_push import send_push
        user = store.get_user(t.get("uid", "")) or {}
        lang = user.get("lang") or store.DEFAULT_LANG
        title = store.brand(lang)
        if lang != "en":
            from .features.translate import translate_many
            title = translate_many(["%s support" % title], lang)[0]
        else:
            title = "%s support" % title
        send_push(t.get("uid", ""), title, message[:180],
                  {"type": "support", "ticket_id": ticket_id})
    except Exception:
        pass
    return dict(t, id=ticket_id, status="resolved" if resolve else t.get("status"),
                replies=(t.get("replies") or []) + [reply])


# ---------------- Disclaimer ----------------

def accept_disclaimer(uid: str, version: str = "1") -> Dict:
    now = store.now_iso()
    store.fs().collection("users").document(uid).update(
        {"disclaimer_accepted_at": now, "disclaimer_version": version})
    return {"disclaimer_accepted_at": now, "disclaimer_version": version}


# ---------------- Export (DPDP right to access) ----------------

def export_user(uid: str) -> Dict:
    db = store.fs()
    uref = db.collection("users").document(uid)
    snap = uref.get()
    user = dict(snap.to_dict() or {}) if snap.exists else {}
    user.pop("device_hashes", None)
    user.pop("fcm_tokens", None)
    out: Dict = {"exported_at": store.now_iso(), "user": user,
                 "profiles": _docs(uref.collection("profiles")),
                 "alerts_sent": _docs(uref.collection("alerts_sent")),
                 "ai_memory": _docs(uref.collection("ai_memory")),
                 "ledger": _docs(uref.collection("ledger").order_by(
                     "created_at", direction="DESCENDING"))}
    sessions = _docs(_uid_query("sessions", uid))
    for s in sessions:
        s["messages"] = _docs(db.collection("sessions").document(s["id"])
                              .collection("messages").order_by("created_at"))
    out["sessions"] = sessions
    for name in ("reports", "payments", "refunds", "support_tickets"):
        out[name] = _docs(_uid_query(name, uid))
        if name == "payments":
            for p in out[name]:
                p.pop("raw", None)
    brand = db.collection("astro_brand").document(uid).get()
    out["astro_brand"] = brand.to_dict() if brand.exists else None
    return out


# ---------------- Erasure (DPDP right to erasure) ----------------

def soft_delete(uid: str) -> Dict:
    """Hide the account now; ``purge_deleted`` erases it after 30 days.
    Signing in again within the grace period restores it."""
    now = datetime.now(timezone.utc)
    purge_at = (now + timedelta(days=PURGE_AFTER_DAYS)).isoformat()
    store.fs().collection("users").document(uid).update(
        {"deleted_at": now.isoformat(), "purge_after": purge_at, "fcm_tokens": []})
    from .platform_auth import revoke_and_delete_firebase_user
    revoke_and_delete_firebase_user(uid, hard=False)
    return {"deleted": True, "purge_after": purge_at}


def _delete_query(query) -> int:
    db = store.fs()
    n = 0
    for d in query.stream():
        db.recursive_delete(d.reference)
        n += 1
    return n


def hard_delete(uid: str) -> Dict:
    """Erase all personal data. Payment records are kept for tax/accounting
    law but pseudonymised (uid replaced by a hash, raw provider data dropped)."""
    import hashlib
    db = store.fs()
    counts = {}
    for name in ("sessions", "reports", "traces", "refunds", "support_tickets"):
        counts[name] = _delete_query(_uid_query(name, uid, order=False))
    pseudo = "erased:" + hashlib.sha256(uid.encode()).hexdigest()[:24]
    n = 0
    for d in _uid_query("payments", uid, order=False).stream():
        d.reference.update({"uid": pseudo, "raw": None})
        n += 1
    counts["payments_pseudonymised"] = n
    brand = db.collection("astro_brand").document(uid)
    if brand.get().exists:
        brand.delete()
    db.recursive_delete(db.collection("users").document(uid))
    try:
        from . import platform_storage
        if platform_storage.GCS_BUCKET:
            counts["files"] = sum(platform_storage.delete_prefix("%s/%s/" % (pre, uid))
                                  for pre in platform_storage.USER_PREFIXES)
    except Exception as exc:
        log.warning("GCS purge for %s failed: %s", uid, exc)
    from .platform_auth import revoke_and_delete_firebase_user
    revoke_and_delete_firebase_user(uid, hard=True)
    return counts


def purge_deleted(limit: int = 200) -> Dict:
    """Cron: hard-delete accounts soft-deleted more than 30 days ago, and
    downgrade expired Pro plans."""
    from google.cloud.firestore_v1.base_query import FieldFilter
    db = store.fs()
    now = store.now_iso()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=PURGE_AFTER_DAYS)).isoformat()
    purged = []
    q = (db.collection("users").where(filter=FieldFilter("deleted_at", "<=", cutoff))
         .limit(limit))
    for d in q.stream():
        data = d.to_dict() or {}
        if not data.get("deleted_at"):
            continue
        try:
            hard_delete(d.id)
            purged.append(d.id)
        except Exception as exc:
            log.error("purge of %s failed: %s", d.id, exc)
    expired = 0
    q = (db.collection("users").where(filter=FieldFilter("plan", "==", "pro"))
         .where(filter=FieldFilter("plan_expires_at", "<", now)).limit(500))
    for d in q.stream():
        d.reference.update({"plan": "free"})
        expired += 1
    return {"purged": len(purged), "plans_expired": expired}
