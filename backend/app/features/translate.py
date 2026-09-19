"""Cached machine translation of engine-generated English text.

The Jyotish engine writes labels and explanations (yoga descriptions, dosha
notes, gemstone guidance...) in English. Screens must be fully in the user's
language, so those strings go through Gemini Flash once per (language, text)
and are cached in Firestore (`i18n_cache`) plus an in-process dict. English
is returned unchanged. On any failure the English text is returned, so a
translation outage never breaks a screen.
"""

import hashlib
import logging
import os
from typing import Dict, List

from .. import store

log = logging.getLogger("udhyath.features.translate")

LANG_NAMES = {"hi": "Hindi", "te": "Telugu", "ta": "Tamil", "kn": "Kannada", "ml": "Malayalam"}
_MEM: Dict[str, str] = {}
_BATCH = 60
# Translations are cached forever, so a stronger model is worth it here
# (Flash-Lite sometimes mixes scripts, e.g. Kannada letters in Telugu).
TRANSLATE_MODEL = os.environ.get("TRANSLATE_MODEL", "gemini-3.6-flash")

# Unicode blocks of the Indic scripts; a translation into one language must
# not contain letters of another.
_BLOCKS = {"hi": (0x0900, 0x097F), "bn": (0x0980, 0x09FF), "pa": (0x0A00, 0x0A7F),
           "gu": (0x0A80, 0x0AFF), "or": (0x0B00, 0x0B7F), "ta": (0x0B80, 0x0BFF),
           "te": (0x0C00, 0x0C7F), "kn": (0x0C80, 0x0CFF), "ml": (0x0D00, 0x0D7F)}


def _clean(lang: str, text: str) -> bool:
    for code, (lo, hi) in _BLOCKS.items():
        if code != lang and any(lo <= ord(ch) <= hi for ch in text):
            return False
    return True

_SYSTEM = (
    "You translate short UI strings of a Vedic astrology app from English into {lang}. "
    "Use the traditional Jyotish vocabulary native speakers of {lang} use (e.g. graha, "
    "rashi, bhava, dasha, yoga, dosha names as commonly written in {lang} script). "
    "Keep numbers, dates, degrees and symbols exactly as they are. Keep it natural and "
    "concise; do not add explanations. Return JSON {{\"t\": [...]}} where t has the "
    "translations, the same length and order as the input array."
)


def _key(lang: str, text: str) -> str:
    return hashlib.sha1(("%s\x00%s" % (lang, text)).encode("utf-8")).hexdigest()


def translate_many(texts: List[str], lang: str) -> List[str]:
    if lang not in LANG_NAMES or not texts:
        return list(texts)
    out: Dict[str, str] = {}
    missing = []
    for tx in dict.fromkeys(texts):  # de-duplicate, keep order
        k = _key(lang, tx)
        if k in _MEM:
            out[tx] = _MEM[k]
        else:
            missing.append(tx)
    if missing:
        try:
            refs = [store.fs().collection("i18n_cache").document(_key(lang, tx)) for tx in missing]
            for snap in store.fs().get_all(refs):
                if snap.exists:
                    val = (snap.to_dict() or {}).get("t")
                    if val:
                        _MEM[snap.id] = val
        except Exception as exc:  # cache miss is fine
            log.warning("i18n cache read failed: %s", exc)
        still = []
        for tx in missing:
            k = _key(lang, tx)
            if k in _MEM:
                out[tx] = _MEM[k]
            else:
                still.append(tx)
        for i in range(0, len(still), _BATCH):
            chunk = still[i:i + _BATCH]
            for tx, tr in zip(chunk, _call_model(chunk, lang)):
                out[tx] = tr
    return [out.get(tx, tx) for tx in texts]


def _call_model(chunk: List[str], lang: str) -> List[str]:
    import json
    from ..ai import llm
    try:
        schema = {"type": "object", "required": ["t"],
                  "properties": {"t": {"type": "array", "items": {"type": "string"}}}}
        res, _stage = llm.flash("translate", _SYSTEM.format(lang=LANG_NAMES[lang]),
                                json.dumps(chunk, ensure_ascii=False),
                                max_output_tokens=min(8000, 400 + 120 * len(chunk)),
                                schema=schema, temperature=0.1, model=TRANSLATE_MODEL)
        res = res.get("t") if isinstance(res, dict) else None
        if not isinstance(res, list) or len(res) != len(chunk):
            raise ValueError("translation length mismatch")
    except Exception as exc:
        log.warning("translation to %s failed (%d strings): %s", lang, len(chunk), exc)
        return chunk
    try:
        batch = store.fs().batch()
    except Exception:
        batch = None
    for src, tr in zip(chunk, res):
        tr = str(tr).strip()
        if not tr or not _clean(lang, tr):
            continue  # keep English for this one; retried on a later request
        k = _key(lang, src)
        _MEM[k] = tr
        if batch is not None:
            batch.set(store.fs().collection("i18n_cache").document(k),
                      {"lang": lang, "src": src, "t": tr, "at": store.now_iso()})
    try:
        if batch is not None:
            batch.commit()
    except Exception as exc:
        log.warning("i18n cache write failed: %s", exc)
    return [_MEM.get(_key(lang, s), s) for s in chunk]
