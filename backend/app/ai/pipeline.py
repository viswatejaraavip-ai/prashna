"""Per-query orchestration: pre-filters -> plan (Flash) -> tools + brief
(Flash) -> reason (Opus 4.5, budget-capped) -> [TTS] -> charge -> memory
(Flash) -> trace + rollups.

Money rules (CONTRACT.md):
* the user pays flags.query_price_units (default ₹10) only when the planner
  said "ok" and Opus produced an answer; refused/clarify/error turns are free;
* balance is checked BEFORE any tokens are spent; the charge happens after
  the answer. If the charge then fails (race with another device, billing
  outage) the answer is still delivered and the failure is recorded in the
  trace (`charge_error`) — we never pay for tokens twice;
* provider cost is kept under flags.cost_ceiling_units by budget.py; the
  actual cost is written to the trace and status is "over_ceiling" if it
  ever exceeds it.
"""

import base64
import logging
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from typing import Callable, Dict, List, Optional, Tuple

from .. import guard, store
from . import budget as budget_mod
from . import clock, executor, llm, memory, planner, reasoner, repo, speech

log = logging.getLogger("udhyath.ai.pipeline")

AI_RATE_LIMIT = int(os.environ.get("AI_RATE_LIMIT_PER_5MIN", "10"))
# Free (unbilled) turns per session: after SOFT the planner's free replies
# are replaced by a canned nudge; after HARD no model is called at all.
FREE_TURNS_SOFT = int(os.environ.get("FREE_TURNS_SOFT", "4"))
FREE_TURNS_HARD = int(os.environ.get("FREE_TURNS_HARD", "12"))
# The memory update, the message/session writes, the trace and the rollups all
# happen AFTER the user has their answer. Running them on a background thread
# takes the whole tail (a Flash call plus ~5 Firestore writes) out of the
# user's wall clock. Set AI_ASYNC_TAIL=0 to go back to inline bookkeeping.
ASYNC_TAIL = os.environ.get("AI_ASYNC_TAIL", "1") != "0"
TAIL_TIMEOUT_S = float(os.environ.get("AI_TAIL_TIMEOUT_S", "60"))


class AiError(Exception):
    """Maps to an HTTP error {"detail", "code"} in routes_ai."""

    def __init__(self, status_code: int, code: str, detail: str):
        super().__init__(detail)
        self.status_code, self.code, self.detail = status_code, code, detail


@dataclass
class Result:
    reply: str
    status: str
    trace_id: str
    charged_units: int = 0
    balance_units: int = 0
    transcript: Optional[str] = None
    audio_b64: Optional[str] = None
    trace: Dict = field(default_factory=dict)
    tail: Optional[threading.Thread] = None
    # Filled by the background tail: the rolled-up session summary and the
    # per-profile memory this turn produced (what the next turn will read).
    summary: str = ""
    facts: List[str] = field(default_factory=list)

    def wait(self, timeout: Optional[float] = None) -> "Result":
        """Block until the background bookkeeping (memory, trace, rollups)
        has finished, so `trace` is final. Tests and the benchmark use it;
        the request path never needs to."""
        if self.tail is not None:
            self.tail.join(timeout if timeout is not None else TAIL_TIMEOUT_S)
        return self


def flags() -> Dict:
    return store.get_flags()


def price_units(f: Optional[Dict] = None) -> int:
    return int((f or flags()).get("query_price_units", 1000))


def precheck(uid: str, *, voice_cloud: bool = False, dry_run: bool = False,
             f: Optional[Dict] = None) -> Dict:
    f = f or flags()
    if f.get("maintenance_message"):
        raise AiError(503, "maintenance", f["maintenance_message"])
    if not f.get("opus_enabled", True):
        raise AiError(503, "maintenance",
                      "Consultations are paused for a short while. Please try again later.")
    if voice_cloud and not f.get("voice_cloud_enabled", True):
        raise AiError(503, "maintenance",
                      "Cloud voice is unavailable; please use on-device voice.")
    if dry_run:
        return f
    if not guard.rate_ok("ai:" + uid, limit=AI_RATE_LIMIT, window_s=300):
        raise AiError(429, "rate_limited",
                      "You're asking very fast — please wait a minute.")
    if repo.get_balance(uid) < price_units(f):
        raise AiError(402, "insufficient_balance",
                      "An answer costs ₹%d — please top up your wallet."
                      % (price_units(f) // 100))
    return f


def _billing():
    from .. import billing  # platform workstream; imported lazily
    return billing


def _charge(uid: str, units_: int, trace_id: str) -> Tuple[int, Optional[str]]:
    """Returns (charged_units, error). Never raises."""
    try:
        b = _billing()
        insufficient = getattr(b, "InsufficientBalance", None)
        try:
            b.charge(uid, units_, type="query", ref=trace_id)
            return units_, None
        except Exception as exc:
            if insufficient is not None and isinstance(exc, insufficient):
                return 0, "insufficient_balance"
            raise
    except Exception as exc:
        log.error("charge failed uid=%s trace=%s: %s", uid, trace_id, exc)
        return 0, "charge_failed: %s" % str(exc)[:200]


def run_query(uid: str, session: Dict, text: str = "", *,
              audio: Optional[bytes] = None, want_tts: bool = False,
              on_delta: Optional[Callable[[str], None]] = None,
              on_done: Optional[Callable[[Dict, str], None]] = None,
              dry_run: bool = False, prechecked: Optional[Dict] = None,
              profile: Optional[Dict] = None, memory_facts: Optional[List[str]] = None,
              ) -> Result:
    """Answer one user turn. `session` is the sessions doc (with "id")."""
    f = prechecked or precheck(uid, voice_cloud=audio is not None, dry_run=dry_run)
    t0 = time.time()
    trace_id = uuid.uuid4().hex
    lang = session.get("lang") or store.DEFAULT_LANG
    mode = "voice" if (audio is not None or session.get("mode") == "voice") else "text"
    b = budget_mod.Budget(int(f.get("cost_ceiling_units", 500)))
    stages: List[llm.Stage] = []
    st = {"status": "error", "reply": "", "error": None, "charged": 0,
          "charge_error": None, "transcript": None, "audio": None}

    def add(stage: llm.Stage):
        stages.append(stage)
        b.add(stage)

    question = ""
    plan: Dict = {}
    answered = False
    try:
        # ---- cloud STT ----
        if audio is not None:
            question, stage = speech.transcribe(audio, lang)
            add(stage)
            st["transcript"] = question
        else:
            question = text
        question = guard.sanitize(question)
        if not question:
            if audio is None:
                raise AiError(400, "invalid", "Empty question")
            st.update(status="clarify", reply=guard.free_cap_message(lang))
            return _finish(uid, session, question, st, stages, b, t0, trace_id,
                           lang, mode, dry_run, plan, on_done)
        if guard.too_long(question):
            raise AiError(400, "invalid", "Question too long (max %d characters)"
                          % guard.MAX_QUESTION_CHARS)

        free_turns = int(session.get("free_turns", 0) or 0)
        if free_turns >= FREE_TURNS_HARD:
            st.update(status="refused", reply=guard.free_cap_message(lang),
                      error="free_turn_cap")
            return _finish(uid, session, question, st, stages, b, t0, trace_id,
                           lang, mode, dry_run, plan, on_done)
        if guard.obvious_off_topic(question):
            st.update(status="refused", reply=guard.refusal_for(lang),
                      error="prefilter_off_topic")
            return _finish(uid, session, question, st, stages, b, t0, trace_id,
                           lang, mode, dry_run, plan, on_done)
        injection = guard.looks_like_injection(question)
        if injection:
            log.warning("possible injection uid=%s: %.120s", uid, question)

        # ---- context (three independent Firestore reads, run together) ----
        pid = session.get("profile_id", "")
        profile, facts, others = _context(uid, pid, dry_run, profile, memory_facts)
        if not profile:
            raise AiError(404, "not_found", "Profile not found for this session")
        summary = session.get("summary", "") or ""

        # ---- 1. plan ----
        try:
            plan, stage = planner.plan(question, lang=lang, mode=mode, summary=summary,
                                       memory=facts, profile=profile,
                                       other_profiles=others,
                                       injection_suspected=injection)
            add(stage)
        except Exception as exc:
            log.error("planner failed: %s", exc)
            st.update(status="error", reply=guard.error_message(lang),
                      error="planner: %s" % str(exc)[:300])
            return _finish(uid, session, question, st, stages, b, t0, trace_id,
                           lang, mode, dry_run, plan, on_done)
        if plan["status"] != "ok":
            reply = plan["reply"] or guard.refusal_for(lang)
            if free_turns >= FREE_TURNS_SOFT:
                reply = guard.free_cap_message(lang)
            st.update(status=plan["status"], reply=reply)
            return _finish(uid, session, question, st, stages, b, t0, trace_id,
                           lang, mode, dry_run, plan, on_done)

        # ---- 2. tools + brief ----
        birth = repo.birth_of(profile)

        def other_birth(opid):
            p = repo.get_profile(uid, opid) if (opid and not dry_run) else None
            return repo.birth_of(p) if p else None

        results, stage = executor.run_tools(plan, birth, other_birth)
        add(stage)
        b.reserve("memory", budget_mod.memory_reserve())
        tts_tier = speech.tts_tier_for(lang) if want_tts else None
        brief_out = executor.VOICE_BRIEF_TOKENS if mode == "voice" else executor.TEXT_BRIEF_TOKENS
        # When the engine output is already small, Opus reads it directly and
        # the Flash brief is skipped: the reason floor must then be sized on
        # the real JSON rather than on a full-size brief.
        skip_brief = executor.skips_brief(results)
        facts_tokens = (executor.raw_tokens(results) if skip_brief else brief_out)
        reason_reserve = _reason_floor(question, summary, facts, facts_tokens, mode, tts_tier)
        if b.remaining() < reason_reserve:   # misconfigured ceiling: stop before spending more
            st.update(status="error", reply=guard.error_message(lang),
                      error="budget: ceiling too low for a minimum answer")
            return _finish(uid, session, question, st, stages, b, t0, trace_id,
                           lang, mode, dry_run, plan, on_done)
        if skip_brief:
            brief, stage = executor.raw_brief(results)
        else:
            max_in = budget_mod.brief_input_cap_tokens(b.remaining(), brief_out,
                                                       reason_reserve)
            brief, stage = executor.make_brief(
                results, focus=plan["focus"], question=question, profile=profile,
                max_out_tokens=brief_out, max_in_tokens=max_in,
                today=clock.stamp())
        add(stage)

        # ---- 3. reason (budget-capped) ----
        fit = reasoner.fit(lang=lang, mode=mode, question=question, brief=brief,
                           summary=summary, memory=facts, profile=profile,
                           remaining_paise=b.remaining(), tts_tier=tts_tier,
                           intent=plan.get("intent", ""))
        if not fit["fits"]:
            st.update(status="error", reply=guard.error_message(lang),
                      error="budget: cannot fit a minimum answer (cap %d)" % fit["max_tokens"])
            return _finish(uid, session, question, st, stages, b, t0, trace_id,
                           lang, mode, dry_run, plan, on_done)
        try:
            reply, stage = reasoner.answer(fit, on_delta=on_delta)
            add(stage)
        except Exception as exc:
            log.error("reasoner failed: %s", exc)
            st.update(status="error", reply=guard.error_message(lang),
                      error="reason: %s" % str(exc)[:300])
            return _finish(uid, session, question, st, stages, b, t0, trace_id,
                           lang, mode, dry_run, plan, on_done)
        if not reply or guard.leaks_system_prompt(reply):
            st.update(status="refused" if reply else "error",
                      reply=guard.refusal_for(lang) if reply else guard.error_message(lang),
                      error="leak_blocked" if reply else "empty_reply")
            return _finish(uid, session, question, st, stages, b, t0, trace_id,
                           lang, mode, dry_run, plan, on_done)
        answered = True
        st.update(status="ok", reply=reply)

        # ---- cloud TTS ----
        if tts_tier:
            try:
                audio_out, stage = speech.synthesize(reply, lang)
                add(stage)
                st["audio"] = base64.b64encode(audio_out).decode("ascii")
            except Exception as exc:
                log.warning("tts failed (client falls back to on-device): %s", exc)

        # ---- charge ----
        if not dry_run:
            st["charged"], st["charge_error"] = _charge(uid, price_units(f), trace_id)
        return _finish(uid, session, question, st, stages, b, t0, trace_id, lang,
                       mode, dry_run, plan, on_done, facts=facts, summary=summary)
    except AiError:
        raise
    except speech.AudioError as exc:
        raise AiError(400, "invalid", "Audio not usable: %s" % exc)
    except Exception as exc:
        log.exception("pipeline error trace=%s", trace_id)
        if answered:   # never lose a delivered answer to a bookkeeping error
            st["error"] = "post-answer: %s" % str(exc)[:300]
        else:
            st.update(status="error", reply=guard.error_message(lang),
                      error=str(exc)[:300])
        return _finish(uid, session, question, st, stages, b, t0, trace_id, lang,
                       mode, dry_run, plan, on_done)


def _context(uid: str, pid: str, dry_run: bool, profile: Optional[Dict],
             memory_facts: Optional[List[str]]) -> Tuple[Optional[Dict], List[str], List[Dict]]:
    """Profile + long-term memory + the other profiles, in parallel.

    These are three independent Firestore round trips in front of the first
    model call; serially they are the whole pre-plan latency."""
    if dry_run:
        return profile, (memory_facts if memory_facts is not None else []), []
    jobs = {}
    with ThreadPoolExecutor(max_workers=3, thread_name_prefix="ai-ctx") as pool:
        if profile is None:
            jobs["profile"] = pool.submit(repo.get_profile, uid, pid)
        if memory_facts is None:
            jobs["facts"] = pool.submit(repo.get_memory, uid, pid)
        jobs["others"] = pool.submit(repo.list_profiles, uid)
        out = {}
        for name, fut in jobs.items():
            try:
                out[name] = fut.result()
            except Exception as exc:
                if name == "profile":
                    raise
                log.warning("context read %s failed: %s", name, exc)
                out[name] = []
    return (out.get("profile", profile),
            out.get("facts", memory_facts) or [],
            out.get("others") or [])


def _reason_floor(question: str, summary: str, facts: List[str], brief_out: int,
                  mode: str, tts_tier: Optional[str]) -> float:
    """Minimum Opus spend we must keep available when sizing the brief
    input: full prompt with a max-size brief + the mode's minimum answer."""
    from . import costs
    m = llm.CLAUDE_MODEL
    in_tok = (costs.estimate_tokens(reasoner.SYSTEM_PROMPT + reasoner.VOICE_STYLE)
              + costs.estimate_tokens(question) + costs.estimate_tokens(summary[:1500])
              + costs.estimate_tokens(" ".join(facts[:8])) + brief_out + 120)
    min_out = budget_mod.mode_min_tokens(mode)
    per_out = costs.per_token_paise(m, "out")
    if tts_tier:
        per_out += costs.TTS_CHARS_PER_OUT_TOKEN * costs.tts_paise_per_char(tts_tier)
    return in_tok * costs.per_token_paise(m, "in") + min_out * per_out


def _finish(uid, session, question, st, stages, b, t0, trace_id, lang, mode,
            dry_run, plan, on_done, facts=None, summary=None) -> Result:
    """Balance -> on_done (SSE 'done') -> RETURN, then, off the request
    thread: memory -> persist -> trace/rollups.

    Nothing after `on_done` is needed to answer the user, so the tail runs in
    the background. `trace["latency_ms"]` is therefore what the user waited,
    not what the query took to file away; each tail stage still carries its
    own `latency_ms` and `cost_units` exactly as CONTRACT.md specifies, and
    `trace` is the same dict object the tail fills in (Result.wait())."""
    status = st["status"]
    answered = status == "ok"
    if answered and b.over():
        status = "over_ceiling"
    balance = 0
    if not dry_run:
        try:
            balance = repo.get_balance(uid)
        except Exception as exc:
            log.warning("balance read failed: %s", exc)
    done = {"charged_units": st["charged"], "balance_units": balance,
            "status": status, "trace_id": trace_id}
    if on_done:   # SSE `done` goes out before the (slow-ish) memory update
        try:
            on_done(done, st["reply"])
        except Exception:
            pass

    trace = {
        "trace_id": trace_id, "uid": uid, "session_id": session.get("id", ""),
        "lang": lang, "mode": mode, "kind": "query", "status": status,
        "question_chars": len(question or ""), "created_at": store.now_iso(),
        "latency_ms": int((time.time() - t0) * 1000),
        "stages": [s.to_trace() for s in stages],
        "cost_units": sum(s.to_trace()["cost_units"] for s in stages),
        "charged_units": st["charged"], "error": st["error"],
    }
    if st["charge_error"]:
        trace["charge_error"] = st["charge_error"]
    trace["budget"] = budget_mod.summary(b)

    result = Result(reply=st["reply"], status=status, trace_id=trace_id,
                    charged_units=st["charged"], balance_units=balance,
                    transcript=st["transcript"], audio_b64=st["audio"],
                    trace=trace, summary=summary or "", facts=list(facts or []))

    def tail() -> None:
        _tail(uid, session, question, st, stages, b, trace, status, answered,
              lang, mode, dry_run, facts, summary, result)

    if ASYNC_TAIL:
        # Also async under dry_run, so the benchmark and the cost probe
        # measure the real thing; both call Result.wait() for the trace.
        result.tail = threading.Thread(target=tail, name="ai-tail-" + trace_id[:8],
                                       daemon=True)
        result.tail.start()
    else:
        tail()
    return result


def _tail(uid, session, question, st, stages, b, trace, status, answered,
          lang, mode, dry_run, facts, summary, result) -> None:
    """Post-answer bookkeeping. Runs off the request thread; never raises."""
    try:
        new_summary, new_facts = summary, facts
        if answered:
            b.release("memory")
            try:
                new_summary, new_facts, stage = memory.update(
                    summary=summary or "", facts=facts or [], question=question,
                    answer=st["reply"], lang=lang)
                stages.append(stage)
                b.add(stage)
            except Exception as exc:
                # A broken memory update must not cost us the trace, the
                # rollups or the session write that follow.
                log.error("memory update failed: %s", exc)
                stages.append(llm.Stage(name="memory",
                                        detail={"error": str(exc)[:200]}))
            if b.over():
                status = "over_ceiling"
            result.summary, result.facts = new_summary or "", list(new_facts or [])

        cost_units = sum(s.to_trace()["cost_units"] for s in stages)
        # The trace dict is shared with the returned Result: update in place.
        trace.update(status=status, stages=[s.to_trace() for s in stages],
                     cost_units=cost_units, budget=budget_mod.summary(b))

        if dry_run:
            return
        sid = session.get("id", "")
        _safe(repo.add_message, sid, "user", question or "", 0, trace["trace_id"])
        _safe(repo.add_message, sid, "assistant", st["reply"], st["charged"],
              trace["trace_id"])
        upd = {"updated_at": store.now_iso()}
        if question and not session.get("title"):
            # Shown in the conversation list: the user's own words, in their
            # language (the running `summary` is internal English memory).
            upd["title"] = question.strip()[:140]
        if answered:
            upd["query_count"] = ("incr", 1)
            upd["summary"] = new_summary or ""
            if new_facts is not None and new_facts != facts:
                _safe(repo.save_memory, uid, session.get("profile_id", ""), new_facts)
        elif status in ("refused", "clarify"):
            upd["free_turns"] = ("incr", 1)
        _safe(repo.update_session, sid, upd)
        _safe(repo.write_trace, trace)
        roll = {"cost_units": cost_units}
        if status in ("ok", "over_ceiling"):
            roll.update({"queries": 1, "revenue_units": st["charged"],
                         "by_lang.%s" % lang: 1})
            if mode == "voice":
                roll["voice_queries"] = 1
            if status == "over_ceiling":
                roll["over_ceiling"] = 1
        elif status == "error":
            roll["errors"] = 1
        else:
            roll["refusals"] = 1
        _safe(repo.incr_rollup, roll)
    except Exception:   # pragma: no cover - defensive; the answer is delivered
        log.exception("tail failed trace=%s", trace.get("trace_id"))


def _safe(fn, *args):
    try:
        fn(*args)
    except Exception as exc:
        log.error("%s failed: %s", getattr(fn, "__name__", fn), exc)
