#!/usr/bin/env python3
"""Measure real per-query cost against the live model APIs (run after deploy).

Sends one sample question per language (hi, te, ta, kn, ml) through the REAL
pipeline in dry-run mode — no wallet charge and no Firestore writes — and
prints per-stage tokens and ₹ cost, plus Opus output tokens per word (use it
to calibrate costs.TOKENS_PER_WORD).

    cd backend
    ANTHROPIC_API_KEY=... GEMINI_API_KEY=... GOOGLE_CLOUD_PROJECT=<project> \
        python scripts/ai_cost_probe.py
    python scripts/ai_cost_probe.py --langs te ml --voice      # + cloud STT/TTS
    python scripts/ai_cost_probe.py --report-chapter           # report tok/word

Needs: ANTHROPIC_API_KEY (Claude Opus 4.5), GEMINI_API_KEY (Gemini Flash),
and for --voice gcloud application-default credentials with Speech/TTS access.
Costs a few rupees per run.
"""

import argparse
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from app.ai import costs, llm, pipeline, speech  # noqa: E402

QUESTIONS = {
    "hi": "मेरी नौकरी में अगले दो साल कैसे रहेंगे? क्या प्रमोशन मिलेगा?",
    "te": "నా ఉద్యోగంలో వచ్చే రెండు సంవత్సరాలు ఎలా ఉంటాయి? ప్రమోషన్ వస్తుందా?",
    "ta": "அடுத்த இரண்டு ஆண்டுகளில் என் வேலை எப்படி இருக்கும்? பதவி உயர்வு கிடைக்குமா?",
    "kn": "ಮುಂದಿನ ಎರಡು ವರ್ಷಗಳಲ್ಲಿ ನನ್ನ ಉದ್ಯೋಗ ಹೇಗಿರುತ್ತದೆ? ಬಡ್ತಿ ಸಿಗುತ್ತದೆಯೇ?",
    "ml": "അടുത്ത രണ്ട് വർഷം എന്റെ ജോലി എങ്ങനെയായിരിക്കും? പ്രമോഷൻ കിട്ടുമോ?",
}

PROFILE = {"id": "probe", "name": "Probe", "relation": "self", "time_known": True,
           "birth": {"date": "1990-05-17", "time": "14:30", "tz": "Asia/Kolkata",
                     "lat": 17.385, "lon": 78.4867, "place": "Hyderabad"}}

FLAGS = {"voice_cloud_enabled": True, "opus_enabled": True,
         "query_price_units": int(os.environ.get("QUERY_PRICE_UNITS", "1000")),
         "cost_ceiling_units": int(os.environ.get("QUERY_COST_CEILING_UNITS", "500")),
         "maintenance_message": ""}


def _words(text: str) -> int:
    return max(1, len(text.split()))


def print_trace(label: str, r) -> None:
    t = r.trace
    print("\n== %s  status=%s  latency=%.1fs" % (label, t["status"], t["latency_ms"] / 1000))
    print("  %-7s %-28s %8s %8s %8s" % ("stage", "model", "in/units", "out", "₹"))
    for s in t["stages"]:
        print("  %-7s %-28s %8s %8s %8.2f" % (
            s["name"], s.get("model", "")[:28], s.get("in_tok", s.get("units", "")),
            s.get("out_tok", ""), s["cost_units"] / 100.0))
    print("  %-7s %-28s %8s %8s %8.2f   (ceiling ₹%.2f)" % (
        "TOTAL", "", "", "", t["cost_units"] / 100.0, FLAGS["cost_ceiling_units"] / 100.0))
    reason = next((s for s in t["stages"] if s["name"] == "reason"), None)
    if reason:
        print("  reason: max_tokens=%s stop=%s exact_count=%s shrunk=%s  "
              "out tokens/word=%.2f" % (
                  reason["detail"]["max_tokens"], reason["detail"]["stop"],
                  reason["detail"]["exact_count"], reason["detail"]["shrunk"],
                  reason["out_tok"] / _words(r.reply)))
    if t.get("error"):
        print("  error:", t["error"])
    print("  reply: %s…" % r.reply[:160].replace("\n", " "))


def _tts_linear16(text: str, lang: str) -> bytes:
    """Make a spoken question for the STT leg (Standard voice, 16 kHz PCM)."""
    from google.cloud import texttospeech as tts
    name, _ = speech.voice_for(lang)
    r = speech._tts_client().synthesize_speech(
        input=tts.SynthesisInput(text=text),
        voice=tts.VoiceSelectionParams(language_code=speech.LOCALES[lang], name=name),
        audio_config=tts.AudioConfig(audio_encoding=tts.AudioEncoding.LINEAR16,
                                     sample_rate_hertz=16000))
    data = r.audio_content
    return data[44:] if data[:4] == b"RIFF" else data


def probe_queries(langs, voice: bool) -> None:
    totals = []
    for lang in langs:
        session = {"id": "probe-%s" % lang, "uid": "probe", "profile_id": "probe",
                   "lang": lang, "mode": "voice" if voice else "text", "summary": ""}
        kw = {"text": QUESTIONS[lang]}
        if voice:
            kw = {"audio": _tts_linear16(QUESTIONS[lang], lang), "want_tts": True}
        t0 = time.time()
        r = pipeline.run_query("probe", session, dry_run=True, prechecked=FLAGS,
                               profile=PROFILE, memory_facts=[], **kw)
        r.wait()      # the memory stage and the trace are filed off-thread
        print_trace("%s %s (%.1fs)" % (lang, "voice" if voice else "text", time.time() - t0), r)
        if voice:
            print("  transcript: %s" % r.transcript)
        totals.append(r.trace["cost_units"])
    print("\nper-query cost ₹: min %.2f  max %.2f  mean %.2f  (price ₹%.2f)" % (
        min(totals) / 100, max(totals) / 100, sum(totals) / len(totals) / 100,
        FLAGS["query_price_units"] / 100))


def probe_report_chapter(langs) -> None:
    from app import agent  # noqa: F401  (engine path)
    from app import reports
    from app.ai import repo
    birth = repo.birth_of(PROFILE)
    bundle = reports._bundle(birth)
    for lang in langs:
        text, stages = reports._write_chapter(
            bundle, lang, birth["year"], 400,
            "Write chapter 4 of 18: \"Career and Profession\".\nCoverage: 10th house, "
            "D-10, dashas, year windows.")
        out = sum(s.out_tok for s in stages)
        cost = sum(s.cost for s in stages)
        tpw = out / _words(text)
        est = reports.estimate_cost_units(lang, tpw=tpw)
        print("%s: %d words, %d out tokens -> %.2f tok/word; chapter ₹%.2f "
              "(cache write %d, read %d); full report at this rate ≈ ₹%.0f, margin %.1f%%"
              % (lang, _words(text), out, tpw, cost / 100,
                 stages[0].cache_write_tok, stages[0].cache_read_tok,
                 est["total_units"] / 100, est["margin_pct"]))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--langs", nargs="*", default=list(QUESTIONS))
    ap.add_argument("--voice", action="store_true", help="also exercise cloud STT + TTS")
    ap.add_argument("--report-chapter", action="store_true",
                    help="measure report tokens/word with a 400-word chapter per language")
    a = ap.parse_args()
    if not llm.ANTHROPIC_API_KEY:
        sys.exit("Set ANTHROPIC_API_KEY")
    if not (llm.GEMINI_API_KEY or llm.GEMINI_USE_VERTEX):
        sys.exit("Set GEMINI_API_KEY (or GEMINI_USE_VERTEX=1)")
    print("models: flash=%s  opus=%s  USD_TO_INR=%.0f" % (
        llm.GEMINI_MODEL, llm.CLAUDE_MODEL, costs.USD_TO_INR))
    if a.report_chapter:
        probe_report_chapter(a.langs)
    else:
        probe_queries(a.langs, a.voice)


if __name__ == "__main__":
    main()
