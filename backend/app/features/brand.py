"""Astrologer white-label settings in astro_brand/{uid}.

Shape (contract): {display_name, phone, logo_url, footer}. The AI workstream
reads the same document for branded reports; use get_brand(uid), which returns
None when the astrologer has not set a brand up yet.

The HTTP layer never hands a bare ``None`` to the app: ``blank()`` gives the
same four keys with empty strings, so the settings form always has a shape to
bind to."""

import re
from typing import Dict, Optional

from .. import store
from .common import invalid, t

FIELDS = {"display_name": 80, "phone": 20, "logo_url": 500, "footer": 300}
_PHONE = re.compile(r"^[+0-9 ()-]{0,20}$")


def blank() -> Dict:
    """An empty brand with every contract key present."""
    return {k: "" for k in FIELDS}


def get_brand(uid: str) -> Optional[Dict]:
    snap = store.fs().collection("astro_brand").document(uid).get()
    return (snap.to_dict() or {}) if snap.exists else None


def put_brand(uid: str, body: Dict, lang: str = "en") -> Dict:
    labels = t(lang, "brand_fields")
    doc = {}
    for k, limit in FIELDS.items():
        v = str(body.get(k) or "").strip()
        if len(v) > limit:
            raise invalid(t(lang, "errors.brand_too_long",
                            field=labels.get(k, k), limit=limit))
        doc[k] = v
    if not doc["display_name"]:
        raise invalid(t(lang, "errors.brand_name_required"))
    if doc["phone"] and not _PHONE.match(doc["phone"]):
        raise invalid(t(lang, "errors.brand_phone_invalid"))
    if doc["logo_url"] and not doc["logo_url"].startswith("https://"):
        raise invalid(t(lang, "errors.brand_logo_https"))
    doc["updated_at"] = store.now_iso()
    store.fs().collection("astro_brand").document(uid).set(doc)
    return doc
