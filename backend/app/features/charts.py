"""Free charts (engine passthrough with the Pro gate) and the Pro bundle."""

from datetime import datetime, timezone
from typing import Dict, Optional

from . import views
from .common import birth_dict, invalid, is_pro, forbidden, japi, jc

BASIC_KINDS = ("rasi", "navamsa", "varga", "bhava", "dashas", "panchanga",
               "yogas", "doshas", "gemstones")
PRO_KINDS = ("kp", "shadbala", "ashtakavarga", "nadi", "varshphal", "lalkitab")
ALL_KINDS = BASIC_KINDS + PRO_KINDS
# Results that depend on the lagna / house cusps (approximate if time unknown).
LAGNA_DEPENDENT = {"rasi", "navamsa", "varga", "bhava", "kp", "shadbala",
                   "ashtakavarga", "nadi", "varshphal", "lalkitab", "gemstones",
                   "yogas", "doshas"}


def normalise_kind(kind: str, division: Optional[str]) -> (str, Optional[str]):
    kind = (kind or "rasi").lower().strip()
    div = (division or "").strip().lower() or None
    # The contract lists the deep kinds under `division` too; accept both.
    if kind == "varga" and div in ALL_KINDS:
        kind, div = div, None
    if kind not in ALL_KINDS:
        raise invalid("kind must be one of: %s" % ", ".join(ALL_KINDS))
    if kind == "varga":
        div = div or "9"
        if div != "all":
            key = "D" + div.upper().lstrip("D")
            if key not in jc.VARGA_LIST:
                raise invalid("division must be all or one of: %s"
                              % ", ".join(v[1:] for v in jc.VARGA_LIST))
            div = key[1:]
    return kind, div


def needs_pro(kind: str, div: Optional[str]) -> bool:
    return kind in PRO_KINDS or (kind == "varga" and div == "all")


def chart(profile: Dict, user: Dict, kind: str, division: Optional[str], lang: str,
          year: Optional[int] = None) -> Dict:
    kind, div = normalise_kind(kind, division)
    if needs_pro(kind, div) and not is_pro(user):
        raise forbidden("'%s' is an astrologer-grade chart and needs an active Pro plan"
                        % (kind if kind != "varga" else "all vargas"))
    birth = birth_dict(profile, lang)
    try:
        if kind == "rasi":
            data = japi.birth_chart(birth)
        elif kind == "navamsa":
            data = japi.varga_chart(birth, "D9")
        elif kind == "varga":
            data = japi.all_vargas(birth) if div == "all" else japi.varga_chart(birth, "D" + div)
        elif kind == "bhava":
            data = japi.bhava_chart(birth)
        elif kind == "dashas":
            data = japi.dasha_periods(birth, 2, "vimshottari")
            data["current"] = japi.current_dasha(birth)
        elif kind == "panchanga":
            data = japi.panchanga_for(birth)
        elif kind == "yogas":
            data = japi.yoga_analysis(birth)
        elif kind == "doshas":
            data = japi.dosha_analysis(birth)
        elif kind == "gemstones":
            data = japi.gemstone_recommendations(birth)
        elif kind == "kp":
            data = japi.kp_chart(birth)
        elif kind == "shadbala":
            data = japi.shadbala_chart(birth)
        elif kind == "ashtakavarga":
            data = japi.ashtakavarga_chart(birth)
        elif kind == "nadi":
            data = japi.nadi_analysis(birth)
        elif kind == "lalkitab":
            data = japi.lal_kitab(birth)
        else:  # varshphal
            data = japi.varshphal(birth, int(year or datetime.now(timezone.utc).year))
    except ValueError as exc:
        raise invalid(str(exc))
    approx = (not profile.get("time_known", True)) and kind in LAGNA_DEPENDENT
    return {"profile_id": profile.get("id"), "kind": kind, "division": div,
            "time_known": profile.get("time_known", True),
            "approximate": approx, "data": data,
            "view": views.build(kind, div, data, lang)}


def pro_bundle(profile: Dict, lang: str) -> Dict:
    """Everything an astrologer needs in one call (Pro only; caller gates)."""
    birth = birth_dict(profile, lang)
    now = datetime.now(timezone.utc)
    dashas = {}
    for system in japi.DASHA_SYSTEMS:
        tl = japi.dasha_periods(birth, 2, system)
        dashas[system] = {"system": tl.get("system", system),
                          "running": japi._active_chain(tl["mahadashas"], now),
                          "mahadashas": tl["mahadashas"]}
    dashas["vimshottari_now"] = japi.current_dasha(birth)
    out = {
        "profile_id": profile.get("id"),
        "time_known": profile.get("time_known", True),
        "approximate": not profile.get("time_known", True),
        "rasi": japi.birth_chart(birth),
        "vargas": japi.all_vargas(birth)["charts"],
        "bhava_chalit": japi.bhava_chart(birth),
        "kp": japi.kp_chart(birth),
        "shadbala": japi.shadbala_chart(birth),
        "ashtakavarga": japi.ashtakavarga_chart(birth),
        "dashas": dashas,
        "yogas": japi.yoga_analysis(birth),
        "doshas": japi.dosha_analysis(birth),
    }
    out["view"] = pro_bundle_view(out, lang)
    return out


def pro_bundle_view(b: Dict, lang: str) -> Dict:
    """One localized view: rasi chart + all 16 vargas + every table."""
    rasi = views.build("rasi", None, b["rasi"], lang)
    vargas = views.build("varga", "all", {"charts": b["vargas"]}, lang)
    vim = dict(b["dashas"].get("vimshottari") or {})
    vim["current"] = b["dashas"].get("vimshottari_now") or {}
    sections = list(rasi.get("sections") or [])
    for kind, data in (("dashas", vim), ("bhava", b["bhava_chalit"]), ("kp", b["kp"]),
                       ("shadbala", b["shadbala"]), ("ashtakavarga", b["ashtakavarga"]),
                       ("yogas", b["yogas"]), ("doshas", b["doshas"])):
        sections += views.build(kind, None, data, lang).get("sections") or []
    return {"chart": rasi.get("chart"), "charts": vargas.get("charts") or [], "sections": sections}
