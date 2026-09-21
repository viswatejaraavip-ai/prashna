"""Multilingual Jyotish vocabulary used by the deterministic scorers.

The agent answers in the client's language and script, so a scorer that wants
to check "did it say Saturn mahadasha" has to recognise Saturn and mahadasha in
six scripts. Stems (not whole words) are listed, because Indic replies inflect
them (Telugu "శని" -> "శనిలో", "శనిది"). A stem that is also a common everyday
word is listed with the strings it must NOT be part of (Telugu "గురు" is also
"గురువారం" = Thursday).

Recall is deliberately incomplete and that is safe: a missed claim is not
scored, it is never scored wrong. The scorers report how many claims they
could extract so the reader can judge coverage.
"""

from typing import Dict, List, Tuple

PLANETS = ("Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Rahu", "Ketu")

SIGNS = ("Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo", "Libra",
         "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces")

# planet -> lang -> [stems]
PLANET_STEMS: Dict[str, Dict[str, List[str]]] = {
    "Sun":     {"en": ["sun"], "hi": ["सूर्य", "रवि"], "te": ["సూర్య", "రవి"],
                "ta": ["சூரிய", "ரவி"], "kn": ["ಸೂರ್ಯ", "ರವಿ"], "ml": ["സൂര്യ", "ആദിത്യ"]},
    "Moon":    {"en": ["moon"], "hi": ["चंद्र", "चन्द्र"], "te": ["చంద్ర"],
                "ta": ["சந்திர"], "kn": ["ಚಂದ್ರ"], "ml": ["ചന്ദ്ര"]},
    "Mars":    {"en": ["mars"], "hi": ["मंगल", "कुज", "भौम"], "te": ["కుజ", "అంగారక", "మంగళ"],
                "ta": ["செவ்வாய", "அங்காரக"], "kn": ["ಕುಜ", "ಮಂಗಳ", "ಅಂಗಾರಕ"],
                "ml": ["ചൊവ്വ", "കുജ"]},
    "Mercury": {"en": ["mercury"], "hi": ["बुध"], "te": ["బుధ"], "ta": ["புத"],
                "kn": ["ಬುಧ"], "ml": ["ബുധ"]},
    "Jupiter": {"en": ["jupiter"], "hi": ["गुरु", "बृहस्पति"], "te": ["గురు", "బృహస్పతి"],
                "ta": ["குரு", "வியாழ"], "kn": ["ಗುರು", "ಬೃಹಸ್ಪತಿ"],
                "ml": ["ഗുരു", "വ്യാഴ", "ബൃഹസ്പതി"]},
    "Venus":   {"en": ["venus"], "hi": ["शुक्र"], "te": ["శుక్ర"], "ta": ["சுக்கிர"],
                "kn": ["ಶುಕ್ರ"], "ml": ["ശുക്ര"]},
    "Saturn":  {"en": ["saturn"], "hi": ["शनि"], "te": ["శని"], "ta": ["சனி"],
                "kn": ["ಶನಿ"], "ml": ["ശനി"]},
    "Rahu":    {"en": ["rahu"], "hi": ["राहु"], "te": ["రాహు"], "ta": ["ராகு"],
                "kn": ["ರಾಹು"], "ml": ["രാഹു"]},
    "Ketu":    {"en": ["ketu"], "hi": ["केतु"], "te": ["కేతు"], "ta": ["கேது"],
                "kn": ["ಕೇತು"], "ml": ["കേതു"]},
}

# Stems that are a prefix of an unrelated everyday word (weekday names, mostly).
PLANET_BLOCKERS: Dict[str, List[str]] = {
    "గురు": ["గురువారం"], "శుక్ర": ["శుక్రవారం"], "శని": ["శనివారం"],
    "బుధ": ["బుధవారం"], "మంగళ": ["మంగళవారం"], "ఆది": ["ఆదివారం"],
    "गुरु": ["गुरुवार"], "शुक्र": ["शुक्रवार"], "शनि": ["शनिवार"],
    "बुध": ["बुधवार"], "मंगल": ["मंगलवार"], "रवि": ["रविवार"],
    "ಗುರು": ["ಗುರುವಾರ"], "ಶುಕ್ರ": ["ಶುಕ್ರವಾರ"], "ಶನಿ": ["ಶನಿವಾರ"],
    "ಬುಧ": ["ಬುಧವಾರ"], "ಮಂಗಳ": ["ಮಂಗಳವಾರ"], "ರವಿ": ["ರವಿವಾರ"],
    "குரு": ["குருவார"], "சுக்கிர": ["சுக்கிரவார"], "சனி": ["சனிக்கிழமை"],
    "வியாழ": ["வியாழக்கிழமை"], "செவ்வாய": ["செவ்வாய்க்கிழமை"],
    "ഗുരു": ["ഗുരുവാഴ്ച"], "ശുക്ര": ["വെള്ളിയാഴ്ച"], "ശനി": ["ശനിയാഴ്ച"],
    "ബുധ": ["ബുധനാഴ്ച"], "വ്യാഴ": ["വ്യാഴാഴ്ച"],
    # Tamil "புத்தி" is bhukti, the antardasha itself, not the planet Mercury;
    # without this every "சந்திர புத்தி" read as a Moon-Mercury pair.
    "புத": ["புத்தி"],
}

SIGN_STEMS: Dict[str, Dict[str, List[str]]] = {
    "Aries":       {"en": ["aries"], "hi": ["मेष"], "te": ["మేష"], "ta": ["மேஷ"], "kn": ["ಮೇಷ"], "ml": ["മേട"]},
    "Taurus":      {"en": ["taurus"], "hi": ["वृष"], "te": ["వృషభ"], "ta": ["ரிஷப"], "kn": ["ವೃಷಭ"], "ml": ["ഇടവ"]},
    "Gemini":      {"en": ["gemini"], "hi": ["मिथुन"], "te": ["మిథున"], "ta": ["மிதுன"], "kn": ["ಮಿಥುನ"], "ml": ["മിഥുന"]},
    "Cancer":      {"en": ["cancer"], "hi": ["कर्क"], "te": ["కర్కాట"], "ta": ["கடக"], "kn": ["ಕರ್ಕಾಟ"], "ml": ["കർക്കട"]},
    "Leo":         {"en": ["leo"], "hi": ["सिंह"], "te": ["సింహ"], "ta": ["சிம்ம"], "kn": ["ಸಿಂಹ"], "ml": ["ചിങ്ങ"]},
    "Virgo":       {"en": ["virgo"], "hi": ["कन्या"], "te": ["కన్య"], "ta": ["கன்னி"], "kn": ["ಕನ್ಯ"], "ml": ["കന്നി"]},
    "Libra":       {"en": ["libra"], "hi": ["तुला"], "te": ["తుల"], "ta": ["துலா"], "kn": ["ತುಲಾ"], "ml": ["തുലാ"]},
    "Scorpio":     {"en": ["scorpio"], "hi": ["वृश्चिक"], "te": ["వృశ్చిక"], "ta": ["விருச்சிக"], "kn": ["ವೃಶ್ಚಿಕ"], "ml": ["വൃശ്ചിക"]},
    "Sagittarius": {"en": ["sagittarius"], "hi": ["धनु"], "te": ["ధను"], "ta": ["தனுசு"], "kn": ["ಧನು"], "ml": ["ധനു"]},
    "Capricorn":   {"en": ["capricorn"], "hi": ["मकर"], "te": ["మకర"], "ta": ["மகர"], "kn": ["ಮಕರ"], "ml": ["മകര"]},
    "Aquarius":    {"en": ["aquarius"], "hi": ["कुंभ", "कुम्भ"], "te": ["కుంభ"], "ta": ["கும்ப"], "kn": ["ಕುಂಭ"], "ml": ["കുംഭ"]},
    "Pisces":      {"en": ["pisces"], "hi": ["मीन"], "te": ["మీన"], "ta": ["மீன"], "kn": ["ಮೀನ"], "ml": ["മീന"]},
}

# "dasha" in each language, as written by the app's own i18n bundle plus the
# forms a native writer uses.
DASHA_WORDS: Dict[str, List[str]] = {
    "en": ["mahadasha", "antardasha", "dasha", "bhukti"],
    "hi": ["महादशा", "अंतर्दशा", "अन्तर्दशा", "दशा", "भुक्ति"],
    "te": ["మహాదశ", "అంతర్దశ", "దశ", "భుక్తి"],
    "ta": ["மகா தசை", "மகாதசை", "தசை", "புத்தி", "புக்தி"],
    "kn": ["ಮಹಾದಶೆ", "ಮಹಾದಶಾ", "ಅಂತರ್ದಶೆ", "ದಶೆ", "ದಶಾ", "ಭುಕ್ತಿ"],
    "ml": ["മഹാദശ", "അന്തർദശ", "അപഹാര", "ദശ", "ഭുക്തി"],
}

# Words that mean specifically the Vimshottari MAHADASHA (the only level the
# free chart endpoint exposes), and words that mean a DIFFERENT dasha system or
# a deeper level. A claim is only machine-checked when the first set appears and
# the second does not -- otherwise the checker would "correct" a correct
# pratyantardasha or a correct Yogini/Chara period it has no table for.
MAHA_WORDS: Dict[str, List[str]] = {
    "en": ["mahadasha", "maha dasha", "major period"],
    "hi": ["महादशा", "महा दशा"],
    "te": ["మహాదశ", "మహా దశ"],
    "ta": ["மகா தசை", "மகாதசை"],
    "kn": ["ಮಹಾದಶೆ", "ಮಹಾದಶಾ", "ಮಹಾ ದಶೆ"],
    "ml": ["മഹാദശ", "മഹാ ദശ"],
}

# A DIFFERENT dasha system. The free chart endpoint only returns Vimshottari,
# so a "Yogini mahadasha" or a "Chara mahadasha" cannot be checked here and
# must not be scored against the Vimshottari table.
OTHER_SYSTEM_WORDS: List[str] = [
    "yogini", "chara dasha", "kalachakra", "ashtottari", "jaimini",
    "bhramari", "mandukhya", "pingala", "dhanya", "sankata", "siddha", "ulka",
    "యోగిని", "చర దశ", "చరదశ", "కాలచక్ర", "అష్టోత్తరి", "భ్రామరి", "సిద్ధ",
    "సంకట", "ఉల్క", "పింగళ", "ధాన్య", "మాండూక",
    "योगिनी", "चर दशा", "चरदशा", "कालचक्र", "अष्टोत्तरी", "भ्रामरी", "सिद्ध",
    "संकट", "उल्का", "पिंगला", "धान्य", "मांडूक",
    "யோகினி", "சர தசை", "காலசக்ர", "அஷ்டோத்தரி", "பிராமரி", "சித்த",
    "ಯೋಗಿನಿ", "ಚರ ದಶೆ", "ಚರದಶೆ", "ಕಾಲಚಕ್ರ", "ಅಷ್ಟೋತ್ತರಿ", "ಭ್ರಾಮರಿ", "ಸಿದ್ಧ",
    "യോഗിനി", "ചര ദശ", "കാലചക്ര", "അഷ്ടോത്തരി", "ഭ്രാമരി", "സിദ്ധ",
]

# The third dasha level. It is Vimshottari, but the free chart endpoint returns
# only the pratyantardasha running today, never the table, so a pratyantar
# period cannot be machine-checked either.
DEEPER_LEVEL_WORDS: List[str] = [
    "pratyantar", "pratyanthar", "sookshma", "sukshma",
    "ప్రత్యంతర", "प्रत्यंतर", "प्रत्यन्तर",
    "பிரத்யந்தர", "ಪ್ರತ್ಯಂತರ", "പ്രത്യന്തർ",
]


# Unicode ranges, for script-purity checks.
SCRIPT_RANGE: Dict[str, Tuple[int, int]] = {
    "hi": (0x0900, 0x097F), "bn": (0x0980, 0x09FF), "pa": (0x0A00, 0x0A7F),
    "gu": (0x0A80, 0x0AFF), "or": (0x0B00, 0x0B7F), "ta": (0x0B80, 0x0BFF),
    "te": (0x0C00, 0x0C7F), "kn": (0x0C80, 0x0CFF), "ml": (0x0D00, 0x0D7F),
}

# Latin tokens allowed even in an Indic reply.
LATIN_ALLOWED = {
    "tele", "manas", "telemanas", "ist", "am", "pm", "a", "b", "c", "d", "e",
    "f", "g", "h", "i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x",
}


def stem_hits(text: str, stems: List[str]) -> List[int]:
    """Start offsets of every occurrence of any stem, skipping occurrences that
    are part of a blocked everyday word."""
    out: List[int] = []
    low = text.lower()
    for st in stems:
        s = st.lower()
        blockers = [b.lower() for b in PLANET_BLOCKERS.get(st, [])]
        i = low.find(s)
        while i >= 0:
            if not any(low[max(0, i - len(b)):i + len(b)].find(b) >= 0 for b in blockers):
                out.append(i)
            i = low.find(s, i + 1)
    return sorted(set(out))


def find_planets(text: str, lang: str) -> List[Tuple[int, str]]:
    """(offset, canonical planet name) for every planet mention."""
    hits: List[Tuple[int, str]] = []
    for planet, by_lang in PLANET_STEMS.items():
        stems = by_lang.get(lang, []) + by_lang.get("en", [])
        for off in stem_hits(text, stems):
            hits.append((off, planet))
    return sorted(hits)


def find_planet_spans(text: str, lang: str) -> List[Tuple[int, int, str]]:
    """(start, end, planet) for every planet mention.

    find_planets gives only the start, and the lord-pair scanner has to measure
    the gap between two lords, so it needs to know where the first one ends.
    Where two stems of the same planet overlap, the longer one wins.
    """
    hits: List[Tuple[int, int, str]] = []
    for planet, by_lang in PLANET_STEMS.items():
        for stem in by_lang.get(lang, []) + by_lang.get("en", []):
            for off in stem_hits(text, [stem]):
                hits.append((off, off + len(stem), planet))
    hits.sort()
    kept: List[Tuple[int, int, str]] = []
    for h in hits:
        if kept and h[0] < kept[-1][1]:
            if h[1] - h[0] > kept[-1][1] - kept[-1][0]:
                kept[-1] = h
            continue
        kept.append(h)
    return kept


def find_signs(text: str, lang: str) -> List[Tuple[int, str]]:
    hits: List[Tuple[int, str]] = []
    for sign, by_lang in SIGN_STEMS.items():
        stems = by_lang.get(lang, []) + by_lang.get("en", [])
        for off in stem_hits(text, stems):
            hits.append((off, sign))
    return sorted(hits)


def find_dasha_words(text: str, lang: str) -> List[Tuple[int, str]]:
    hits: List[Tuple[int, str]] = []
    for w in DASHA_WORDS.get(lang, []) + DASHA_WORDS["en"]:
        for off in stem_hits(text, [w]):
            hits.append((off, w))
    return sorted(hits)


def find_maha_words(text: str, lang: str) -> List[Tuple[int, str]]:
    """Offsets of "mahadasha", de-duplicated: the same occurrence must not be
    counted twice because two spellings in the table overlap it."""
    seen: Dict[int, str] = {}
    for w in dict.fromkeys(MAHA_WORDS.get(lang, []) + MAHA_WORDS["en"]):
        for off in stem_hits(text, [w]):
            if not any(abs(off - o) < 6 for o in seen):
                seen[off] = w
    return sorted(seen.items())


def mentions_other_system(seg: str) -> bool:
    low = seg.lower()
    return any(w.lower() in low for w in OTHER_SYSTEM_WORDS)


def mentions_deeper_level(seg: str) -> bool:
    low = seg.lower()
    return any(w.lower() in low for w in DEEPER_LEVEL_WORDS)
