"""admin_audit: one doc per mutating operator action."""

from typing import Any, Dict, Optional

from .. import store


def write_audit(admin: str, action: str, target: str, before: Any = None,
                after: Any = None, reason: str = "", extra: Optional[Dict] = None,
                doc_id: Optional[str] = None) -> str:
    """Records who did what to which target, with before/after. Returns doc id."""
    doc = {
        "admin": admin,
        "action": action,
        "target": target,
        "before": before,
        "after": after,
        "reason": reason or "",
        "created_at": store.now_iso(),
    }
    if extra:
        doc.update(extra)
    col = store.fs().collection("admin_audit")
    ref = col.document(doc_id) if doc_id else col.document()
    ref.set(doc)
    return ref.id


def new_audit_id() -> str:
    """Pre-allocate an audit id so it can be used as the wallet ledger ref."""
    return store.fs().collection("admin_audit").document().id
