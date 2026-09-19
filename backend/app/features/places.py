"""Place search/lookup over the existing website dataset (backend/static/places.js:
GeoNames India towns + curated world cities)."""

import json
import os
import re
from typing import Dict, List, Optional

_STATIC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "static")
_PLACES: Optional[List[Dict]] = None


def load() -> List[Dict]:
    global _PLACES
    if _PLACES is None:
        with open(os.path.join(_STATIC, "places.js"), encoding="utf-8") as fh:
            src = fh.read()
        out = []
        for _name, arr in re.findall(r"const (PLACES_\w+)\s*=\s*(\[\[.*?\]\]);", src, re.S):
            for row in json.loads(arr):
                out.append({"name": row[0], "region": row[1],
                            "lat": row[2], "lon": row[3],
                            "tz": row[4] if len(row) > 4 else "Asia/Kolkata"})
        _PLACES = out
    return _PLACES


def label(p: Dict) -> str:
    return "%s, %s" % (p["name"], p["region"])


# ---------- Indic-script search ----------
# Users on Telugu/Hindi/Tamil/Kannada/Malayalam keyboards type place names in
# their own script (transliterating keyboards convert even Latin typing). The
# dataset is English-only, so both sides are reduced to a consonant skeleton:
# vowels, h and y dropped, voiced/aspirated folded into one class, doubles
# collapsed. "Hyderabad" and "హైదరాబాద్" both become "trpt".

# Devanagari consonant -> class; the other four scripts map onto Devanagari
# by their fixed Unicode block offsets.
_DEV = {}
for _chars, _cls in (("कखगघक़ख़ग़", "k"), ("ङञणनऩ", "n"), ("चछजझज़", "c"), ("टठडढड़ढ़", "t"),
                     ("तथदध", "t"), ("पफबभफ़", "p"), ("म", "n"), ("रऱ", "r"),
                     ("लळऴ", "l"), ("व", "v"), ("शषस", "s"), ("ं", "n")):
    for _ch in _chars:
        _DEV[_ch] = _cls
_OFFSETS = ((0x0C00, 0x0C7F, 0x300), (0x0B80, 0x0BFF, 0x280),  # Telugu, Tamil
            (0x0C80, 0x0CFF, 0x380), (0x0D00, 0x0D7F, 0x400))  # Kannada, Malayalam
_LATIN = [("kh", "k"), ("gh", "k"), ("ch", "c"), ("jh", "c"), ("th", "t"), ("dh", "t"),
          ("ph", "p"), ("bh", "p"), ("sh", "s"), ("zh", "l"), ("x", "ks")]
_LATIN1 = {"k": "k", "g": "k", "q": "k", "c": "k", "j": "c", "z": "c", "t": "t", "d": "t",
           "p": "p", "b": "p", "f": "p", "m": "n", "n": "n", "r": "r", "l": "l",
           "v": "v", "w": "v", "s": "s"}


def _collapse(chars: List[str]) -> str:
    # A nasal before a stop is written with anusvara in Indic scripts but as
    # m/n/ng in English (Mumbai/मुंबई, Bengaluru/ಬೆಂಗಳೂರು): drop it on both sides.
    # m and n share one class (a final anusvara is "m": തിരുവനന്തപുരം).
    chars = [c for c in chars if c]
    chars = [c for i, c in enumerate(chars)
             if not (c == "n" and i + 1 < len(chars) and chars[i + 1] in "kctp")]
    out: List[str] = []
    for c in chars:
        if c and (not out or out[-1] != c):
            out.append(c)
    return "".join(out)


def _to_devanagari(text: str) -> str:
    out = []
    for ch in text:
        cp = ord(ch)
        for lo, hi, off in _OFFSETS:
            if lo <= cp <= hi:
                ch = chr(cp - off)
                break
        out.append(ch)
    return "".join(out)


def _skeleton_indic(text: str) -> str:
    return _collapse([_DEV.get(ch, "") for ch in _to_devanagari(text)])


# Rough romanisation, only used to rank skeleton ties (Tirupati vs Hyderabad
# are both "trpt").
_ROM_C = dict(zip("कखगघङचछजझञटठडढणतथदधनपफबभमयरलळवशषसहऱऩऴ",
                  ["k", "kh", "g", "gh", "n", "ch", "chh", "j", "jh", "n", "t", "th", "d", "dh",
                   "n", "t", "th", "d", "dh", "n", "p", "ph", "b", "bh", "m", "y", "r", "l", "l",
                   "v", "sh", "sh", "s", "h", "r", "n", "zh"]))
_ROM_V = dict(zip("अआइईउऊऋएऐओऔऎऒ", ["a", "a", "i", "i", "u", "u", "ru", "e", "ai", "o", "au", "e", "o"]))
_ROM_M = dict(zip("ािीुूृेैोौॆॊ", ["a", "i", "i", "u", "u", "ru", "e", "ai", "o", "au", "e", "o"]))


def _romanize(text: str) -> str:
    d = _to_devanagari(text)
    out = []
    for i, ch in enumerate(d):
        nxt = d[i + 1] if i + 1 < len(d) else ""
        if ch in _ROM_C:
            out.append(_ROM_C[ch])
            if nxt not in _ROM_M and nxt != "्" and nxt:
                out.append("a")
        elif ch in _ROM_M:
            out.append(_ROM_M[ch])
        elif ch in _ROM_V:
            out.append(_ROM_V[ch])
        elif ch == "ं":
            out.append("n")
    return "".join(out)


def _skeleton_latin(text: str) -> str:
    t = text.lower()
    for a, b in _LATIN:
        t = t.replace(a, b.upper())  # upper = already mapped
    return _collapse([c.lower() if c.isupper() else _LATIN1.get(c, "") for c in t])


_SKELETONS: Optional[List[str]] = None


def _skeletons() -> List[str]:
    global _SKELETONS
    if _SKELETONS is None:
        _SKELETONS = [_skeleton_latin(p["name"]) for p in load()]
    return _SKELETONS


# Cities whose English name isn't a transliteration of the local one.
_ALIASES = {
    "delhi": ("दिल्ली", "ఢిల్లీ", "டெல்லி", "ದೆಹಲಿ", "ഡൽഹി", "दिल्ली", "డిల్లీ", "தில்லி", "ದಿಲ್ಲಿ", "ദില്ലി"),
    "new delhi": ("नई दिल्ली", "న్యూ ఢిల్లీ", "புது தில்லி", "ನವದೆಹಲಿ", "ന്യൂഡൽഹി"),
    "lucknow": ("लखनऊ", "లక్నో", "லக்னோ", "ಲಕ್ನೋ", "ലഖ്‌നൗ", "ലഖ്നൗ"),
    "kolkata": ("कलकत्ता", "కలకత్తా", "கல்கத்தா", "ಕಲ್ಕತ್ತಾ", "കൽക്കട്ട"),
}
_ALIAS_OF = {native: eng for eng, natives in _ALIASES.items() for native in natives}


def _search_indic(q: str, limit: int) -> List[Dict]:
    alias = next((eng for native, eng in _ALIAS_OF.items()
                  if native.startswith(q) or q.startswith(native)), None)
    if alias:
        hits = search(alias, limit)
        seen = {(h["name"], h["region"]) for h in hits}
        rest = [h for h in _search_indic_skeleton(q, limit) if (h["name"], h["region"]) not in seen]
        return (hits + rest)[:limit]
    return _search_indic_skeleton(q, limit)


def _search_indic_skeleton(q: str, limit: int) -> List[Dict]:
    sk = _skeleton_indic(q)
    if len(sk) < 2:
        return []
    from difflib import SequenceMatcher
    rom = _romanize(q)
    cands = []
    for i, (p, psk) in enumerate(zip(load(), _skeletons())):
        if psk.startswith(sk):
            ratio = SequenceMatcher(None, rom, p["name"].lower()[:len(rom) + 2]).ratio()
            cands.append((psk != sk, -round(ratio, 2), i, p))
            if len(cands) >= 300:
                break
    cands.sort(key=lambda c: c[:3])
    return [dict(c[3], label=label(c[3])) for c in cands[:limit]]


def search(q: str, limit: int = 12) -> List[Dict]:
    q = (q or "").strip().lower()
    if len(q) < 2:
        return []
    if any(ord(c) > 0x7F for c in q):
        return _search_indic(q, limit)
    starts, contains = [], []
    for p in load():
        n = p["name"].lower()
        if n.startswith(q):
            starts.append(p)
        elif q in n or q in p["region"].lower():
            contains.append(p)
        if len(starts) >= limit:
            break
    return [dict(p, label=label(p)) for p in (starts + contains)[:limit]]


def resolve(place: str) -> Optional[Dict]:
    """Best match for "Town" or "Town, Region"; exact name matches win,
    earlier (more populous) rows win ties."""
    if not place:
        return None
    parts = [s.strip().lower() for s in place.split(",")]
    name = parts[0]
    region = parts[1] if len(parts) > 1 else ""
    for p in load():
        if p["name"].lower() == name and (not region or p["region"].lower() == region):
            return p
    for p in load():
        if p["name"].lower() == name:
            return p
    hits = search(name, 1)
    return hits[0] if hits else None
