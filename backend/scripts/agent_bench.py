#!/usr/bin/env python3
"""Benchmark the Prashna consultation agent: latency, tokens and ₹ cost.

Runs a fixed suite of questions (career, marriage, health, money, a narrow
factual lookup, a general reading and a follow-up turn — one per supported
language) through the REAL pipeline `--runs` times and prints, per stage,
p50/p95 latency, tokens and paise, plus the two numbers that matter to a
waiting user: **time to first token** and total wall clock.

    cd backend
    ANTHROPIC_API_KEY=... GEMINI_API_KEY=... python scripts/agent_bench.py
    python scripts/agent_bench.py --runs 3 --json after.json
    python scripts/agent_bench.py --compare before.json        # A/B table
    python scripts/agent_bench.py --cases career,followup --langs te,hi
    python scripts/agent_bench.py --dry-run                    # free, no network
    python scripts/agent_bench.py --http https://host --token eyJ...  # real SSE

Modes
-----
default     Real Gemini + Claude calls, in-process, `dry_run=True` in the
            pipeline: no wallet charge, no Firestore, no rate limiting.
            **This spends provider money** — see the cost line it prints at
            the end (roughly ₹3 per question, so ~₹20 for one full pass).
--dry-run   The unit-test fakes with injected per-stage latency. Calls no
            API and costs nothing; use it to exercise this script, to check
            the orchestration (what overlaps what, what the tail does) and
            to smoke-test a refactor before paying for a real pass.
--http      Additionally drives POST /api/sessions/{sid}/ask/stream against
            a running server and reports the TTFT seen on the wire, which is
            what the Android app feels. Needs --token (an app JWT) and
            --profile. This path DOES charge the wallet: it is a real query.

Everything the suite reports comes out of the pipeline's own trace, so the
numbers are exactly what the operator dashboard will show for real traffic.
"""

import argparse
import json
import os
import statistics
import sys
import time
from typing import Dict, List

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
sys.path.insert(0, BACKEND)

os.environ.setdefault("JWT_SECRET", "agent-bench-not-a-real-secret-0123456789")

from app.ai import costs, llm, pipeline  # noqa: E402

# --------------------------------------------------------------------------
# The suite. Six intents across six languages plus a follow-up turn, so one
# pass exercises every branch the budget guard can take: a wide reading
# (full_analysis + varga), a narrow lookup (small engine output -> the brief
# call is skipped), and a follow-up that must resolve a pronoun from the
# session summary rather than from the question.

CASES: List[Dict] = [
    {"name": "career", "lang": "te", "intent": "career",
     "q": "నా ఉద్యోగంలో వచ్చే రెండు సంవత్సరాలు ఎలా ఉంటాయి? ప్రమోషన్ వస్తుందా?",
     # Follow-up: meaningless without the running session summary.
     "followup": "మరి ఆ సమయంలో విదేశాలకు వెళ్ళే అవకాశం ఉందా?"},
    {"name": "marriage", "lang": "hi", "intent": "marriage",
     "q": "मेरा विवाह कब तक होगा? जीवनसाथी कैसा रहेगा?"},
    {"name": "health", "lang": "ta", "intent": "health",
     "q": "என் உடல்நலம் அடுத்த ஆண்டில் எப்படி இருக்கும்? எதில் கவனம் தேவை?"},
    {"name": "money", "lang": "kn", "intent": "finance",
     "q": "ನನ್ನ ಆರ್ಥಿಕ ಸ್ಥಿತಿ ಸುಧಾರಿಸುತ್ತದೆಯೇ? ಸಾಲ ತೀರಿಸಲು ಯಾವ ಸಮಯ ಒಳ್ಳೆಯದು?"},
    {"name": "general", "lang": "ml", "intent": "general",
     "q": "എന്റെ ജാതകത്തിൽ ഇപ്പോൾ നടക്കുന്ന ദശ എന്താണ്? ഈ കാലയളവ് എങ്ങനെയായിരിക്കും?"},
    # Narrow factual question: the engine output is small, so this is the
    # case that takes the no-brief path.
    {"name": "lookup", "lang": "en", "intent": "panchanga",
     "q": "What is my current mahadasha and antardasha, with exact dates?"},
]

PROFILE = {"id": "bench", "name": "Bench", "relation": "self", "time_known": True,
           "birth": {"date": "1990-05-17", "time": "14:30", "tz": "Asia/Kolkata",
                     "lat": 17.385, "lon": 78.4867, "place": "Hyderabad"}}

FLAGS = {"voice_cloud_enabled": True, "opus_enabled": True,
         "query_price_units": int(os.environ.get("QUERY_PRICE_UNITS", "1000")),
         "cost_ceiling_units": int(os.environ.get("QUERY_COST_CEILING_UNITS", "500")),
         "maintenance_message": ""}

STAGES = ("stt", "plan", "tools", "brief", "reason", "tts", "memory")


# --------------------------------------------------------------------------
# --dry-run: the unit-test fakes, with latency injected so the printed shape
# resembles a real pass. These numbers are NOT measurements of the models.

FAKE_LATENCY_MS = {"plan": 900, "brief": 3800, "reason_ttft": 1700,
                   "reason_total": 14000, "memory": 1500, "count_tokens": 320}


def install_fakes() -> None:
    sys.path.insert(0, os.path.join(BACKEND, "tests", "ai"))
    import ai_fakes

    lat = FAKE_LATENCY_MS

    wide = {"status": "ok", "intent": "career", "focus": "Career prospects.",
            "reply": "", "tools": [{"name": "full_analysis"},
                                   {"name": "varga_chart", "varga": "D10"}]}
    narrow = {"status": "ok", "intent": "panchanga", "focus": "Running dasha.",
              "reply": "", "tools": [{"name": "current_dasha"}]}

    class SlowGemini(ai_fakes.FakeGemini):
        def generate_content(self, model, contents, config):
            system = config.get("system_instruction", "")
            key = ("plan" if "PLANNER PROTOCOL" in system else
                   "brief" if "FACTS BRIEF PROTOCOL" in system else "memory")
            if key == "plan":
                # Route like the real planner would, so the dry run also
                # exercises the narrow (no-brief) branch.
                self.plan = narrow if "mahadasha" in contents else wide
            time.sleep(lat[key] / 1000.0)
            return super().generate_content(model, contents, config)

    class SlowClaude(ai_fakes.FakeClaude):
        def count_tokens(self, model, system, messages):
            time.sleep(lat["count_tokens"] / 1000.0)
            return super().count_tokens(model, system, messages)

        def stream(self, **kw):
            inner = super().stream(**kw)
            ttft, total = lat["reason_ttft"] / 1000.0, lat["reason_total"] / 1000.0
            real_stream = ai_fakes._Stream

            class Timed(real_stream):
                @property
                def text_stream(self):
                    time.sleep(ttft)
                    chunks = list(real_stream.text_stream.fget(self))
                    gap = max(0.0, total - ttft) / max(1, len(chunks))
                    for c in chunks:
                        time.sleep(gap)
                        yield c

            return Timed(inner._text, inner._final)

    llm.set_clients(gemini=SlowGemini(), claude=SlowClaude())


# --------------------------------------------------------------------------

def _pct(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def _words(text: str) -> int:
    return max(1, len((text or "").split()))


def run_one(case: Dict, lang: str, question: str, summary: str,
            facts: List[str], mode: str) -> Dict:
    """One measured turn. Returns a sample dict (also used for --json)."""
    session = {"id": "bench-%s" % case["name"], "uid": "bench",
               "profile_id": "bench", "lang": lang, "mode": mode,
               "summary": summary}
    mark = {"first": None, "done": None}
    t0 = time.time()

    def on_delta(_text: str) -> None:
        if mark["first"] is None:
            mark["first"] = time.time()

    def on_done(_done: Dict, _reply: str) -> None:
        # Exactly where routes_ai emits SSE `event: done`.
        mark["done"] = time.time()

    r = pipeline.run_query("bench", session, question, dry_run=True,
                           prechecked=FLAGS, profile=PROFILE,
                           memory_facts=list(facts), on_delta=on_delta,
                           on_done=on_done)
    return_ms = int((time.time() - t0) * 1000)   # what POST /ask returns in
    r.wait()                       # the trace is filed by the background tail
    wall_ms = int((time.time() - t0) * 1000)
    t = r.trace
    stages = {s["name"]: s for s in t["stages"]}
    reason = stages.get("reason", {})
    sample = {
        "case": case["name"], "lang": lang, "status": t["status"],
        "wall_ms": wall_ms, "return_ms": return_ms,
        "ttft_ms": int((mark["first"] - t0) * 1000) if mark["first"] else None,
        "done_ms": int((mark["done"] - t0) * 1000) if mark["done"] else return_ms,
        "user_latency_ms": t["latency_ms"],
        "cost_units": t["cost_units"],
        "stages": {n: {"latency_ms": s.get("latency_ms", 0),
                       "in_tok": s.get("in_tok", 0), "out_tok": s.get("out_tok", 0),
                       "cost_units": s.get("cost_units", 0),
                       "detail": s.get("detail", {})}
                   for n, s in stages.items()},
        "intent": (stages.get("plan", {}).get("detail") or {}).get("intent", ""),
        "brief_skipped": bool((stages.get("brief", {}).get("detail") or {}).get("skipped")),
        "reply_words": _words(r.reply),
        "out_tok_per_word": round(reason.get("out_tok", 0) / _words(r.reply), 2),
        "reply": r.reply,
        "error": t.get("error"),
    }
    return sample, r


def run_suite(cases: List[Dict], runs: int, mode: str, show_replies: int) -> List[Dict]:
    samples: List[Dict] = []
    for run in range(runs):
        for case in cases:
            lang = case["lang"]
            s, r = run_one(case, lang, case["q"], "", [], mode)
            samples.append(s)
            _progress(run, runs, s)
            if show_replies and run == 0:
                _show_reply(s, show_replies)
            if case.get("followup"):
                # Thread the real session summary/memory the first turn's
                # memory stage produced into the second turn: that is what
                # makes it a follow-up rather than a second cold question.
                fu = dict(case, name=case["name"] + "+followup")
                s2, _ = run_one(fu, lang, case["followup"], r.summary,
                                r.facts, mode)
                samples.append(s2)
                _progress(run, runs, s2)
                if show_replies and run == 0:
                    _show_reply(s2, show_replies)
    return samples


def _progress(run: int, runs: int, s: Dict) -> None:
    print("  run %d/%d %-18s %-3s %-12s wall %5.1fs  ttft %s  ₹%.2f%s"
          % (run + 1, runs, s["case"], s["lang"], s["status"],
             s["wall_ms"] / 1000.0,
             "%5.1fs" % (s["ttft_ms"] / 1000.0) if s["ttft_ms"] else "    —",
             s["cost_units"] / 100.0,
             "  [no-brief]" if s["brief_skipped"] else ""), flush=True)


def _show_reply(s: Dict, chars: int) -> None:
    print("      %s" % (s["reply"] or "")[:chars].replace("\n", " ⏎ "))


# --------------------------------------------------------------------------

def summarise(samples: List[Dict]) -> Dict:
    ok = [s for s in samples if s["status"] in ("ok", "over_ceiling")] or samples
    out: Dict = {"n": len(samples), "ok": len(ok), "stages": {}}
    for name in STAGES:
        rows = [s["stages"][name] for s in ok if name in s["stages"]]
        if not rows:
            continue
        out["stages"][name] = {
            "n": len(rows),
            "p50_ms": round(_pct([r["latency_ms"] for r in rows], 0.5)),
            "p95_ms": round(_pct([r["latency_ms"] for r in rows], 0.95)),
            "in_tok": round(statistics.mean([r["in_tok"] for r in rows])),
            "out_tok": round(statistics.mean([r["out_tok"] for r in rows])),
            "cost_units": round(statistics.mean([r["cost_units"] for r in rows]), 1),
        }
    ttfts = [s["ttft_ms"] for s in ok if s["ttft_ms"]]
    out.update({
        "wall_p50_ms": round(_pct([s["wall_ms"] for s in ok], 0.5)),
        "wall_p95_ms": round(_pct([s["wall_ms"] for s in ok], 0.95)),
        "done_p50_ms": round(_pct([s["done_ms"] for s in ok], 0.5)),
        "done_p95_ms": round(_pct([s["done_ms"] for s in ok], 0.95)),
        "return_p50_ms": round(_pct([s["return_ms"] for s in ok], 0.5)),
        "return_p95_ms": round(_pct([s["return_ms"] for s in ok], 0.95)),
        "user_p50_ms": round(_pct([s["user_latency_ms"] for s in ok], 0.5)),
        "user_p95_ms": round(_pct([s["user_latency_ms"] for s in ok], 0.95)),
        "ttft_p50_ms": round(_pct(ttfts, 0.5)),
        "ttft_p95_ms": round(_pct(ttfts, 0.95)),
        "cost_mean_units": round(statistics.mean([s["cost_units"] for s in ok]), 1),
        "cost_p95_units": round(_pct([s["cost_units"] for s in ok], 0.95), 1),
        "cost_max_units": max(s["cost_units"] for s in ok),
        "over_ceiling": sum(1 for s in samples if s["status"] == "over_ceiling"),
        "errors": sum(1 for s in samples if s["status"] == "error"),
        "total_spend_units": sum(s["cost_units"] for s in samples),
    })
    return out


def print_report(samples: List[Dict], summary: Dict) -> None:
    ceiling = FLAGS["cost_ceiling_units"]
    print("\n" + "=" * 78)
    print("PER-STAGE  (mean tokens, mean ₹, p50/p95 latency over %d turns)"
          % summary["ok"])
    print("-" * 78)
    print("  %-7s %6s %8s %8s %8s %9s %9s" %
          ("stage", "n", "in_tok", "out_tok", "₹", "p50", "p95"))
    for name, st in summary["stages"].items():
        print("  %-7s %6d %8d %8d %8.2f %8.2fs %8.2fs"
              % (name, st["n"], st["in_tok"], st["out_tok"],
                 st["cost_units"] / 100.0, st["p50_ms"] / 1000.0,
                 st["p95_ms"] / 1000.0))
    print("-" * 78)
    print("  WHAT THE USER WAITS")
    print("    first token         p50 %5.2fs   p95 %5.2fs   (SSE first delta)"
          % (summary["ttft_p50_ms"] / 1000.0, summary["ttft_p95_ms"] / 1000.0))
    print("    answer complete     p50 %5.2fs   p95 %5.2fs   (SSE `done`)"
          % (summary["done_p50_ms"] / 1000.0, summary["done_p95_ms"] / 1000.0))
    print("    POST /ask returns   p50 %5.2fs   p95 %5.2fs   (non-streaming route)"
          % (summary["return_p50_ms"] / 1000.0, summary["return_p95_ms"] / 1000.0))
    print("    incl. background    p50 %5.2fs   p95 %5.2fs   (bench joins the "
          "tail; no user waits for this)"
          % (summary["wall_p50_ms"] / 1000.0, summary["wall_p95_ms"] / 1000.0))
    print("  cost per query        mean ₹%.2f  p95 ₹%.2f  max ₹%.2f   "
          "(ceiling ₹%.2f, price ₹%.2f)"
          % (summary["cost_mean_units"] / 100.0, summary["cost_p95_units"] / 100.0,
             summary["cost_max_units"] / 100.0, ceiling / 100.0,
             FLAGS["query_price_units"] / 100.0))
    margin = 100.0 * (FLAGS["query_price_units"] - summary["cost_mean_units"]) \
        / FLAGS["query_price_units"]
    print("  gross margin          %.1f%%   over-ceiling %d   errors %d"
          % (margin, summary["over_ceiling"], summary["errors"]))

    print("\nPER CASE")
    print("-" * 78)
    print("  %-18s %-4s %-10s %7s %7s %7s %6s %5s" %
          ("case", "lang", "intent", "ttft", "wall", "₹", "words", "t/w"))
    seen = {}
    for s in samples:
        seen.setdefault((s["case"], s["lang"]), []).append(s)
    for (case, lang), rows in seen.items():
        print("  %-18s %-4s %-10s %6.2fs %6.2fs %7.2f %6d %5.2f%s"
              % (case, lang, rows[0]["intent"],
                 _pct([r["ttft_ms"] or 0 for r in rows], 0.5) / 1000.0,
                 _pct([r["wall_ms"] for r in rows], 0.5) / 1000.0,
                 statistics.mean([r["cost_units"] for r in rows]) / 100.0,
                 round(statistics.mean([r["reply_words"] for r in rows])),
                 statistics.mean([r["out_tok_per_word"] for r in rows]),
                 "  [no-brief]" if rows[0]["brief_skipped"] else ""))
    print("\n  this pass spent ₹%.2f of provider budget"
          % (summary["total_spend_units"] / 100.0))


def print_compare(base: Dict, now: Dict) -> None:
    b, n = base["summary"], now["summary"]

    def row(label, key, unit="s", scale=1000.0, lower_better=True):
        bv, nv = b.get(key, 0) / scale, n.get(key, 0) / scale
        if not bv and not nv:
            return
        delta = (nv - bv) / bv * 100.0 if bv else 0.0
        mark = "✓" if (delta < 0) == lower_better and abs(delta) >= 1 else " "
        print("  %s %-28s %8.2f%s %8.2f%s %+7.1f%%"
              % (mark, label, bv, unit, nv, unit, delta))

    print("\n" + "=" * 78)
    print("BEFORE (%s)  ->  AFTER (%s)" % (base.get("label", "base"),
                                           now.get("label", "now")))
    print("-" * 78)
    print("  %-30s %9s %9s %8s" % ("", "before", "after", "change"))
    row("first token p50", "ttft_p50_ms")
    row("first token p95", "ttft_p95_ms")
    row("answer complete p50 (SSE)", "done_p50_ms")
    row("answer complete p95 (SSE)", "done_p95_ms")
    row("POST /ask returns p50", "return_p50_ms")
    row("POST /ask returns p95", "return_p95_ms")
    row("cost per query (mean)", "cost_mean_units", unit="₹", scale=100.0)
    row("cost per query (p95)", "cost_p95_units", unit="₹", scale=100.0)
    print("-" * 78)
    print("  %-30s %9s %9s %8s" % ("stage p50", "before", "after", "change"))
    for name in STAGES:
        sb, sn = b["stages"].get(name), n["stages"].get(name)
        if not sb and not sn:
            continue
        bv = (sb or {}).get("p50_ms", 0) / 1000.0
        nv = (sn or {}).get("p50_ms", 0) / 1000.0
        d = (nv - bv) / bv * 100.0 if bv else 0.0
        print("    %-28s %8.2fs %8.2fs %+7.1f%%" % (name, bv, nv, d))


# --------------------------------------------------------------------------
# --http: the real SSE endpoint, to prove the stream reaches the wire.

def probe_http(base_url: str, token: str, profile_id: str, question: str,
               lang: str) -> None:
    import urllib.request

    def call(path, body=None, method="POST"):
        req = urllib.request.Request(
            base_url.rstrip("/") + path, method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": "Bearer " + token,
                     "Content-Type": "application/json",
                     "Accept-Language": lang})
        return req

    sid = json.loads(urllib.request.urlopen(
        call("/api/sessions", {"profile_id": profile_id, "mode": "text"}),
        timeout=30).read())["session_id"]
    req = call("/api/sessions/%s/ask/stream" % sid, {"text": question})
    req.add_header("Accept", "text/event-stream")
    t0 = time.time()
    first = last = None
    deltas = 0
    done = {}
    with urllib.request.urlopen(req, timeout=180) as resp:
        enc = resp.headers.get("Content-Encoding", "")
        ctype = resp.headers.get("Content-Type", "")
        event = "message"
        for raw in resp:
            line = raw.decode("utf-8", "replace").rstrip("\n")
            if line.startswith("event:"):
                event = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                payload = line.split(":", 1)[1].strip()
                if event in ("delta", "message"):
                    if first is None:
                        first = time.time()
                    deltas += 1
                    last = time.time()
                elif event == "done":
                    done = json.loads(payload)
    total = time.time() - t0
    print("\nSSE /ask/stream  (%s)" % base_url)
    print("  content-type      %s" % ctype)
    print("  content-encoding  %s%s" % (enc or "(none)",
          "   *** gzip buffers SSE — TTFT will be wrong ***" if "gzip" in enc else ""))
    print("  deltas            %d %s" % (deltas,
          "(streamed)" if deltas > 2 else "*** one chunk: NOT streaming ***"))
    print("  wire TTFT         %.2fs" % ((first - t0) if first else total))
    print("  last delta        %.2fs" % ((last - t0) if last else total))
    print("  done event        %.2fs  %s" % (total, json.dumps(done)))


# --------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", type=int, default=1, help="repeats of the whole suite")
    ap.add_argument("--cases", default="", help="comma-separated subset of case names")
    ap.add_argument("--langs", default="", help="comma-separated subset of languages")
    ap.add_argument("--voice", action="store_true",
                    help="voice mode (shorter answers, voice brief budget)")
    ap.add_argument("--dry-run", action="store_true",
                    help="fakes with injected latency: no API calls, costs nothing")
    ap.add_argument("--replies", type=int, default=0, metavar="CHARS",
                    help="print the first CHARS of each reply (quality spot-check)")
    ap.add_argument("--json", metavar="FILE", help="write raw samples + summary")
    ap.add_argument("--compare", metavar="FILE", help="A/B against an earlier --json")
    ap.add_argument("--label", default="", help="label stored in --json")
    ap.add_argument("--http", metavar="BASE_URL", help="also probe the real SSE route")
    ap.add_argument("--token", default="", help="app JWT for --http")
    ap.add_argument("--profile", default="", help="profile id for --http")
    # --- reasoning-model A/B (Opus 4.5 vs Opus 5) ---
    ap.add_argument("--model", default="", metavar="ID",
                    help="override CLAUDE_MODEL for this run, e.g. claude-opus-5")
    ap.add_argument("--effort", default="", metavar="LEVEL",
                    help="output_config.effort: low|medium|high (|xhigh|max on Opus 5); "
                         "'off' sends none")
    ap.add_argument("--thinking", default="", choices=["", "adaptive", "disabled"],
                    help="force the thinking mode instead of the model's default "
                         "(Opus 4.5 is off by default, Opus 5 adaptive)")
    a = ap.parse_args()

    # Model knobs are module-level in llm.py; set them before anything runs.
    if a.model:
        llm.CLAUDE_MODEL = a.model
    if a.effort:
        llm.CLAUDE_EFFORT = "" if a.effort == "off" else a.effort.lower()
    if a.thinking:
        llm.CLAUDE_THINKING = a.thinking
    llm.reset_capabilities()

    cases = list(CASES)
    if a.cases:
        want = {c.strip() for c in a.cases.split(",")}
        cases = [c for c in cases if c["name"] in want]
    if a.langs:
        want = {c.strip() for c in a.langs.split(",")}
        cases = [c for c in cases if c["lang"] in want]
    if not cases:
        sys.exit("no cases selected")

    if a.dry_run:
        install_fakes()
        print("DRY RUN — fakes with injected latency; no API calls, no money spent.")
    else:
        if not llm.ANTHROPIC_API_KEY:
            sys.exit("Set ANTHROPIC_API_KEY (or use --dry-run)")
        if not (llm.GEMINI_API_KEY or llm.GEMINI_USE_VERTEX):
            sys.exit("Set GEMINI_API_KEY or GEMINI_USE_VERTEX=1 (or use --dry-run)")
        llm.warm_clients()

    print("models: flash=%s  reason=%s  effort=%s  thinking=%s  "
          "USD_TO_INR=%.0f  ceiling ₹%.2f"
          % (llm.GEMINI_MODEL, llm.CLAUDE_MODEL, llm.CLAUDE_EFFORT or "off",
             llm.CLAUDE_THINKING or ("default-on" if llm.thinks_by_default()
                                     else "default-off"),
             costs.USD_TO_INR, FLAGS["cost_ceiling_units"] / 100.0))
    print("suite: %d cases x %d runs%s\n"
          % (len(cases), a.runs, ", voice" if a.voice else ""))

    t0 = time.time()
    samples = run_suite(cases, a.runs, "voice" if a.voice else "text", a.replies)
    summary = summarise(samples)
    print_report(samples, summary)
    print("  suite wall clock %.1fs" % (time.time() - t0))

    payload = {"label": a.label or ("dry-run" if a.dry_run else "real"),
               "when": time.strftime("%Y-%m-%dT%H:%M:%S"),
               "models": {"flash": llm.GEMINI_MODEL, "reason": llm.CLAUDE_MODEL,
                          "effort": llm.CLAUDE_EFFORT,
                          "thinking": llm.CLAUDE_THINKING or "model default"},
               "summary": summary, "samples": samples}
    if a.json:
        with open(a.json, "w") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=1)
        print("  wrote %s" % a.json)
    if a.compare:
        with open(a.compare) as fh:
            print_compare(json.load(fh), payload)

    if a.http:
        if not (a.token and a.profile):
            sys.exit("--http needs --token and --profile")
        c = cases[0]
        probe_http(a.http, a.token, a.profile, c["q"], c["lang"])


if __name__ == "__main__":
    main()
