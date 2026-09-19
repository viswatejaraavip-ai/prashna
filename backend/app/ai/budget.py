"""Per-query cost ceiling (CONTRACT: total provider cost < ₹5).

Everything before the reasoning call is either already spent (STT, plan,
brief — actual usage is known) or reserved at its worst case (the memory
update after the answer, and cloud TTS of the not-yet-written reply). Opus's
`max_tokens` is then the largest value that keeps

    spent + reserves + opus_in + max_tokens * (opus_out + tts_per_token) <= limit

where limit = ceiling * (1 - safety margin). Since max_tokens is a hard cap
on output tokens and input tokens are counted (or pessimistically
estimated) before the call, the ceiling cannot be exceeded by the model.
"""

import math
import os
from typing import Dict, List, Optional

from . import costs, llm

SAFETY = float(os.environ.get("QUERY_COST_SAFETY", "0.05"))
# Opus output caps by mode (upper bound; the budget usually binds first).
TEXT_MAX_OUTPUT_TOKENS = int(os.environ.get("TEXT_MAX_OUTPUT_TOKENS", "1400"))
VOICE_MAX_OUTPUT_TOKENS = int(os.environ.get("VOICE_MAX_OUTPUT_TOKENS", "450"))
# Below these we shrink context instead of answering in a stub.
TEXT_MIN_OUTPUT_TOKENS = int(os.environ.get("TEXT_MIN_OUTPUT_TOKENS", "500"))
VOICE_MIN_OUTPUT_TOKENS = int(os.environ.get("VOICE_MIN_OUTPUT_TOKENS", "220"))

# Worst case of the post-answer memory update (Flash): input is capped by
# memory.py (summary + facts + question + answer, truncated) and output by
# its max_output_tokens.
MEMORY_MAX_IN_TOKENS = 4000
MEMORY_MAX_OUT_TOKENS = 600


class Budget:
    def __init__(self, ceiling_units: int, safety: float = SAFETY):
        self.ceiling = float(ceiling_units)
        self.limit = self.ceiling * (1.0 - safety)
        self.spent: Dict[str, float] = {}
        self.reserved: Dict[str, float] = {}

    def add(self, stage) -> None:
        self.spent[stage.name] = self.spent.get(stage.name, 0.0) + stage.cost

    def reserve(self, name: str, paise: float) -> None:
        self.reserved[name] = paise

    def release(self, name: str) -> None:
        self.reserved.pop(name, None)

    @property
    def total_spent(self) -> float:
        return sum(self.spent.values())

    def remaining(self) -> float:
        return self.limit - self.total_spent - sum(self.reserved.values())

    def over(self) -> bool:
        return self.total_spent > self.ceiling


def memory_reserve(model: Optional[str] = None) -> float:
    m = model or llm.GEMINI_MODEL
    return costs.llm_cost(m, MEMORY_MAX_IN_TOKENS, MEMORY_MAX_OUT_TOKENS)


def opus_output_cap(remaining_paise: float, in_tokens: int, *, tts_tier: Optional[str],
                    mode_max: int, model: Optional[str] = None) -> int:
    """Largest max_tokens affordable after paying for `in_tokens` of input
    (and, for cloud voice, speaking every output token)."""
    m = model or llm.CLAUDE_MODEL
    in_cost = in_tokens * costs.per_token_paise(m, "in")
    per_out = costs.per_token_paise(m, "out")
    if tts_tier:
        per_out += costs.TTS_CHARS_PER_OUT_TOKEN * costs.tts_paise_per_char(tts_tier)
    left = remaining_paise - in_cost
    if left <= 0:
        return 0
    return max(0, min(mode_max, int(math.floor(left / per_out))))


def brief_input_cap_tokens(remaining_paise: float, brief_out_tokens: int,
                           reason_reserve_paise: float,
                           model: Optional[str] = None) -> int:
    """How many raw-tool-JSON tokens the brief call may read, leaving
    `reason_reserve_paise` for the Opus stage."""
    m = model or llm.GEMINI_MODEL
    left = remaining_paise - reason_reserve_paise - brief_out_tokens * costs.per_token_paise(m, "out")
    return max(0, int(left / costs.per_token_paise(m, "in")))


def summary(b: Budget) -> Dict:
    return {"ceiling": b.ceiling, "limit": round(b.limit, 2),
            "spent": {k: round(v, 3) for k, v in b.spent.items()},
            "reserved": {k: round(v, 3) for k, v in b.reserved.items()}}
