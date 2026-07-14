"""Mega life report: ~1,00,000-word Vedic analysis generated with Opus 4.8.

A report is 18 chapters generated sequentially in a background thread; each
call reuses the same cached astrological context (full_analysis bundle), so
input cost stays low while output quality stays chapter-focused. Sections
land in DynamoDB as they finish, so the client can show live progress and
the reader works even mid-generation. Total failure refunds the fee.
"""

import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

from . import billing, config, db

log = logging.getLogger("udhyath.reports")

from jyotish import api as jyotish_api  # engine path prepared by app.agent

# (key, title, coverage notes for the writer)
SECTIONS: List[tuple] = [
    ("overview", "Your Chart — The Blueprint of This Life",
     "Lagna, Moon, Sun, chart pattern, the 3 defining signatures of this "
     "horoscope, how the material and spiritual threads of this life weave "
     "together. Set the tone for the whole report."),
    ("personality", "Personality, Mind and Inner Nature",
     "Lagna and its lord, Moon nakshatra psychology, Mercury (intellect), "
     "strengths, blind spots, karmic temperament, how others perceive them."),
    ("past", "The Story So Far — Your Past, Decoded",
     "Walk dasha-by-dasha from birth to today. For each maha/antar period "
     "give the approximate calendar years and what likely happened: studies, "
     "moves, family events, career turns, emotional chapters. Be specific "
     "about years. This chapter builds trust — anchor every claim in a dasha "
     "or transit."),
    ("career", "Career and Profession",
     "10th house across D-1/D-10/chalit, KP cuspal analysis, Saturn and "
     "karma karaka in nadi, suitable fields, job vs business, recognition, "
     "promotions with year windows, career peaks and rough patches ahead."),
    ("business", "Business, Enterprise and Partnerships",
     "7th house (partnerships), 3rd (initiative), 11th (gains), lagna-lord "
     "strength for independent ventures, favourable business lines, timing "
     "windows for launches, partners to choose or avoid."),
    ("finance", "Wealth, Money and Assets",
     "2nd and 11th houses, dhana yogas found, Ashtakavarga strength of "
     "wealth signs, periods of accumulation vs drain with years, property "
     "and vehicles (4th house), inheritance, debt discipline."),
    ("marriage", "Marriage and Life Partner",
     "7th house, Venus/Jupiter, navamsa in depth, KP 7th cusp sub lord, "
     "spouse nature and direction, marriage timing windows (or married-life "
     "phases if already married), harmony periods and friction periods with "
     "remedies."),
    ("children", "Children and Progeny",
     "5th house, D-7 saptamsa, Jupiter, putra karaka, timing windows for "
     "children, their temperament and your relationship with them, what "
     "their charts inherit from this one."),
    ("parents", "Parents and Ancestral Blessings",
     "4th house and Moon (mother), 9th and Sun (father), pitru factors, "
     "their health phases, your duties and karmic debts to them, ancestral "
     "property indications."),
    ("siblings", "Brothers, Sisters and Cousins",
     "3rd house (younger), 11th (elder), Mars (brothers), co-borns' fortunes "
     "intertwined with yours, cousins and extended family dynamics, support "
     "vs rivalry periods."),
    ("friends", "Friends, Allies and Social World",
     "11th house, benefics aspecting lagna, the kind of friends fate sends, "
     "who to trust, community standing, public image phases."),
    ("health", "Health and Vitality",
     "Lagna strength, 6th/8th/12th, shadbala of the lagna lord, body "
     "constitution by element, vulnerable periods by dasha with years, "
     "long-life indications, preventive guidance. No medical guarantees."),
    ("education", "Education, Knowledge and Skills",
     "4th/5th/9th houses, Mercury-Jupiter axis, learning style, higher "
     "education phases, competitive success windows, lifelong skills the "
     "chart rewards."),
    ("foreign", "Travel, Foreign Lands and Relocation",
     "12th house, chara rasi factors, Rahu, videsha yoga check, when travel "
     "or relocation is favoured, which directions suit."),
    ("spiritual", "The Spiritual Path — Your Inner Journey",
     "9th and 12th houses, Ketu and Jupiter, atmakaraka in nadi, past-life "
     "indications, the deity/energies this chart naturally connects to, "
     "meditation and sadhana suited to the Moon nakshatra, moksha direction."),
    ("forecast", "The Next Twenty Years — Year by Year",
     "Using the dasha timelines and Jupiter/Saturn transits, give a year-by-"
     "year forecast for the next 20 years: theme of each year, best months "
     "to act, cautions. This is the longest chapter — be concrete."),
    ("remedies", "Remedies, Gemstones and Mantras",
     "Gemstone recommendations with wearing method, mantras per weak planet "
     "with counts and days, charity/seva suited to the chart, fasting days, "
     "Lal Kitab upay found, temple/deity guidance."),
    ("closing", "Key Dates and Final Words",
     "A condensed table-like summary of the most important date windows "
     "from every chapter, the 5 rules this soul should live by, and a "
     "dignified closing blessing."),
]

_STYLE = """You are Udhyath, a master Vedic astrologer writing one chapter of
a premium, paid life report. Rules:
- Write in {lang_name}. Warm, dignified, personal — address the native as
  "you". No headers about the report itself, no meta-commentary, no
  apologies. Start directly with the chapter content.
- Ground EVERY claim in the chart data provided: name the dasha, house,
  yoga, KP sub lord or transit behind each statement. Give calendar years
  for all timing (birth {birth_year}; compute ages/years from dashas).
- Synthesize systems: whole-sign vs chalit houses, Ashtakavarga strength,
  KP significators, nadi stellar delivery, shadbala, all four dashas.
- Be honest about uncertainty; astrology shows tendencies. No medical,
  legal or financial guarantees.
- Length: about {words} words for this chapter. Use short sub-headings and
  flowing paragraphs; no bullet spam.
- The full data bundle is authoritative — never invent placements."""


def _complete(system_blocks: List[Dict], prompt: str, max_tokens: int,
              thinking: bool = False):
    """Provider-aware single completion. Returns (text, provider)."""
    from . import agent
    if config.INFERENCE_PROVIDER == "aicredits":
        system_text = "\n\n".join(b["text"] for b in system_blocks)
        req = {"model": config.AICREDITS_MODEL, "max_tokens": max_tokens,
               "messages": [{"role": "system", "content": system_text},
                            {"role": "user", "content": prompt}]}
        resp = agent._compat_request(req)
        return (resp["choices"][0]["message"].get("content") or "").strip()
    kwargs = dict(model=config.REPORT_MODEL, max_tokens=max_tokens,
                  system=system_blocks,
                  messages=[{"role": "user", "content": prompt}])
    if thinking:
        kwargs["thinking"] = {"type": "adaptive"}
    resp = agent.client().messages.create(**kwargs)
    return "".join(b.text for b in resp.content if b.type == "text").strip()


def _context_blocks(bundle: str, lang: str, birth_year: int, words: int) -> List[Dict]:
    lang_name = {"te": "Telugu", "hi": "Hindi"}.get(lang, "English")
    return [
        {"type": "text",
         "text": _STYLE.format(lang_name=lang_name, birth_year=birth_year,
                               words=words)},
        {"type": "text",
         "text": "ASTROLOGICAL DATA BUNDLE (full_analysis):\n" + bundle,
         "cache_control": {"type": "ephemeral"}},
    ]


def report_fee_units(lang: str) -> int:
    return (config.REPORT_FEE_UNITS_INDIC if lang in ("te", "hi")
            else config.REPORT_FEE_UNITS)


def generate_teaser(birth: Dict, lang: str = "en") -> Dict:
    """~100-word free preview that shows real insight and sells the report."""
    bundle = json.dumps(jyotish_api.full_analysis(birth), default=str)
    lang_name = {"te": "Telugu", "hi": "Hindi"}.get(lang, "English")
    teaser = _complete(
        _context_blocks(bundle, lang, int(birth["year"]), 100),
        "Write a ~100-word teaser in %s for this person's full life "
        "report. Include exactly TWO strikingly specific, verifiable "
        "hooks from their chart (one about their past with a year, one "
        "about their future with a year window) and ONE intriguing "
        "unanswered question the full report resolves. End mid-thought "
        "with '…'. No greetings, no sales language like 'buy now'."
        % lang_name, 700)
    return {
        "teaser": teaser,
        "full_report": {
            "words": "≈1,00,000",
            "chapters": [t for _, t, _ in SECTIONS],
            "price": report_fee_units(lang) / 100.0,
            "currency": config.CURRENCY,
            "delivery": "Generated chapter by chapter; usually ready in "
                        "30-45 minutes.",
        },
    }


def _generate_section(bundle: str, lang: str, birth_year: int,
                      words: int, prompt: str) -> str:
    """One chapter. Long chapters go in two half-passes so no single call
    outlives gateway/HTTP timeouts (~70 tok/s upstream)."""
    def _mt(w):
        return min(int(w * 2.2) + 1200, 24000)
    if words <= 3000:
        return _complete(_context_blocks(bundle, lang, birth_year, words),
                         prompt, _mt(words), thinking=True)
    half = words // 2
    blocks = _context_blocks(bundle, lang, birth_year, half)
    p1 = _complete(blocks, prompt +
                   "\nWrite the FIRST HALF of this chapter (about %d words). "
                   "Do not conclude — stop at a natural mid-point." % half,
                   _mt(half), thinking=True)
    p2 = _complete(blocks, prompt +
                   "\nThe first half of this chapter is already written; it "
                   "ends with:\n\u2026%s\n\nWrite the SECOND HALF (about "
                   "%d words): continue seamlessly, do not repeat covered "
                   "points, and bring the chapter to its conclusion."
                   % (p1[-600:], half), _mt(half), thinking=True)
    return p1.rstrip() + "\n\n" + p2.lstrip()


def _generate(report_id: str, email: str, birth: Dict, lang: str) -> None:
    try:
        bundle = json.dumps(jyotish_api.full_analysis(birth), default=str)
        words = config.REPORT_SECTION_WORDS
        birth_year = int(birth["year"])
        already = {s["idx"] for s in db.list_report_sections(report_id)}
        for idx, (key, title, coverage) in enumerate(SECTIONS, 1):
            if idx in already:  # resume: keep chapters from a prior attempt
                db.update_report(email, report_id,
                                 sections_done=idx, status="generating")
                continue
            prompt = ("Write chapter %d of %d: \"%s\".\nCoverage: %s"
                      % (idx, len(SECTIONS), title, coverage))
            content = None
            for attempt in (1, 2):
                try:
                    content = _generate_section(bundle, lang, birth_year,
                                                words, prompt)
                    if content:
                        break
                except Exception as exc:
                    log.warning("report %s sec %s attempt %d: %s",
                                report_id, key, attempt, exc)
            if not content:
                raise RuntimeError("section %s failed twice" % key)
            db.add_report_section(report_id, idx, title, content)
            db.update_report(email, report_id,
                             sections_done=idx, status="generating")
            log.info("report %s: %d/%d done", report_id, idx, len(SECTIONS))
        db.update_report(email, report_id, status="ready",
                         completed_at=datetime.now(timezone.utc).isoformat())
    except Exception as exc:
        log.error("report %s FAILED: %s — refunding", report_id, exc)
        try:
            meta = db.get_report(email, report_id) or {}
            billing.credit(email, int(meta.get("fee_units",
                                               config.REPORT_FEE_UNITS)))
        except Exception:
            log.error("refund failed for %s / %s", email, report_id)
        db.update_report(email, report_id, status="failed", error=str(exc))


def start_report(email: str, birth: Dict, lang: str) -> Dict:
    """Charge the language-specific fee and launch background generation."""
    fee = report_fee_units(lang)
    billing.charge(email, fee)  # raises on low balance
    report_id = uuid.uuid4().hex[:12]
    db.create_report(email, report_id, birth, lang, fee, len(SECTIONS))
    t = threading.Thread(target=_generate,
                         args=(report_id, email, birth, lang), daemon=True)
    t.start()
    return {"report_id": report_id, "status": "generating",
            "sections_total": len(SECTIONS)}


def resume_report(email: str, report_id: str) -> Dict:
    """Re-charge and finish a failed report, keeping completed chapters."""
    meta = db.get_report(email, report_id)
    if meta is None:
        raise ValueError("Report not found")
    if meta["status"] != "failed":
        raise ValueError("Only failed reports can be resumed")
    lang = meta.get("lang", "en")
    fee = report_fee_units(lang)
    billing.charge(email, fee)  # the failed attempt was refunded in full
    db.update_report(email, report_id, status="generating", error=None,
                     fee_units=fee)
    birth = json.loads(meta["birth"])
    t = threading.Thread(target=_generate,
                         args=(report_id, email, birth, lang), daemon=True)
    t.start()
    done = len(db.list_report_sections(report_id))
    return {"report_id": report_id, "status": "generating",
            "sections_done": done, "sections_total": len(SECTIONS)}
