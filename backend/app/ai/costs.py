"""Provider price table and cost math — the ONLY place prices live.

All prices are USD list prices (no free tiers, no committed-use discounts, so
real bills can only be lower). Converted to paise with USD_TO_INR.

Sources, checked 2026-09-18:
  * Claude Opus 4.5 on the first-party Anthropic API: $5 / $25 per Mtok
    in/out; cache reads 0.1x input, 5-minute cache writes 1.25x input.
    https://platform.claude.com/docs/en/pricing
  * Gemini 2.5 Flash (Gemini API paid tier; Vertex list price is the same): $0.30 / Mtok text input, $2.50 / Mtok
    output (thinking tokens are billed as output), $0.03 / Mtok cached input.
    Flash-Lite $0.10 / $0.40. Gemini 3 Flash (preview) $0.50 / $3.00.
    https://cloud.google.com/vertex-ai/generative-ai/pricing (+ ai.google.dev
    /gemini-api/docs/pricing, which matches for these models).
  * Cloud Speech-to-Text V2, standard recognition (Chirp / Chirp 2 /
    Chirp 3 / long): $0.016 per minute, billed per second.
    https://cloud.google.com/speech-to-text/pricing
  * Cloud Text-to-Speech: Standard voices $4 per 1M characters. WaveNet is
    listed by third parties at $4/1M since early 2026 but historically $16/1M;
    we budget the conservative $16 until the owner confirms on the pricing
    page. Premium tiers (Neural2 $16, Chirp 3 HD $30, Studio $160) are not
    allowed on this path. https://cloud.google.com/text-to-speech/pricing

If Google/Anthropic change prices, edit PRICES and nothing else.
"""

import math
import os
from typing import Dict, Optional

USD_TO_INR = float(os.environ.get("USD_TO_INR", "90"))

# USD per 1M tokens (LLMs), per minute (stt:*), per 1M characters (tts:*).
PRICES: Dict[str, Dict[str, float]] = {
    # --- Claude (first-party Anthropic API) ---
    "claude-opus-4-5": {"in": 5.00, "out": 25.00,
                        "cache_read": 0.50, "cache_write": 6.25},
    "claude-opus-4-5-20251101": {"in": 5.00, "out": 25.00,
                                 "cache_read": 0.50, "cache_write": 6.25},
    # Opus 5 lists at the SAME per-token price as 4.5. It is not automatically
    # the same cost per query: adaptive thinking is on by default there and
    # thinking tokens bill as output, so a query's output token count (and so
    # its cost) can be higher at identical answer length. Measure with
    # scripts/agent_bench.py before switching CLAUDE_MODEL — see
    # docs/launch/AGENT_BENCH.md "Opus 4.5 vs Opus 5".
    "claude-opus-5": {"in": 5.00, "out": 25.00,
                      "cache_read": 0.50, "cache_write": 6.25},
    # --- Gemini (text input; <=200k context) ---
    # Gemini API paid tier, checked 2026-09-19 (ai.google.dev/gemini-api/docs/pricing).
    # 2.5 Flash / Flash-Lite are closed to new accounts; 3.5 Flash-Lite is the
    # default (same price as 2.5 Flash). 3.6-3.8 Flash are promo-priced until
    # 2026-12-31 and double after -- the rows below use the post-promo price
    # so the budget guard never under-estimates.
    "gemini-3.5-flash-lite": {"in": 0.30, "out": 2.50, "cache_read": 0.03},
    "gemini-3.1-flash-lite": {"in": 0.25, "out": 1.50, "cache_read": 0.025},
    "gemini-3.5-flash": {"in": 1.50, "out": 9.00, "cache_read": 0.15},
    "gemini-3.6-flash": {"in": 1.50, "out": 7.50, "cache_read": 0.15},
    "gemini-3.7-flash": {"in": 1.50, "out": 7.50, "cache_read": 0.15},
    "gemini-3.8-flash": {"in": 1.50, "out": 7.50, "cache_read": 0.15},
    "gemini-2.5-flash": {"in": 0.30, "out": 2.50, "cache_read": 0.03},
    "gemini-2.5-flash-lite": {"in": 0.10, "out": 0.40, "cache_read": 0.01},
    "gemini-3-flash-preview": {"in": 0.50, "out": 3.00, "cache_read": 0.05},
    # --- Speech ---
    "stt:chirp_3": {"per_min": 0.016},
    "stt:chirp_2": {"per_min": 0.016},
    "stt:chirp": {"per_min": 0.016},
    "stt:long": {"per_min": 0.016},
    "stt:latest_long": {"per_min": 0.024},   # V1 pricing, if someone picks V1
    "tts:standard": {"per_mchar": 4.00},
    "tts:wavenet": {"per_mchar": 16.00},    # conservative, see docstring
}

# Unknown ids are billed at the most expensive row of their family so a
# config typo can never make the budget guard optimistic.
_FALLBACK = {
    "claude": {"in": 15.00, "out": 75.00, "cache_read": 1.50, "cache_write": 18.75},
    "gemini": {"in": 1.25, "out": 10.00, "cache_read": 0.125},
    "stt": {"per_min": 0.024},
    "tts": {"per_mchar": 16.00},
}



def price(model: str) -> Dict[str, float]:
    p = PRICES.get(model)
    if p is None:
        bare = model.split("@", 1)[0]
        p = next((v for k, v in PRICES.items() if k.split("@", 1)[0] == bare), None)
    if p is None:
        fam = ("claude" if "claude" in model else "stt" if model.startswith("stt:")
               else "tts" if model.startswith("tts:") else "gemini")
        p = _FALLBACK[fam]
    return p


def usd_to_paise(usd: float) -> float:
    return usd * USD_TO_INR * 100.0


def per_token_paise(model: str, kind: str = "in") -> float:
    """Paise per single token of `kind` (in|out|cache_read|cache_write)."""
    p = price(model)
    return usd_to_paise(p.get(kind, p["in"]) / 1e6)


def llm_cost(model: str, in_tok: int = 0, out_tok: int = 0,
             cache_read_tok: int = 0, cache_write_tok: int = 0) -> float:
    """Exact cost in paise (float). `in_tok` excludes cached tokens."""
    p = price(model)
    usd = (in_tok * p["in"] + out_tok * p["out"]
           + cache_read_tok * p.get("cache_read", p["in"])
           + cache_write_tok * p.get("cache_write", p["in"])) / 1e6
    return usd_to_paise(usd)


def stt_cost(model: str, seconds: float) -> float:
    """V2 bills per second (we round up to whole seconds, minimum 1s)."""
    secs = max(1, int(math.ceil(seconds)))
    return usd_to_paise(price("stt:" + model)["per_min"] * secs / 60.0)


def tts_tier(voice_name: str) -> Optional[str]:
    """'standard' | 'wavenet' | None (premium or unknown — not allowed)."""
    n = (voice_name or "").lower()
    if "-standard-" in n:
        return "standard"
    if "-wavenet-" in n:
        return "wavenet"
    return None


def tts_cost(tier: str, chars: int) -> float:
    return usd_to_paise(price("tts:" + tier)["per_mchar"] * chars / 1e6)


def tts_paise_per_char(tier: str) -> float:
    return usd_to_paise(price("tts:" + tier)["per_mchar"] / 1e6)


def units(cost_paise: float) -> int:
    """Integer paise for traces/rollups; rounds UP so we never under-report."""
    return int(math.ceil(cost_paise - 1e-9)) if cost_paise > 0 else 0


# ---------------- token estimation (fallback when count_tokens fails) -------
#
# Deliberately pessimistic chars-per-token ratios. Claude's (pre-4.7) and
# Gemini's tokenizers split Dravidian scripts into roughly one token per 1-2
# code points (virama conjuncts and vowel signs are separate code points), and
# Devanagari into ~1.5-2.5; ASCII English/JSON runs ~3.5-4.5 chars/token. We
# assume the dense end of every range, so an estimate is an upper bound.

_DRAVIDIAN = ((0x0C00, 0x0C7F), (0x0B80, 0x0BFF), (0x0C80, 0x0CFF), (0x0D00, 0x0D7F))
_DEVANAGARI = (0x0900, 0x097F)
CHARS_PER_TOKEN = {"dravidian": 1.0, "devanagari": 1.4, "ascii": 3.0, "other": 1.5}


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    counts = {"dravidian": 0, "devanagari": 0, "ascii": 0, "other": 0}
    for ch in text:
        cp = ord(ch)
        if cp < 128:
            counts["ascii"] += 1
        elif _DEVANAGARI[0] <= cp <= _DEVANAGARI[1]:
            counts["devanagari"] += 1
        elif any(lo <= cp <= hi for lo, hi in _DRAVIDIAN):
            counts["dravidian"] += 1
        else:
            counts["other"] += 1
    tok = sum(n / CHARS_PER_TOKEN[k] for k, n in counts.items())
    return int(math.ceil(tok)) + 4


# Upper bound on characters per *output* token when reserving TTS cost before
# the reply exists (Indic replies are ~1-2 chars/token; 3 leaves headroom for
# numerals and Latin astrology terms).
TTS_CHARS_PER_OUT_TOKEN = float(os.environ.get("TTS_CHARS_PER_OUT_TOKEN", "3.0"))

# Rough output tokens per written word, per language, used only to tell Opus a
# target length that lands inside max_tokens (the probe script measures the
# real ratio — update these from its output).
TOKENS_PER_WORD = {"hi": 3.7, "te": 6.5, "ta": 6.9, "kn": 13.7, "ml": 5.2, "en": 1.8}
