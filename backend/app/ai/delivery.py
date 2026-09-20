"""What actually reaches the client: two checks on the reasoner's output.

1. `scrub()` / `Scrubber` — corrupted text. A small share of Indic answers
   come back from the provider with U+FFFD (the Unicode replacement
   character) followed by an unrelated Latin token glued to it — the tail of
   a byte-level token the model's own decoder could not put back together
   ("## प्रश्न <U+FFFD>DiSC", "**प्रश्न** <U+FFFD>DinosaurMicrosoft"). Nothing in
   this process can reconstruct the character that was lost, but no client
   should ever see the wreckage of it, so it is cut out of the reply and out
   of the SSE stream that carries the reply.

2. `delivers_a_reading()` — money. The client pays for an answer. A turn the
   astrologer ends by asking them to come back with a different, shorter or
   rephrased question delivers nothing, so it is a clarification and free
   (CONTRACT.md: only "ok" turns are billable, and an "ok" turn is one that
   answered). The test is deliberately narrow: every signal has to agree,
   because the expensive mistake is the opposite one — giving a real reading
   away because it happened to end with a question.
"""

import os
import re
from typing import Callable, Dict, List, Optional

REPLACEMENT = "\ufffd"

# U+FFFD plus the Latin run stuck to it. Bounded so a replacement character
# that happens to sit in front of a real English sentence (" <U+FFFD> The
# tenth house...") loses at most one word.
_CORRUPTION = re.compile("[\ufffd\ufffe\uffff]+[A-Za-z]{0,40}")
_LONE_SURROGATE = re.compile(r"[\ud800-\udfff]")

# Longest run `_CORRUPTION` can consume: while the stream still ends inside
# one, the tail is held back instead of being sent to the client.
HOLD_CHARS = 48


def scrub(text: str, lang: str = "en") -> str:
    """Remove corrupted characters (and the junk glued to them) from a reply.

    For an English reply only the replacement character itself goes: the
    Latin text around it is the answer. For every other language a Latin run
    welded to a replacement character is never part of the answer."""
    if not text:
        return text
    text = _LONE_SURROGATE.sub("", text)
    if REPLACEMENT not in text and "\ufffe" not in text and "\uffff" not in text:
        return text
    if lang == "en":
        return re.sub("[\ufffd\ufffe\uffff]+", "", text)
    return _CORRUPTION.sub("", text)


class Scrubber:
    """`scrub()` for a stream: same result as scrubbing the whole reply.

    Deltas arrive in arbitrary pieces, so a corrupted run can straddle two of
    them. Everything that cannot still be part of one is passed straight
    through; the rest waits for the next delta, or for `flush()`."""

    def __init__(self, lang: str, sink: Optional[Callable[[str], None]] = None):
        self.lang, self.sink, self.buf = lang, sink, ""

    def feed(self, delta: str) -> None:
        self.buf += delta or ""
        i = max(self.buf.rfind(c) for c in (REPLACEMENT, "\ufffe", "\uffff"))
        cut = i if 0 <= i and len(self.buf) - i <= HOLD_CHARS else len(self.buf)
        out, self.buf = scrub(self.buf[:cut], self.lang), self.buf[cut:]
        if out and self.sink:
            self.sink(out)

    def flush(self) -> None:
        out, self.buf = scrub(self.buf, self.lang), ""
        if out and self.sink:
            self.sink(out)


# ---------------- did this turn deliver a reading? ----------------

# A real reading is long: the reasoner is given a length target of a few
# hundred words and the mode's minimum output cap is 500 tokens of text /
# 220 of voice. Anything under this is already anomalous for an "ok" turn.
MIN_READING_CHARS = int(os.environ.get("AI_MIN_READING_CHARS", "600"))
MIN_READING_CHARS_VOICE = int(os.environ.get("AI_MIN_READING_CHARS_VOICE", "320"))

# A dated window — the thing the client paid for. Any four-digit year, or a
# run of digits long enough to be a year or a date, counts as content.
_DATED = re.compile(r"(?<!\d)(1[89]\d\d|20\d\d|21\d\d)(?!\d)")

# "Send it again", "pick two or three", "one at a time", "I cannot answer
# this many" — in the six languages the product speaks.
_ASKS_AGAIN = re.compile("|".join([
    # English
    r"\b(re-?send|re-?phrase|re-?word)\b",
    r"\b(ask|send|share|post)\b[^.!?\n]{0,40}\b(again|separately|individually|"
    r"one at a time|next time)\b",
    r"\b(pick|choose|select|narrow)\b[^.!?\n]{0,40}\b(one|two|three|a few|fewer|"
    r"question|questions)\b",
    r"\b(too many|this many|cannot answer all|can.t answer all)\b",
    # Hindi
    r"(फिर से|दोबारा|पुनः)\s*\S{0,12}\s*(पूछ|भेज)",
    r"अलग-अलग\s*\S{0,12}\s*(पूछ|भेज)", r"एक-एक\s*कर",
    r"(चुनकर|चुनकार|छाँटकर)\s*\S{0,12}\s*(पूछ|भेज)",
    r"(दो-तीन|दो या तीन)", r"इतने\s+(सारे\s+)?(प्रश्न|सवाल)",
    # Telugu
    r"(మళ్ళీ|మళ్లీ|తిరిగి)\s*\S{0,14}\s*(అడగ|పంప)",
    r"(విడివిడిగా|ఒక్కొక్కటిగా|ఒక్కొక్క)",
    r"(ఎంచుకుని|ఎంచుకొని|ఎంపిక చేసి)\s*\S{0,14}\s*(అడగ|పంప)",
    r"(రెండు-మూడు|రెండు లేదా మూడు)", r"ఇన్ని\s+ప్రశ్నల",
    # Tamil
    r"(மீண்டும்|திரும்ப)\s*\S{0,14}\s*(கேள|அனுப்ப)",
    r"(தனித்தனியாக|ஒவ்வொன்றாக)",
    r"(தேர்ந்தெடுத்து|தேர்வு செய்து)\s*\S{0,14}\s*(கேள|அனுப்ப)",
    r"(இரண்டு-மூன்று|இரண்டு அல்லது மூன்று)", r"இத்தனை\s+கேள்வி",
    # Kannada
    r"(ಮತ್ತೆ|ಮರಳಿ|ಪುನಃ)\s*\S{0,14}\s*(ಕೇಳ|ಕಳುಹಿಸ)",
    r"(ಪ್ರತ್ಯೇಕವಾಗಿ|ಒಂದೊಂದಾಗಿ)",
    r"(ಆಯ್ಕೆ ಮಾಡಿ|ಆರಿಸಿ)\s*\S{0,14}\s*(ಕೇಳ|ಕಳುಹಿಸ)",
    r"(ಎರಡು-ಮೂರು|ಎರಡು ಅಥವಾ ಮೂರು)", r"ಇಷ್ಟು\s+ಪ್ರಶ್ನೆ",
    # Malayalam
    r"(വീണ്ടും|തിരികെ)\s*\S{0,14}\s*(ചോദി|അയയ്?ക്ക)",
    r"(വെവ്വേറെ|ഒന്നൊന്നായി)",
    r"(തിരഞ്ഞെടുത്ത്|തെരഞ്ഞെടുത്ത്)\s*\S{0,14}\s*(ചോദി|അയയ്?ക്ക)",
    r"(രണ്ട്-മൂന്ന്|രണ്ടോ മൂന്നോ)", r"ഇത്രയും\s+ചോദ്യ",
]), re.I)


def asks_the_client_to_resend(reply: str) -> bool:
    return bool(_ASKS_AGAIN.search(reply or ""))


def delivers_a_reading(reply: str, *, mode: str = "text") -> bool:
    """True unless this "ok" turn quite clearly answered nothing.

    All three have to agree before a turn is downgraded to a free
    clarification: it is far shorter than any real reading, it names no year
    at all, and it asks the client to come back with a different question.
    A real answer that happens to end with a question keeps every one of
    those tests on the "charge" side, because it is long and dated."""
    text = (reply or "").strip()
    if not text:
        return False
    floor = MIN_READING_CHARS_VOICE if mode == "voice" else MIN_READING_CHARS
    if len(text) >= floor:
        return True
    if _DATED.search(text):
        return True
    return not asks_the_client_to_resend(text)


# ---------------- English left in an Indic reply ----------------

# reasoner.SYSTEM forbids Latin letters outside an English consultation, and
# the evaluation still found "D-10", "KP", "SAV", "Birth Time Rectification",
# "commitment" in Indic answers. A rule nothing checks is a rule that decays,
# so the leak is measured on every turn and the two purely mechanical cases
# are repaired.
#
# Only substitutions whose replacement is already a reviewed string are made
# here: chart_kinds.kp and chart_kinds.varga_one come out of
# app/features/i18n/*.json. Everything else is recorded, never machine-
# translated mid-reply -- a wrong word inside a paid reading is worse than an
# English one, and the trace makes the rest visible to whoever owns the prompt.
_VARGA = re.compile(r"\bD[-– ]?(\d{1,2})\b")
_KP = re.compile(r"\bK\.?\s?P\.?(?=[\s,.:;)\]]|$)")
# A Latin run worth reporting: two or more letters. One letter is usually a
# house or a list marker and is noise.
_LATIN_RUN = re.compile(r"[A-Za-z][A-Za-z'’-]+")


def localize_jargon(text: str, lang: str) -> str:
    """Replace the mechanical English jargon with its reviewed local term."""
    if not text or lang == "en":
        return text
    from ..features import common
    try:
        kp = common.t(lang, "chart_kinds.kp")
        varga = common.t(lang, "chart_kinds.varga_one")
    except (KeyError, OSError):          # missing language file: leave it be
        return text
    text = _VARGA.sub(lambda m: "%s %s" % (m.group(1), varga), text)
    return _KP.sub(kp, text)


def latin_leaks(text: str, lang: str) -> List[str]:
    """Latin words still in a reply that should carry none, longest first."""
    if not text or lang == "en":
        return []
    seen: Dict[str, int] = {}
    for m in _LATIN_RUN.finditer(text):
        w = m.group(0)
        seen[w] = seen.get(w, 0) + 1
    return sorted(seen, key=lambda w: (-len(w), w))[:12]
