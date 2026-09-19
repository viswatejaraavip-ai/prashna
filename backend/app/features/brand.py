"""Astrologer white-label settings in astro_brand/{uid}.

Shape (contract): {display_name, phone, logo_url, footer}. The AI workstream
reads the same document for branded reports; use get_brand(uid)."""

import re
from typing import Dict, Optional

from .. import store
from .common import invalid

FIELDS = {"display_name": 80, "phone": 20, "logo_url": 500, "footer": 300}
_PHONE = re.compile(r"^[+0-9 ()-]{0,20}$")


def get_brand(uid: str) -> Optional[Dict]:
    snap = store.fs().collection("astro_brand").document(uid).get()
    return (snap.to_dict() or {}) if snap.exists else None


def put_brand(uid: str, body: Dict) -> Dict:
    doc = {}
    for k, limit in FIELDS.items():
        v = str(body.get(k) or "").strip()
        if len(v) > limit:
            raise invalid("%s must be at most %d characters" % (k, limit))
        doc[k] = v
    if not doc["display_name"]:
        raise invalid("display_name is required")
    if doc["phone"] and not _PHONE.match(doc["phone"]):
        raise invalid("phone has invalid characters")
    if doc["logo_url"] and not doc["logo_url"].startswith("https://"):
        raise invalid("logo_url must be an https URL")
    doc["updated_at"] = store.now_iso()
    store.fs().collection("astro_brand").document(uid).set(doc)
    return doc
