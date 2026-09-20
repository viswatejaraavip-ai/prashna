#!/usr/bin/env python3
"""Measure what one life-report chapter really costs, per language.

Writes a REAL chapter with Claude Opus 4.5 for each language and prints the
only number that matters for pricing: output **tokens per written word** in
that script. Everything else (₹ per chapter, ₹ per report, the price at
REPORT_MARGIN) follows from it and from app/ai/costs.py.

    cd backend
    ANTHROPIC_API_KEY=... GEMINI_API_KEY=... \
        ../.venv/bin/python scripts/report_bench.py                # all 6 langs
    ... scripts/report_bench.py --langs te ml --words 1000
    ... scripts/report_bench.py --langs te --wave 18               # real makespan
    ... scripts/report_bench.py --dry-run                          # no network

THIS COSTS REAL MONEY: one 1,000-word chapter is roughly ₹12-₹18 in a
Dravidian language, so the default six-language run is about ₹60-₹90 (the
script prints the exact total it spent). `--wave 18` writes 18 chapters of
one language: that is one whole report, ~₹250.

What to do with the output:
  * paste the printed TOKENS_PER_WORD line into app/ai/costs.py (that table
    is owned by the AI workstream — send them the line, don't edit it here);
  * paste the printed REPORT_FEE_UNITS_<LANG> lines into the Cloud Run env so
    the price matches the measurement instead of the model.
"""

import argparse
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from app.ai import costs, llm  # noqa: E402

PROFILE = {"id": "bench", "name": "Bench", "relation": "self", "time_known": True,
           "birth": {"date": "1990-05-17", "time": "14:30", "tz": "Asia/Kolkata",
                     "lat": 17.385, "lon": 78.4867, "place": "Hyderabad"}}
# Chapter 4 ("Career and Profession") — a middle-of-the-road chapter: plenty
# of chart detail, no year-by-year table (which inflates digits per word).
CHAPTER = 4


def _words(text: str) -> int:
    return max(1, len(text.split()))


def _fmt_rs(units: float) -> str:
    return "%8.2f" % (units / 100.0)


def measure(reports, bundle, birth_year: int, lang: str, words: int, chapters: int):
    """One real chapter. Returns the measured row."""
    key, title, coverage = reports.SECTIONS[CHAPTER - 1]
    prompt = ('Write chapter %d of %d: "%s".\nCoverage: %s\nChapter notes '
              "(facts to use): (none)" % (CHAPTER, chapters, title, coverage))
    plan_words, max_tokens = reports._chapter_plan(lang, words, chapters)
    t0 = time.time()
    text, stages = reports._write_chapter(bundle, lang, birth_year, plan_words,
                                          prompt, max_tokens=max_tokens)
    secs = time.time() - t0
    out_tok = sum(s.out_tok for s in stages)
    cost = sum(s.cost for s in stages)
    w = _words(text)
    return {"lang": lang, "words": w, "out_tok": out_tok, "tpw": out_tok / w,
            "chapter_units": cost, "seconds": secs,
            "cache_write": sum(s.cache_write_tok for s in stages),
            "cache_read": sum(s.cache_read_tok for s in stages),
            "tok_per_s": out_tok / max(0.001, secs), "text": text}


def modelled(reports, lang: str, words: int, chapters: int):
    """Same row shape, from costs.TOKENS_PER_WORD — no network, no spend."""
    tpw = costs.TOKENS_PER_WORD.get(lang, 5.5)
    out_tok = int(words * tpw)
    est = reports.estimate_cost_units(lang, words_total=words * chapters,
                                      chapters=chapters, tpw=tpw)
    return {"lang": lang, "words": words, "out_tok": out_tok, "tpw": tpw,
            "chapter_units": est["total_units"] / float(chapters),
            "seconds": out_tok / 50.0, "cache_write": 0, "cache_read": 0,
            "tok_per_s": 50.0, "text": ""}


def report_rows(reports, rows, words: int, chapters: int, concurrency: int,
                budget_s: int) -> None:
    print("\n%-4s %6s %8s %7s %9s %8s %9s %8s %7s" % (
        "lang", "words", "out tok", "tok/w", "₹/chapter", "chap s", "₹/report",
        "price ₹", "margin"))
    print("-" * 78)
    lines_costs, lines_env = [], []
    for r in rows:
        lang = r["lang"]
        est = reports.estimate_cost_units(lang, words_total=words * chapters,
                                          chapters=chapters, tpw=r["tpw"])
        price = max(reports.REPORT_MIN_FEE_UNITS,
                    reports._round_up_units(est["total_units"] * reports.REPORT_MARGIN))
        margin = (price - est["total_units"]) * 100.0 / price
        print("%-4s %6d %8d %7.2f %9s %8.1f %9s %8.0f %6.1f%%" % (
            lang, r["words"], r["out_tok"], r["tpw"], _fmt_rs(r["chapter_units"]),
            r["seconds"], _fmt_rs(est["total_units"]), price / 100.0, margin))
        lines_costs.append('"%s": %.1f' % (lang, round(r["tpw"] + 0.049, 1)))
        lines_env.append("REPORT_FEE_UNITS_%s=%d" % (lang.upper(), price))

    waves = -(-chapters // max(1, concurrency))
    slowest = max(r["seconds"] for r in rows)
    print("\nstructure: %d chapters x %d words = %s words, %d in flight => %d wave(s)"
          % (chapters, words, format(chapters * words, ","), concurrency, waves))
    print("projected wall clock: outline ~30s + %d x %.0fs (slowest chapter) = %.0fs"
          " of the %ds budget" % (waves, slowest, 30 + waves * slowest, budget_s))
    print("output speed: %.0f tok/s median across languages"
          % statistics.median(r["tok_per_s"] for r in rows))
    print("\ncosts.TOKENS_PER_WORD = {%s}   <- send to the AI workstream"
          % ", ".join(lines_costs))
    print("price env (cost x %.2f, rounded up to ₹%d):" % (
        reports.REPORT_MARGIN, reports.REPORT_PRICE_ROUND_UNITS // 100))
    for line in lines_env:
        print("  " + line)


def run_wave(reports, bundle, birth_year, lang, words, chapters, n):
    """Write n chapters of one language at once: the real makespan, the real
    cache behaviour and the real cost of a full report."""
    print("\n== wave: %d chapters of %s in parallel (this is a whole report)" % (n, lang))
    plan_words, max_tokens = reports._chapter_plan(lang, words, chapters)
    t0 = time.time()
    reports._warm_cache(bundle, lang, birth_year, plan_words)
    warm_s = time.time() - t0

    def one(i):
        key, title, coverage = reports.SECTIONS[(i - 1) % len(reports.SECTIONS)]
        prompt = ('Write chapter %d of %d: "%s".\nCoverage: %s\nChapter notes '
                  "(facts to use): (none)" % (i, chapters, title, coverage))
        t = time.time()
        text, stages = reports._write_chapter(bundle, lang, birth_year, plan_words,
                                              prompt, max_tokens=max_tokens)
        return {"i": i, "seconds": time.time() - t, "words": _words(text),
                "out_tok": sum(s.out_tok for s in stages),
                "cost": sum(s.cost for s in stages),
                "cache_read": sum(s.cache_read_tok for s in stages),
                "cache_write": sum(s.cache_write_tok for s in stages)}

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=n) as pool:
        out = list(pool.map(one, range(1, n + 1)))
    makespan = time.time() - t0
    spent = sum(r["cost"] for r in out)
    hits = sum(1 for r in out if r["cache_read"])
    print("  pre-warm %.1fs; makespan %.1fs (slowest chapter %.1fs, median %.1fs)" % (
        warm_s, makespan, max(r["seconds"] for r in out),
        statistics.median(r["seconds"] for r in out)))
    print("  %d/%d chapters read the cached bundle; %s words, %s output tokens"
          % (hits, n, format(sum(r["words"] for r in out), ","),
             format(sum(r["out_tok"] for r in out), ",")))
    print("  cost of this wave: ₹%.2f   (price at margin %.2f: ₹%.0f)" % (
        spent / 100.0, reports.REPORT_MARGIN,
        reports._round_up_units(spent * reports.REPORT_MARGIN) / 100.0))
    print("  VERDICT: %s the %ds budget (warm + makespan = %.0fs, + ~30s outline)" % (
        "INSIDE" if warm_s + makespan + 30 < reports.REPORT_BUDGET_S else "OVER",
        reports.REPORT_BUDGET_S, warm_s + makespan))
    return spent


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--langs", nargs="*", default=["hi", "te", "ta", "kn", "ml", "en"])
    ap.add_argument("--words", type=int, default=0, help="words per chapter "
                    "(default: REPORT_SECTION_WORDS)")
    ap.add_argument("--chapters", type=int, default=0, help="chapters in the report")
    ap.add_argument("--concurrency", type=int, default=0)
    ap.add_argument("--wave", type=int, default=0,
                    help="also write N chapters of --langs[0] in parallel (costly)")
    ap.add_argument("--dry-run", action="store_true",
                    help="no API calls: project from costs.TOKENS_PER_WORD")
    a = ap.parse_args()

    from app import reports          # imported late: pulls in the engine
    words = a.words or reports.REPORT_SECTION_WORDS
    chapters = a.chapters or len(reports.SECTIONS)
    concurrency = a.concurrency or reports.REPORT_CONCURRENCY

    if a.dry_run:
        print("DRY RUN — numbers are MODELLED from costs.TOKENS_PER_WORD, not measured.")
        rows = [modelled(reports, l, words, chapters) for l in a.langs]
        report_rows(reports, rows, words, chapters, concurrency, reports.REPORT_BUDGET_S)
        return

    if not llm.ANTHROPIC_API_KEY:
        sys.exit("Set ANTHROPIC_API_KEY (this run calls the real API and costs money)")
    from app.ai import repo
    birth = repo.birth_of(PROFILE)
    bundle = reports._bundle(birth)
    print("model=%s  effort=%r  USD_TO_INR=%.0f  bundle=%d chars (~%d tokens)" % (
        llm.CLAUDE_MODEL, reports.REPORT_EFFORT or llm.CLAUDE_EFFORT, costs.USD_TO_INR,
        len(bundle), costs.estimate_tokens(bundle)))
    print("measuring %d words/chapter in %s ..." % (words, ", ".join(a.langs)))

    spent, rows = 0.0, []
    for lang in a.langs:
        reports._warm_cache(bundle, lang, int(birth["year"]), words)
        r = measure(reports, bundle, int(birth["year"]), lang, words, chapters)
        rows.append(r)
        spent += r["chapter_units"]
        print("  %-3s %4d words in %5.1fs -> %.2f tok/word (%s ₹, cache read %d)"
              % (lang, r["words"], r["seconds"], r["tpw"],
                 _fmt_rs(r["chapter_units"]).strip(), r["cache_read"]))
        print("       %s…" % r["text"][:110].replace("\n", " "))
    report_rows(reports, rows, words, chapters, concurrency, reports.REPORT_BUDGET_S)

    if a.wave:
        spent += run_wave(reports, bundle, int(birth["year"]), a.langs[0], words,
                          chapters, a.wave)
    print("\nTHIS RUN SPENT ₹%.2f on the Anthropic API." % (spent / 100.0))


if __name__ == "__main__":
    main()
