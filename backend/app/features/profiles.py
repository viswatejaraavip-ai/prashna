"""Family/client birth profiles in users/{uid}/profiles."""

import os
import re
from datetime import date
from typing import Dict, List, Optional

from .. import store
from . import places
from .common import derive, invalid, not_found

RELATIONS = ("self", "spouse", "child", "parent", "other", "client")
GENDERS = ("male", "female", "other")
MAX_PROFILES_USER = int(os.environ.get("FEATURES_MAX_PROFILES", "25"))
MAX_PROFILES_ASTRO = int(os.environ.get("FEATURES_MAX_CLIENTS", "2000"))

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d(:[0-5]\d)?$")


def _col(uid: str):
    return store.fs().collection("users").document(uid).collection("profiles")


def _valid_tz(tz: str) -> bool:
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo(tz)
        return True
    except Exception:
        return False


def validate_birth(raw: Dict, time_known: bool) -> Dict:
    """Normalise {date, time?, tz?, lat?, lon?, place?}; look the place up in
    the dataset when coordinates are missing."""
    if not isinstance(raw, dict):
        raise invalid("birth must be an object")
    d = str(raw.get("date") or "").strip()
    if not _DATE.match(d):
        raise invalid("birth.date must be YYYY-MM-DD")
    try:
        dd = date.fromisoformat(d)
    except ValueError:
        raise invalid("birth.date is not a real date")
    if dd.year < 1800 or dd > date.today():
        raise invalid("birth.date must be between 1800 and today")
    tm = str(raw.get("time") or "").strip()
    if time_known:
        if not _TIME.match(tm):
            raise invalid("birth.time must be HH:MM (24h) when time_known is true")
        tm = tm[:5]
    else:
        tm = tm[:5] if _TIME.match(tm) else "12:00"

    place = str(raw.get("place") or "").strip()[:160]
    lat, lon, tz = raw.get("lat"), raw.get("lon"), raw.get("tz")
    if lat is None or lon is None:
        hit = places.resolve(place)
        if not hit:
            raise invalid("Unknown place; pick one from /api/places or send lat/lon/tz")
        lat, lon = hit["lat"], hit["lon"]
        tz = tz or hit["tz"]
        place = places.label(hit)
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        raise invalid("birth.lat/lon must be numbers")
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise invalid("birth.lat/lon out of range")
    tz = str(tz or "Asia/Kolkata")
    if not _valid_tz(tz):
        raise invalid("birth.tz must be an IANA zone like Asia/Kolkata")
    return {"date": d, "time": tm, "tz": tz, "lat": round(lat, 5), "lon": round(lon, 5),
            "place": place}


def _clean(body: Dict, partial: bool, existing: Optional[Dict] = None) -> Dict:
    out: Dict = {}
    if not partial or "name" in body:
        name = str(body.get("name") or "").strip()
        if not 1 <= len(name) <= 80:
            raise invalid("name is required (1-80 characters)")
        out["name"] = name
    if not partial or "relation" in body:
        rel = body.get("relation") or "other"
        if rel not in RELATIONS:
            raise invalid("relation must be one of: %s" % ", ".join(RELATIONS))
        out["relation"] = rel
    if not partial or "gender" in body:
        g = body.get("gender")
        if g not in GENDERS and g is not None:
            raise invalid("gender must be male, female or other")
        out["gender"] = g
    if not partial or "notes" in body:
        notes = str(body.get("notes") or "")
        if len(notes) > 4000:
            raise invalid("notes must be at most 4000 characters")
        out["notes"] = notes
    if not partial or "time_known" in body or "birth" in body:
        tk = body.get("time_known", (existing or {}).get("time_known", True))
        out["time_known"] = bool(tk)
        birth = body.get("birth")
        if birth is None:
            if not partial:
                raise invalid("birth is required")
            birth = dict((existing or {}).get("birth") or {})
        elif existing and partial:
            merged = dict(existing.get("birth") or {})
            if "place" in birth and ("lat" not in birth or "lon" not in birth):
                merged.pop("lat", None)
                merged.pop("lon", None)
                merged.pop("tz", None)
            merged.update(birth)
            birth = merged
        out["birth"] = validate_birth(birth, out["time_known"])
    return out


def _with_derived(doc: Dict) -> Dict:
    try:
        doc["derived"] = derive(doc)
    except Exception:  # never block saving on an engine hiccup
        doc["derived"] = None
    return doc


def public(pid: str, doc: Dict) -> Dict:
    out = {k: v for k, v in doc.items()}
    out["id"] = pid
    return out


def list_profiles(uid: str, relation: Optional[str] = None,
                  exclude_clients: bool = False) -> List[Dict]:
    out = []
    for snap in _col(uid).stream():
        doc = snap.to_dict() or {}
        if relation and doc.get("relation") != relation:
            continue
        if exclude_clients and doc.get("relation") == "client":
            continue
        out.append(public(snap.id, doc))
    out.sort(key=lambda p: (p.get("relation") != "self", p.get("created_at") or ""))
    return out


def get(uid: str, pid: str) -> Dict:
    if not pid or "/" in pid:
        raise not_found("Profile not found")
    snap = _col(uid).document(pid).get()
    if not snap.exists:
        raise not_found("Profile not found")
    return public(pid, snap.to_dict() or {})


def create(uid: str, user: Dict, body: Dict) -> Dict:
    doc = _clean(body, partial=False)
    limit = MAX_PROFILES_ASTRO if (user or {}).get("role") == "astrologer" else MAX_PROFILES_USER
    existing = list_profiles(uid)
    if len(existing) >= limit:
        raise invalid("Profile limit reached (%d)" % limit)
    if doc["relation"] == "self" and any(p.get("relation") == "self" for p in existing):
        raise invalid("A 'self' profile already exists; edit it instead")
    doc["created_at"] = store.now_iso()
    _with_derived(doc)
    ref = _col(uid).document()
    ref.set(doc)
    if doc["relation"] == "self" and not (user or {}).get("name") and doc.get("name"):
        # Onboarding only asks for the name once, on the birth-details form.
        store.fs().collection("users").document(uid).set({"name": doc["name"]}, merge=True)
    return public(ref.id, doc)


def update(uid: str, pid: str, body: Dict) -> Dict:
    current = get(uid, pid)
    patch = _clean(body, partial=True, existing=current)
    if patch.get("relation") == "self" and current.get("relation") != "self":
        if any(p.get("relation") == "self" for p in list_profiles(uid)):
            raise invalid("A 'self' profile already exists")
    if "birth" in patch:
        merged = dict(current)
        merged.update(patch)
        patch["derived"] = _with_derived(merged)["derived"]
    patch["updated_at"] = store.now_iso()
    _col(uid).document(pid).set(patch, merge=True)
    current.update(patch)
    return current


def delete(uid: str, pid: str) -> None:
    get(uid, pid)
    _col(uid).document(pid).delete()


def primary(uid: str) -> Optional[Dict]:
    """The user's own profile (relation=self), else their first non-client."""
    profs = list_profiles(uid, exclude_clients=True)
    return profs[0] if profs else None


def ensure_derived(uid: str, prof: Dict) -> Dict:
    d = prof.get("derived")
    if not d:
        d = derive(prof)
        try:
            _col(uid).document(prof["id"]).set({"derived": d}, merge=True)
        except Exception:
            pass
        prof["derived"] = d
    return d
