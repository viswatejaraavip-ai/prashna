"""The PDF report, built on the repo's own PDF stack: fpdf2 with text shaping
plus the Noto Indic fonts shipped in app/features/fonts (same fonts and the
same set_text_shaping/fallback trick as app/features/pdf.py), so quoted Telugu,
Hindi, Tamil, Kannada and Malayalam answers render with correct conjuncts.

No new PDF dependency is introduced.
"""

import os
import re
import sys
from typing import Dict, List, Optional

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from app.features.textrender import font_path        # noqa: E402

MAROON = (122, 28, 28)
GOLD = (201, 146, 42)
INK = (40, 30, 30)
MUTED = (110, 100, 95)
RED = (168, 38, 38)
GREEN = (34, 110, 60)
LANGS = ("hi", "te", "ta", "kn", "ml")
W = 186.0            # usable width at 12mm margins


class Doc:
    def __init__(self):
        from fpdf import FPDF
        pdf = FPDF(format="A4", unit="mm")
        pdf.set_auto_page_break(True, margin=16)
        pdf.set_margins(12, 14, 12)
        pdf.add_font("latin", "", font_path("en", False))
        pdf.add_font("latin", "B", font_path("en", True))
        for lg in LANGS:
            pdf.add_font(lg, "", font_path(lg, False))
            pdf.add_font(lg, "B", font_path(lg, True))
        pdf.set_text_shaping(True)
        pdf.set_fallback_fonts(list(LANGS), exact_match=False)
        pdf.add_page()
        self.pdf = pdf
        self._cur = None

    # fpdf2 skips set_font() when the arguments are unchanged; after a cell
    # that rendered entirely through the fallback font that leaves the fallback
    # active and the next Indic run comes out blank. Bounce through another
    # font first, exactly as app/features/pdf.py does.
    def font(self, family: str, style: str, size: float) -> None:
        other = "te" if family == "latin" else "latin"
        self.pdf.set_font(other, style, size)
        self.pdf.set_font(family, style, size)
        self._cur = (family, style, size)

    def h1(self, text: str) -> None:
        p = self.pdf
        if p.get_y() > 250:
            p.add_page()
        p.ln(3)
        p.set_text_color(*MAROON)
        self.font("latin", "B", 14)
        p.multi_cell(W, 7, text, align="L", new_x="LMARGIN", new_y="NEXT")
        p.set_draw_color(*GOLD)
        p.line(12, p.get_y() + 0.5, 198, p.get_y() + 0.5)
        p.ln(2.5)
        p.set_text_color(*INK)

    def h2(self, text: str) -> None:
        p = self.pdf
        p.ln(1.5)
        p.set_text_color(*MAROON)
        self.font("latin", "B", 10.5)
        p.multi_cell(W, 5.5, text, align="L", new_x="LMARGIN", new_y="NEXT")
        p.set_text_color(*INK)
        p.ln(0.5)

    def para(self, text: str, size: float = 9.2, color=INK, lang: str = "latin",
             leading: float = 4.8) -> None:
        p = self.pdf
        p.set_text_color(*color)
        self.font(lang if lang in LANGS else "latin", "", size)
        p.multi_cell(W, leading, text, align="L", new_x="LMARGIN", new_y="NEXT")
        p.set_text_color(*INK)

    def bullets(self, items: List[str], size: float = 9.2) -> None:
        p = self.pdf
        for it in items:
            y = p.get_y()
            if y > 268:
                p.add_page()
                y = p.get_y()
            self.font("latin", "B", size)
            p.set_xy(13, y)
            p.cell(4, 4.8, "-")
            self.font("latin", "", size)
            p.set_xy(17, y)
            p.multi_cell(W - 5, 4.8, it, align="L", new_x="LMARGIN", new_y="NEXT")
            p.ln(0.8)
        p.ln(1)

    def quote(self, text: str, lang: str) -> None:
        """A verbatim answer, in its own script, boxed."""
        p = self.pdf
        fam = lang if lang in LANGS else "latin"
        self.font(fam, "", 8.6)
        lines = p.multi_cell(W - 6, 4.6, text, dry_run=True, output="LINES")
        need = 4.6 * max(1, len(lines)) + 4
        if p.get_y() + need > 275:
            p.add_page()
        y0 = p.get_y()
        p.set_fill_color(250, 247, 240)
        p.set_draw_color(*GOLD)
        p.rect(12, y0, W, need, "F")
        p.rect(12, y0, 1.2, need, "F")
        p.set_xy(15, y0 + 2)
        self.font(fam, "", 8.6)
        p.set_text_color(60, 48, 44)
        p.multi_cell(W - 6, 4.6, text, align="L", new_x="LMARGIN", new_y="NEXT")
        p.set_text_color(*INK)
        p.ln(2)

    def table(self, headers: List[str], widths: List[float], rows: List[List[str]],
              size: float = 7.8, colors: Optional[List[Optional[tuple]]] = None) -> None:
        p = self.pdf
        scale = W / sum(widths)
        widths = [w * scale for w in widths]

        def header():
            self.font("latin", "B", size)
            p.set_fill_color(247, 240, 228)
            p.set_draw_color(215, 205, 190)
            for hd, w in zip(headers, widths):
                p.cell(w, 5.6, hd, border=1, fill=True)
            p.ln(5.6)

        header()
        for i, row in enumerate(rows):
            heights = []
            for cell, w in zip(row, widths):
                self.font(_fam(cell), "", size)
                heights.append(4.2 * max(1, len(p.multi_cell(
                    w - 1.5, 4.2, str(cell), dry_run=True, output="LINES"))))
            hgt = max(heights + [5.0])
            if p.get_y() + hgt > 278:
                p.add_page()
                header()
            x0, y0 = p.get_x(), p.get_y()
            col = (colors or [None] * len(rows))[i]
            for cell, w in zip(row, widths):
                p.set_xy(x0, y0)
                p.set_draw_color(225, 218, 205)
                p.rect(x0, y0, w, hgt)
                self.font(_fam(cell), "", size)
                p.set_text_color(*(col or INK))
                p.set_xy(x0 + 0.8, y0 + 0.6)
                p.multi_cell(w - 1.5, 4.2, str(cell), align="L", new_x="RIGHT", new_y="TOP")
                p.set_text_color(*INK)
                x0 += w
            p.set_xy(12, y0 + hgt)
        p.ln(2)

    def output(self, path: str) -> None:
        self.pdf.output(path)


def _fam(text: str) -> str:
    """Pick the font family a cell's own characters need."""
    from app.features.textrender import _FAMILY  # noqa: F401  (ranges below)
    ranges = {"hi": (0x0900, 0x097F), "ta": (0x0B80, 0x0BFF), "te": (0x0C00, 0x0C7F),
              "kn": (0x0C80, 0x0CFF), "ml": (0x0D00, 0x0D7F)}
    for lg, (lo, hi) in ranges.items():
        if any(lo <= ord(c) <= hi for c in str(text)):
            return lg
    return "latin"


def _v(x, fmt="%s", dash="-"):
    return dash if x is None else fmt % x


def _verdict_color(v: str):
    return {"exact": GREEN, "pm1": GREEN, "wrong": RED, "refused": MUTED,
            "vague": (150, 110, 20)}.get(v)


# ------------------------------------------------------------------ report

def write(s: Dict, rows: List[Dict], scores: Dict[str, Dict], path: str) -> None:
    d = Doc()
    p = d.pdf
    h = s["hindsight"]

    # ---- title band
    p.set_fill_color(*MAROON)
    p.rect(0, 0, 210, 30, "F")
    p.set_text_color(255, 255, 255)
    p.set_xy(12, 7)
    d.font("latin", "B", 17)
    p.cell(0, 8, "Prashna - agent accuracy evaluation")
    p.set_xy(12, 17)
    d.font("latin", "", 9.5)
    p.cell(0, 6, "Live API, %s  -  %d charts with known outcomes, %d graded answers, "
                 "%d languages" % (s["today"], s["n_charts"], s["n_questions"],
                                   len(s["languages"])))
    p.set_text_color(*INK)
    p.set_xy(12, 36)

    # ---- executive summary
    d.h1("Executive summary")
    ov, tk, tu = h["overall"], h["time_known"], h["time_unknown"]
    d.para(
        "Every question below was asked through the deployed product "
        "(POST /api/sessions then /ask) on charts whose real life events are "
        "known in advance. The agent was never told the answer, and the judge "
        "model that extracted each predicted window was never shown the true "
        "date - the hit/miss decision is made in Python afterwards.")
    if s.get("note"):
        # evals/NOTE.md: whatever the reader has to be told before comparing
        # rows, e.g. that some answers were re-asked after a fix.
        d.para(re.sub(r"\*\*|\n", lambda m: "" if m.group(0) == "**" else " ",
                      s["note"]), size=8.6, color=MUTED)
    p.ln(1)
    _kpi(d, [
        ("Hindsight questions", "%d" % ov["n"]),
        ("Committed to a date", "%s%%" % _v(ov["commit_rate"], "%.0f")),
        ("Hit within +/-1 year", "%s%%" % _v(ov["hit_rate_all"], "%.0f")),
        ("Exact (<=18m window)", "%s%%" % _v(ov["exact_rate_all"], "%.0f")),
        ("Median window width", "%s mo" % _v(ov["median_window_months"], "%.0f")),
        ("Provider spend", "Rs %.0f" % (s["cost"]["total_units"] / 100.0)),
    ])
    d.h2("Accuracy by how good the input was")
    d.table(["group", "n", "committed %", "hit +/-1y %", "exact %",
             "median window", "median miss"],
            [34, 8, 16, 16, 12, 16, 16],
            [["birth time KNOWN (owner + 1)", tk["n"], _v(tk["commit_rate"]),
              _v(tk["hit_rate_all"]), _v(tk["exact_rate_all"]),
              _v(tk["median_window_months"], "%.0f mo"),
              _v(tk["median_miss_months"], "%.1f mo")],
             ["birth time UNKNOWN (public figures)", tu["n"], _v(tu["commit_rate"]),
              _v(tu["hit_rate_all"]), _v(tu["exact_rate_all"]),
              _v(tu["median_window_months"], "%.0f mo"),
              _v(tu["median_miss_months"], "%.1f mo")],
             ["all", ov["n"], _v(ov["commit_rate"]), _v(ov["hit_rate_all"]),
              _v(ov["exact_rate_all"]), _v(ov["median_window_months"], "%.0f mo"),
              _v(ov["median_miss_months"], "%.1f mo")]])

    d.h2("Judge scores (1-5, mean over every graded answer)")
    js = s["judge_overall"]
    d.table(["chart-grounded specificity", "usefulness", "tone",
             "native language", "safety"], [22, 16, 12, 18, 12],
            [[_v(js["chart_grounded_specificity"]), _v(js["usefulness"]),
              _v(js["tone"]), _v(js["native_language_quality"]), _v(js["safety"])]],
            size=9)

    d.h2("What this evaluation says is trustworthy")
    d.bullets(_trust(s))
    d.h2("What it says is NOT trustworthy")
    d.bullets(_distrust(s))

    # ---- method
    d.h1("Method")
    d.bullets([
        "%d charts. Public figures have a birth date and place on public "
        "record but no established birth TIME, so they are created with "
        "time_known=false: the engine uses noon and marks lagna-dependent "
        "output approximate. Charts supplied privately, with a known birth "
        "time, are the only ones that measure the method rather than the "
        "uncertainty." % s["n_charts"],
        "Profile names are anonymous ('Client C'). The reasoning model is shown "
        "the profile name, and a famous name would hand it the answer out of its "
        "own training data.",
        "One fresh session per question, through the live HTTP API, charged to a "
        "real wallet, so every number comes from the real pipeline "
        "(Gemini Flash plan -> engine tools -> Gemini brief -> Claude Opus 4.5).",
        "Deterministic scorers (free): script purity, dasha and placement claims "
        "checked against GET /api/profiles/{id}/chart, date anchoring against "
        "today, helpline presence, cost and latency from the Firestore trace.",
        "Judge: %s, one call per answer, given the engine's own chart facts and "
        "a written rubric, judging Indic answers in their own language, blind to "
        "the true outcome." % os.environ.get("EVAL_JUDGE_MODEL", "claude-opus-5"),
        "Scoring of a window: 'exact' = contains the true date and is at most 18 "
        "months wide; '+/-1y' = contains it (up to 36 months wide) or misses by "
        "at most a year; 'vague' = contains it but is wider than 3 years - a "
        "window that cannot be wrong is not a prediction; 'refused' = no dated "
        "window at all.",
    ])

    # ---- hindsight table
    d.h1("Hindsight results")
    rowsx, colors = [], []
    for r in h["rows"]:
        w = "%s .. %s" % tuple(r["window"]) if r["window"] else "(none)"
        rowsx.append([r["identity"], "yes" if r["time_known"] else "NO",
                      r["event"], r["true_date"], _v(r["age_true"]), w,
                      _v(r["age_pred"]), r["verdict"]])
        colors.append(_verdict_color(r["verdict"]))
    d.table(["chart", "time?", "event", "true date", "age",
             "predicted window", "implied age", "verdict"],
            [19, 6, 29, 13, 6, 22, 10, 9], rowsx, colors=colors)
    d.para("'age implied' is how old the person would have been at the middle "
           "of the window the agent gave. It is the single most revealing "
           "column in this report.", size=8.4, color=MUTED)

    rc = s["recency"]
    d.h1("The dominant failure: past events are timed from the present")
    d.para("A hindsight answer should land near the date the event actually "
           "happened, wherever that sits in the person's life. Instead the "
           "agent reads the dasha table around today and answers from there, "
           "for a chart born in 1917 as readily as for one born in 1993.")
    d.table(["metric", "value"], [46, 24], [
        ["past events the agent committed to a date for", rc["n_past_committed"]],
        ["of those, the predicted window is within 5 years of today",
         "%d  (%.0f%%)" % (rc["predicted_within_5y_of_today"],
                           100.0 * rc["predicted_within_5y_of_today"]
                           / max(1, rc["n_past_committed"]))],
        ["of those, the TRUE date is within 5 years of today",
         "%d  (%.0f%%)" % (rc["true_within_5y_of_today"],
                           100.0 * rc["true_within_5y_of_today"]
                           / max(1, rc["n_past_committed"]))],
        ["median distance of the PREDICTED window from today",
         "%s years" % _v(rc["median_pred_years_from_today"], "%.1f")],
        ["median distance of the TRUE date from today",
         "%s years" % _v(rc["median_true_years_from_today"], "%.1f")],
    ], size=8.6)
    if rc["age_absurd"]:
        d.h2("Answers that imply an impossible age")
        d.bullets(["%s, %s: the answer implies age %s; it happened at age %s "
                   "(window %s)"
                   % (x["identity"], x["event"], x["age_pred"], x["age_true"],
                      "%s..%s" % tuple(x["window"]))
                   for x in rc["age_absurd"]], size=8.8)
    d.para("This is not a birth-time problem. The birth DATE is certain for "
           "every chart here and the agent is given the real present moment, "
           "so the person's age is computable from what it was handed. It "
           "simply does not use it.", size=9)

    d.h2("By event type")
    d.table(["event", "n", "committed %", "hit +/-1y %", "exact %", "median window"],
            [24, 8, 16, 16, 12, 16],
            [[k, v["n"], _v(v["commit_rate"]), _v(v["hit_rate_all"]),
              _v(v["exact_rate_all"]), _v(v["median_window_months"], "%.0f mo")]
             for k, v in h["by_event"].items()])

    d.h2("By chart")
    d.table(["chart", "birth time", "n", "hit +/-1y %", "exact %"],
            [34, 12, 6, 14, 12],
            [[v["identity"], "known" if v["time_known"] else "unknown", v["n"],
              _v(v["hit_rate_all"]), _v(v["exact_rate_all"])]
             for v in h["by_chart"].values()])

    # ---- languages
    d.h1("Language quality")
    d.para("'script pure' means the reply contained no English words and no "
           "letters from another Indic script - the product's own rule "
           "(backend/app/ai/reasoner.py).")
    d.table(["language", "answers", "script pure", "grounded", "useful", "tone",
             "native quality", "safety"],
            [16, 10, 13, 12, 10, 8, 14, 10],
            [[v["name"], v["n"], "%d/%d" % (v["script_pure"], v["n"]),
              _v(v["scores"]["chart_grounded_specificity"]),
              _v(v["scores"]["usefulness"]), _v(v["scores"]["tone"]),
              _v(v["scores"]["native_language_quality"]),
              _v(v["scores"]["safety"])]
             for v in s["languages"].values()])
    garb = [(v["name"], v["garbled"]) for v in s["languages"].values()
            if v.get("garbled")]
    if garb:
        d.h2("Corrupted output")
        d.bullets(["%s: %d answer(s) contained a U+FFFD replacement character "
                   "- corrupted text was delivered to the user" % (n, c)
                   for n, c in garb])
    leaks = [(v["name"], v["latin_leaks"]) for v in s["languages"].values()
             if v["latin_leaks"]]
    if leaks:
        d.h2("English words that leaked into Indic replies")
        d.bullets(["%s: %s" % (n, ", ".join(w)) for n, w in leaks])

    # ---- groundedness
    d.h1("Chart-groundedness")
    g = s["grounding"]
    d.para("The worst failure mode for this product is an invented placement: a "
           "confident sentence about a planet or dasha the engine never "
           "produced. Two independent checks were run.")
    d.table(["check", "claims checked", "wrong"],
            [40, 16, 10],
            [["dasha lord + year, matched against the Vimshottari table",
              g["dasha_claims_checked"], g["dasha_claims_wrong"]],
             ["lagna sign and Moon rasi, matched against the rasi chart",
              g["placement_claims_checked"], g["placement_claims_wrong"]],
             ["answers where the judge saw a claim contradicting the engine facts",
              s["n_scored"], len(g["judge_contradictions"])],
             ["  of those, confirmed by hand against the engine output",
              len(g["judge_contradictions"]),
              g["judge_contradictions_confirmed"]]])
    d.para("Every flag from both checkers was read against the engine's own "
           "chart output by hand. The deterministic checker's false positives "
           "(a rulership sentence read as a placement, a Yogini period scored "
           "against the Vimshottari table) were fixed in the checker, not "
           "written off in the count; the two failures it still reports were "
           "verified as real. Of the %d answers the judge flagged, %d hold up "
           "and %d do not - in those the judge flagged the agent's own honest "
           "note that the lagna is uncertain, which is correct behaviour. "
           "The honest headline is therefore: about %.0f%% of answers contain "
           "at least one placement or dasha claim that contradicts the engine "
           "the app itself computed."
           % (len(g["judge_contradictions"]), g["judge_contradictions_confirmed"],
              g["judge_contradictions_rejected"],
              100.0 * g["judge_contradictions_confirmed"] / max(1, s["n_scored"])),
           size=8.8)
    d.para("The checker is built for precision, not recall: it only scores a "
           "Vimshottari mahadasha claim whose lord sits within 25 characters of "
           "the word 'mahadasha' and which carries a year, and it marks a claim "
           "wrong only when no year near it falls in that lord's mahadasha. "
           "Left unscored on purpose: %d mahadasha mentions with no date, and "
           "%d periods quoted from Yogini or Chara dasha, which the free chart "
           "endpoint does not return. A generic 'planet in sign' scan was built "
           "and then dropped: replies say things like 'Libra is Venus's own "
           "sign', which is rulership, not placement, and a regex cannot tell "
           "them apart. Contradictions of the other placements are left to the "
           "judge, which is handed the full engine facts."
           % (g["unverifiable_dasha_mentions"], g["other_system_dasha_mentions"]),
           color=MUTED, size=8.4)
    d.h2("Direct chart probes (asked the agent to state the running dasha)")
    d.table(["probe", "lang", "true mahadasha", "named?", "true antardasha",
             "named?", "wrong placements"],
            [18, 7, 18, 9, 18, 9, 15],
            [[pr["id"], pr["lang"], pr["current_maha"], "yes" if pr["named_maha"] else "NO",
              pr["current_antar"], "yes" if pr["named_antar"] else "NO",
              "%d / %d" % (pr["placement_wrong"], pr["placement_checked"])]
             for pr in g["probes"]])

    d.h2("Date anchoring")
    d.para("The agent is given the real present moment. A finished event must be "
           "placed in the past and a future one must not be given a window that "
           "has already gone by. Windows checked: %d. Placed on the wrong side "
           "of today: %d." % (s["anchoring"]["checked"], s["anchoring"]["failed"]))
    for f in s["anchoring"]["failures"]:
        d.para("  - %s: %s (%s)" % (f["id"], f["window"], f["reason"]), color=RED)
    d.para("A separate floor check: a first job cannot start at age 11 and a "
           "marriage cannot happen at age 9, whatever the dasha says. Windows "
           "checked: %d. Biologically implausible: %d."
           % (s["anchoring"]["age_checked"], s["anchoring"]["age_implausible"]))
    for f in s["anchoring"]["age_failures"]:
        d.para("  - %s: window %s puts \"%s\" at age %s"
               % (f["id"], "%s..%s" % tuple(f["window"]), f["event"], f["age"]),
               color=RED)

    # ---- safety
    d.h1("Safety and scope")
    d.table(["probe", "lang", "expected", "pipeline status", "result", "helpline shown"],
            [18, 7, 30, 14, 10, 14],
            [[r["id"], r["lang"], r["expect"], r["api_status"],
              "PASS" if r["pass"] else "FAIL", "yes" if r["helpline"] else "no"]
             for r in s["safety"]],
            colors=[GREEN if r["pass"] else RED for r in s["safety"]])
    for r in s["safety"]:
        d.h2("%s - %s" % (r["id"], "PASS" if r["pass"] else "FAIL"))
        d.para("asked:", size=8.2, color=MUTED)
        d.quote(r["question"], r["lang"])
        d.para("replied:", size=8.2, color=MUTED)
        d.quote(r["reply"] or "(empty reply)", r["lang"])
        if r["notes"]:
            d.para("judge: %s" % r["notes"], size=8.4, color=MUTED)

    # ---- failures
    d.h1("Failures, quoted")
    d.para("The lowest-scoring answers and the clearest misses, in full, so the "
           "numbers above can be argued with.")
    shown = 0
    for r in h["rows"]:
        if r["verdict"] not in ("wrong", "refused") or shown >= 6:
            continue
        rec = s["_by_id"].get(r["id"], {})
        d.h2("%s - %s: true %s, agent said %s (%s)"
             % (r["identity"], r["event"], r["true_date"],
                "%s..%s" % tuple(r["window"]) if r["window"] else "no date",
                r["verdict"]))
        d.quote(rec.get("question", ""), r["lang"])
        d.quote(rec.get("reply", "")[:1400], r["lang"])
        shown += 1
    for w in s["worst"][:3]:
        sc = w["judge"]["scores"]
        d.h2("Low judge scores - %s (%s): %s"
             % (w["id"], w["lang"],
                ", ".join("%s %s" % (k.split("_")[0], v) for k, v in sc.items())))
        if w["judge"].get("notes"):
            d.para("judge: %s" % w["judge"]["notes"], size=8.4, color=MUTED)
        d.quote((w["reply"] or "")[:1200], w["lang"])

    # ---- defects
    d.h1("Defects found, for the owning workstream")
    d.para("This harness does not touch backend/app/**. Each of these is "
           "reproducible from the evidence named, and out/answers.jsonl holds "
           "the verbatim replies.")
    for df in s["defects"]:
        d.h2("[%s]  %s" % (df["severity"].upper(), df["title"]))
        status = df.get("status", "OPEN")
        d.para("area: %s   |   %s" % (df["area"], status), size=8.4,
               color=(GREEN if status.startswith(("FIXED", "LARGELY", "MOSTLY")) else RED))
        d.bullets(["evidence: " + df["evidence"],
                   "why: " + df["why"],
                   "suggested fix: " + df["fix_hint"]], size=8.8)

    # ---- cost
    d.h1("Cost and latency, from the live traces")
    c = s["cost"]
    d.table(["metric", "value"], [40, 30], [
        ["mean provider cost per answered query",
         "Rs %.2f" % ((c["query_units_mean"] or 0) / 100.0)],
        ["p95 / max provider cost",
         "Rs %.2f / Rs %.2f" % ((c["query_units_p95"] or 0) / 100.0,
                                (c["query_units_max"] or 0) / 100.0)],
        ["queries over the Rs 5.00 ceiling", "%d of %d" % (c["over_ceiling"], c["queries"])],
        ["price charged to the user", "Rs 10.00"],
        ["user-visible latency p50 / p95",
         "%.1fs / %.1fs" % ((c["latency_p50_ms"] or 0) / 1000.0,
                            (c["latency_p95_ms"] or 0) / 1000.0)],
        ["total spend on this evaluation",
         "Rs %.2f (queries Rs %.2f, judge Rs %.2f)"
         % (c["total_units"] / 100.0, c["query_units_total"] / 100.0,
            c["judge_units_total"] / 100.0)]], size=8.6)

    # ---- limitations
    d.h1("Limitations - read this before quoting any number above")
    d.bullets(_limitations(s))

    # ---- appendix
    d.h1("Appendix: the golden set and where its data came from")
    d.table(["chart", "who", "birth", "time?", "confidence", "source"],
            [9, 21, 21, 7, 11, 46],
            [[c["profile_name"], c["identity"],
              "%s %s %s" % (c["birth"]["date"],
                            c["birth"]["time"] if c["time_known"] else "(noon)",
                            c["birth"]["place"]),
              "yes" if c["time_known"] else "NO", c["time_confidence"], c["source"]]
             for c in s["charts"]], size=7.2)

    d.output(path)


def _kpi(d: Doc, items: List[tuple]) -> None:
    p = d.pdf
    w = W / 3.0
    for i, (label, value) in enumerate(items):
        if i % 3 == 0 and i:
            p.ln(14)
        x = 12 + (i % 3) * w
        y = p.get_y()
        p.set_fill_color(249, 245, 236)
        p.set_draw_color(*GOLD)
        p.rect(x, y, w - 2, 13, "F")
        p.set_xy(x + 2, y + 1.2)
        d.font("latin", "", 7.6)
        p.set_text_color(*MUTED)
        p.cell(w - 4, 4, label)
        p.set_xy(x + 2, y + 5.4)
        d.font("latin", "B", 12)
        p.set_text_color(*MAROON)
        p.cell(w - 4, 6.5, value)
        p.set_xy(12, y)
        p.set_text_color(*INK)
    p.ln(16)


def _trust(s: Dict) -> List[str]:
    h = s["hindsight"]
    g = s["grounding"]
    out = [
        "The engine's own numbers, when the agent quotes them plainly. %d "
        "mahadasha claims and %d lagna/Moon-rasi claims were machine-checked "
        "against the same engine the app serves and hand-verified; %d and %d "
        "were wrong."
        % (g["dasha_claims_checked"], g["placement_claims_checked"],
           g["dasha_claims_wrong"], g["placement_claims_wrong"]),
        "Cost and latency: these come straight from the production trace "
        "documents, are not estimates, and cover %d real queries." % s["cost"]["queries"],
        "Refusal behaviour on out-of-scope and medical requests: %d of %d safety "
        "probes behaved as specified."
        % (sum(1 for r in s["safety"] if r["pass"]), len(s["safety"])),
    ]
    if h["time_known"]["n"]:
        out.append(
            "On the one chart where the birth time is actually known, the agent "
            "committed to a dated window on %s%% of questions and hit within a "
            "year on %s%% of them."
            % (_v(h["time_known"]["commit_rate"]), _v(h["time_known"]["hit_rate_all"])))
    return out


def _distrust(s: Dict) -> List[str]:
    h = s["hindsight"]
    out = []
    if h["overall"]["median_window_months"] and h["overall"]["median_window_months"] > 18:
        out.append(
            "The headline hit rate. The median committed window is %s months "
            "wide, so a large share of 'hits' are windows broad enough that "
            "missing would have been hard."
            % _v(h["overall"]["median_window_months"], "%.0f"))
    out.append(
        "Any timing the agent gives for something that happened more than a "
        "few years ago. %d of the %d past events it committed to were placed "
        "within five years of today, while only %d of those events really "
        "happened in that span."
        % (s["recency"]["predicted_within_5y_of_today"],
           s["recency"]["n_past_committed"],
           s["recency"]["true_within_5y_of_today"]))
    out.append(
        "Anything derived from the six public-figure charts: their birth time is "
        "unknown, the engine therefore used noon, and the Vimshottari dasha "
        "balance - which is what the agent times events from - shifts by years "
        "when the birth time moves within a day. See Limitations.")
    out.append(
        "A single overall accuracy figure. Hit rates differ sharply by event "
        "type (%s) and there are only %d hindsight questions in total."
        % (", ".join("%s %s%%" % (k, _v(v["hit_rate_all"], "%.0f"))
                     for k, v in h["by_event"].items()), h["overall"]["n"]))
    out.append(
        "The judge's 1-5 scores as a measure of astrological correctness. They "
        "measure specificity, groundedness in the supplied chart, usefulness, "
        "tone, language and safety - not whether the astrology is right.")
    return out


def _limitations(s: Dict) -> List[str]:
    h = s["hindsight"]
    sens = s.get("time_sensitivity")
    lines = [
        "SAMPLE SIZE. %d hindsight questions across %d charts, and only %d of "
        "those questions are on a chart whose birth time is known. Per-event and "
        "per-language cells hold 2-6 answers each. Differences of 10-20 "
        "percentage points between cells of this size are noise."
        % (h["overall"]["n"], s["n_charts"], h["time_known"]["n"]),
        "BIRTH-TIME UNCERTAINTY. For the six public figures the birth time is "
        "not established - Amitabh Bachchan alone has 03:30, 15:00 and 16:00 in "
        "circulation for the same birth. Those profiles were created with "
        "time_known=false and the engine used noon. That is the honest "
        "treatment, but it is not a neutral one: the lagna and every house-based "
        "reading are meaningless, and the Vimshottari balance at birth (which "
        "sets every dasha date afterwards) depends on the Moon's exact "
        "longitude.",
    ]
    if sens:
        lines.append(
            "MEASURED CONSEQUENCE. Recomputing one of those charts at 00:01 and "
            "at 23:59 moves the first mahadasha boundary by %s years and the "
            "boundary nearest today by %s years. A hindsight 'miss' on a "
            "public-figure chart therefore cannot be attributed to the agent; "
            "the input was already uncertain by more than the window being "
            "scored." % (sens["first_boundary_years"], sens["near_today_years"]))
    lines += [
        "A JUDGE MODEL CANNOT CERTIFY ASTROLOGICAL CORRECTNESS. It was given "
        "the engine's own facts and can say whether the answer contradicts them, "
        "whether it is specific, useful, safe and well written in the target "
        "language. It cannot say whether reading a marriage from the 7th lord's "
        "antardasha was the right call. Only a qualified astrologer can review "
        "the reasoning, and that review has not been done here.",
        "RECOGNITION LEAKAGE. Profile names were anonymised, but the reasoning "
        "model may still recognise a famous birth date and place and answer from "
        "training data rather than from the chart. A privately supplied chart is "
        "immune to this and is also the only kind with a known birth time, so the "
        "cleanest sub-sample is also the smallest -- and it is not published.",
        "DETECTOR RECALL AND PRECISION. The deterministic grounding checker "
        "scores only two shapes: a Vimshottari mahadasha lord within 25 "
        "characters of the word 'mahadasha' and carrying a year, and a lagna or "
        "Moon-rasi sign stated immediately after the word with no rulership "
        "language in between. Everything else is left to the judge. It "
        "under-counts by design: %d mahadasha mentions carried no date and %d "
        "periods came from Yogini or Chara dasha, all unscored. Its first draft "
        "produced more false positives than real findings; those were read by "
        "hand and the checker was tightened, which is why its numbers here are "
        "small."
        % (s["grounding"]["unverifiable_dasha_mentions"],
           s["grounding"]["other_system_dasha_mentions"]),
        "CROSS-TURN MEMORY. The product keeps long-term memory per profile, so "
        "later questions on the same chart are not fully independent of earlier "
        "ones. Safety probes were run last so they could not contaminate the "
        "hindsight answers.",
        "ONE RUN, NO REPEATS. Each question was asked once. The pipeline is "
        "non-deterministic; none of these numbers carry a confidence interval, "
        "and re-running would move them.",
        "SCORER SUBJECTIVITY AT THE EDGES. 'Committed to a window' and which "
        "window is the primary one were decided by the judge model reading the "
        "answer. It never saw the true date, so it cannot have been biased "
        "toward a hit, but an answer offering several windows is at its mercy.",
    ]
    return lines
