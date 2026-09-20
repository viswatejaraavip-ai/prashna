"""Thin model wrappers: Gemini Flash (google-genai, Gemini API key) and Claude
Opus 4.5 (first-party Anthropic API, ANTHROPIC_API_KEY). Every call returns a `Stage` with tokens,
latency and cost so the pipeline can trace and budget it.

Clients are created lazily and can be swapped with `set_clients()` (tests,
the cost probe) — nothing here talks to the network at import time.
"""

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import costs

log = logging.getLogger("udhyath.ai.llm")

GCP_PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", os.environ.get("GCP_PROJECT", ""))
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")
GEMINI_LOCATION = os.environ.get("GEMINI_LOCATION", "global")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
# Gemini defaults to the Gemini Developer API (paid tier) with GEMINI_API_KEY;
# set GEMINI_USE_VERTEX=1 to route it through Vertex AI with ADC instead.
GEMINI_USE_VERTEX = os.environ.get("GEMINI_USE_VERTEX", "").lower() in ("1", "true", "yes")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
# 0 disables thinking on 2.5 Flash; plan/brief/memory are extraction jobs.
GEMINI_THINKING_BUDGET = int(os.environ.get("GEMINI_THINKING_BUDGET", "0"))
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-4-5")
# low|medium|high (+ xhigh|max on Opus 5) | "" (off). Sent as
# output_config.effort; dropped automatically if the API rejects it.
CLAUDE_EFFORT = os.environ.get("CLAUDE_EFFORT", "medium").strip().lower()
# "" = send nothing and take the model's default; "adaptive" or "disabled" to
# force one. The default differs by model and it changes the bill:
#   Opus 4.5 — thinking is OFF unless asked for. That is today's behaviour and
#              what the ₹5 ceiling was sized against.
#   Opus 5   — thinking is ADAPTIVE unless disabled, and thinking tokens bill
#              as OUTPUT ($25/Mtok) and are spent inside max_tokens. So the
#              same answer can cost more and, at a tight max_tokens, be
#              truncated by its own reasoning.
# `budget_tokens` does not exist on either model (400 on Opus 5) — depth is
# controlled with effort, never a token budget.
CLAUDE_THINKING = os.environ.get("CLAUDE_THINKING", "").strip().lower()
CLAUDE_TIMEOUT_S = float(os.environ.get("CLAUDE_TIMEOUT_S", "120"))

# Models whose default is adaptive thinking (output tokens include reasoning).
THINKS_BY_DEFAULT = ("claude-opus-5", "claude-opus-4-8", "claude-opus-4-7",
                     "claude-sonnet-5", "claude-fable-5")


def thinks_by_default(model: Optional[str] = None) -> bool:
    m = model or CLAUDE_MODEL
    if CLAUDE_THINKING == "adaptive":
        return True
    if CLAUDE_THINKING == "disabled":
        return False
    return m.startswith(THINKS_BY_DEFAULT)


_gemini = None
_claude = None
_effort_supported: Optional[bool] = None if CLAUDE_EFFORT else False
_thinking_supported: Optional[bool] = None if CLAUDE_THINKING else False
_count_tokens_ok: Optional[bool] = None


def set_clients(gemini: Any = None, claude: Any = None) -> None:
    """Inject clients (tests / probe). Pass None to leave one unchanged."""
    global _gemini, _claude
    if gemini is not None:
        _gemini = gemini
    if claude is not None:
        _claude = claude


def reset_capabilities() -> None:
    global _effort_supported, _count_tokens_ok, _thinking_supported
    _effort_supported = None if CLAUDE_EFFORT else False
    _thinking_supported = None if CLAUDE_THINKING else False
    _count_tokens_ok = None


def gemini():
    global _gemini
    if _gemini is None:
        from google import genai
        if GEMINI_USE_VERTEX:
            _gemini = genai.Client(vertexai=True, project=GCP_PROJECT or None,
                                   location=GEMINI_LOCATION)
        else:
            _gemini = genai.Client(api_key=GEMINI_API_KEY or None)
    return _gemini


def claude():
    global _claude
    if _claude is None:
        from anthropic import Anthropic
        _claude = Anthropic(api_key=ANTHROPIC_API_KEY or None,
                            timeout=CLAUDE_TIMEOUT_S, max_retries=1)
    return _claude


# ---------------- Cloud Run warm-up ----------------
# Both SDKs keep a pooled HTTPS connection per client, so the first query on a
# cold instance otherwise pays SDK import + TLS handshake (~0.5-1.5 s) inside
# the user's latency. Building the clients at startup moves that off the
# critical path; the connections are then reused for the instance's life.

WARM_CLIENTS = os.environ.get("AI_WARM_CLIENTS", "1") != "0"
_warmed = False


def warm_clients() -> None:
    """Build both SDK clients (and prime the Anthropic connection pool).

    Safe to call repeatedly and from any thread; never raises."""
    global _warmed
    if _warmed:
        return
    _warmed = True
    t0 = time.time()
    for name, build in (("gemini", gemini), ("claude", claude)):
        try:
            build()
        except Exception as exc:
            log.warning("warm-up: %s client unavailable (%s)", name, exc)
    if ANTHROPIC_API_KEY:
        # Cheapest authenticated round trip there is: opens the TLS
        # connection the first real query will reuse. Never billed.
        try:
            claude().with_options(timeout=5.0, max_retries=0).messages.count_tokens(
                model=CLAUDE_MODEL, messages=[{"role": "user", "content": "ping"}])
        except Exception as exc:
            log.info("warm-up ping skipped (%s)", exc)
    log.info("ai clients warm in %d ms", int((time.time() - t0) * 1000))


def warm_clients_async() -> None:
    """Warm the clients in a daemon thread (called at app startup).

    A no-op without provider keys, so importing the app in a test or on a
    laptop never reaches out to the network."""
    if not WARM_CLIENTS or _warmed:
        return
    if not (ANTHROPIC_API_KEY or GEMINI_API_KEY or GEMINI_USE_VERTEX):
        return
    import threading
    threading.Thread(target=warm_clients, name="ai-warmup", daemon=True).start()


@dataclass
class Stage:
    """One entry of traces.stages (see CONTRACT.md)."""
    name: str
    model: str = ""
    in_tok: int = 0
    out_tok: int = 0
    cache_read_tok: int = 0
    cache_write_tok: int = 0
    cost: float = 0.0            # paise, exact float
    latency_ms: int = 0
    units: float = 0             # stt seconds / tts characters
    detail: Dict = field(default_factory=dict)

    def to_trace(self) -> Dict:
        d: Dict[str, Any] = {"name": self.name, "latency_ms": self.latency_ms,
                             "cost_units": costs.units(self.cost)}
        if self.model:
            d["model"] = self.model
        if self.name in ("stt", "tts"):
            d["units"] = self.units
        elif self.model:
            d.update(in_tok=self.in_tok, out_tok=self.out_tok)
            if self.name == "reason" or self.cache_read_tok:
                d["cache_read_tok"] = self.cache_read_tok
            if self.cache_write_tok:
                d["cache_write_tok"] = self.cache_write_tok
        if self.detail:
            d["detail"] = self.detail
        return d


# ---------------- Gemini Flash ----------------

def _thinking_config(model: str) -> Optional[Dict]:
    if model.startswith("gemini-2.5"):
        return {"thinking_budget": GEMINI_THINKING_BUDGET}
    if model.startswith("gemini-3"):
        return {"thinking_level": os.environ.get("GEMINI_THINKING_LEVEL", "minimal")}
    return None


def _gemini_usage(resp) -> Dict[str, int]:
    um = getattr(resp, "usage_metadata", None)
    g = (lambda k: int(getattr(um, k, 0) or 0)) if um is not None else (lambda k: 0)
    prompt = g("prompt_token_count")
    cached = g("cached_content_token_count")
    out = g("candidates_token_count") + g("thoughts_token_count")
    return {"in": max(0, prompt - cached), "cached": cached, "out": out}


def flash(name: str, system: str, user: str, *, max_output_tokens: int,
          schema: Optional[Dict] = None, temperature: float = 0.2,
          model: Optional[str] = None) -> Tuple[Any, Stage]:
    """One Gemini call. Returns (parsed JSON dict | text, Stage).

    Raises on transport errors; the caller decides whether to fail open."""
    model = model or GEMINI_MODEL
    config: Dict[str, Any] = {"system_instruction": system,
                              "max_output_tokens": max_output_tokens,
                              "temperature": temperature}
    tc = _thinking_config(model)
    if schema is not None:
        config["response_mime_type"] = "application/json"
        config["response_schema"] = schema
    # If the SDK/model rejects our thinking knob, fall back to the other
    # knob, then to none (thinking tokens are billed as output and traced,
    # so a fallback can cost more but never goes unrecorded).
    fallbacks = [tc] if tc else [None]
    if tc and "thinking_level" in tc:
        fallbacks.append({"thinking_budget": GEMINI_THINKING_BUDGET})
    if tc:
        fallbacks.append(None)
    t0 = time.time()
    for i, cfg in enumerate(fallbacks):
        if cfg is None:
            config.pop("thinking_config", None)
        else:
            config["thinking_config"] = cfg
        try:
            resp = gemini().models.generate_content(model=model, contents=user,
                                                    config=config)
            break
        except Exception as exc:
            msg = str(exc)
            if i + 1 < len(fallbacks) and ("thinking" in msg.lower() or "INVALID_ARGUMENT" in msg):
                log.warning("gemini rejected thinking config %s: %s", cfg, exc)
                continue
            raise
    u = _gemini_usage(resp)
    stage = Stage(name=name, model=model, in_tok=u["in"], out_tok=u["out"],
                  cache_read_tok=u["cached"],
                  cost=costs.llm_cost(model, u["in"], u["out"], u["cached"]),
                  latency_ms=int((time.time() - t0) * 1000))
    text = getattr(resp, "text", None) or ""
    if schema is None:
        return text.strip(), stage
    return parse_json(text), stage


def parse_json(text: str) -> Dict:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text)
    try:
        val = json.loads(text)
    except ValueError:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            raise
        val = json.loads(m.group(0))
    if not isinstance(val, dict):
        raise ValueError("expected a JSON object")
    return val


# ---------------- Claude Opus 4.5 ----------------

def count_tokens(system: List[Dict], messages: List[Dict],
                 model: Optional[str] = None) -> Optional[int]:
    """Exact input tokens via the Anthropic count-tokens endpoint, or None if unavailable.
    Remembers a failure so we don't pay the round trip on every query."""
    global _count_tokens_ok
    if _count_tokens_ok is False or os.environ.get("CLAUDE_COUNT_TOKENS", "1") == "0":
        return None
    try:
        r = claude().with_options(timeout=4.0, max_retries=0).messages.count_tokens(
            model=model or CLAUDE_MODEL, system=system, messages=messages)
        _count_tokens_ok = True
        return int(r.input_tokens)
    except Exception as exc:
        if _count_tokens_ok is None:
            log.warning("count_tokens unavailable (%s); using estimates", exc)
            _count_tokens_ok = False
        return None


def _is_bad_request(exc: Exception) -> bool:
    return getattr(exc, "status_code", None) == 400 or type(exc).__name__ == "BadRequestError"


def opus(name: str, system: List[Dict], messages: List[Dict], *, max_tokens: int,
         on_delta: Optional[Callable[[str], None]] = None,
         model: Optional[str] = None, effort: Optional[str] = None) -> Tuple[str, str, Stage]:
    """Streamed Opus call (streaming avoids HTTP timeouts on long outputs and
    feeds SSE). Thinking stays OFF (Opus 4.5 default) for cost.

    Returns (text, stop_reason, Stage). `Stage.detail["ttft_ms"]` is the time
    to the first streamed token — the number the user actually feels."""
    global _effort_supported, _thinking_supported
    model = model or CLAUDE_MODEL
    eff = CLAUDE_EFFORT if effort is None else effort
    kwargs: Dict[str, Any] = dict(model=model, max_tokens=int(max_tokens),
                                  system=system, messages=messages)
    if eff and _effort_supported is not False:
        kwargs["output_config"] = {"effort": eff}
    if CLAUDE_THINKING and _thinking_supported is not False:
        # Only sent when explicitly configured; otherwise the model's own
        # default applies (off on Opus 4.5, adaptive on Opus 5).
        kwargs["thinking"] = {"type": CLAUDE_THINKING}
    t0 = time.time()
    parts: List[str] = []
    ttft_ms = 0
    for attempt in (1, 2, 3):
        try:
            parts = []
            with claude().messages.stream(**kwargs) as stream:
                for delta in stream.text_stream:
                    if not parts:
                        ttft_ms = int((time.time() - t0) * 1000)
                    parts.append(delta)
                    if on_delta:
                        on_delta(delta)
                final = stream.get_final_message()
            if "output_config" in kwargs:
                _effort_supported = True
            if "thinking" in kwargs:
                _thinking_supported = True
            break
        except Exception as exc:
            # Drop optional knobs one at a time rather than failing the query:
            # `thinking` and `output_config.effort` are both model-dependent
            # (e.g. thinking cannot be disabled above effort "high" on Opus 5).
            if parts or not _is_bad_request(exc):
                raise
            if "thinking" in kwargs:
                log.warning("Claude API rejected thinking=%s on %s (%s); "
                            "using the model default", CLAUDE_THINKING, model, exc)
                _thinking_supported = False
                kwargs.pop("thinking")
                continue
            if "output_config" in kwargs:
                log.warning("Claude API rejected output_config.effort (%s); "
                            "continuing without it", exc)
                _effort_supported = False
                kwargs.pop("output_config")
                continue
            raise
    usage = final.usage
    in_tok = int(getattr(usage, "input_tokens", 0) or 0)
    out_tok = int(getattr(usage, "output_tokens", 0) or 0)
    cr = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
    cw = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
    stage = Stage(name=name, model=model, in_tok=in_tok, out_tok=out_tok,
                  cache_read_tok=cr, cache_write_tok=cw,
                  cost=costs.llm_cost(model, in_tok, out_tok, cr, cw),
                  latency_ms=int((time.time() - t0) * 1000),
                  detail={"ttft_ms": ttft_ms,
                          "effort": kwargs.get("output_config", {}).get("effort", ""),
                          "thinking": kwargs.get("thinking", {}).get(
                              "type", "default-on" if thinks_by_default(model)
                              else "default-off")})
    text = "".join(b.text for b in final.content
                   if getattr(b, "type", "") == "text") or "".join(parts)
    return text.strip(), str(getattr(final, "stop_reason", "") or ""), stage
