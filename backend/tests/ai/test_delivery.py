"""Regression tests for three defects the live evaluation found
(backend/evals/RESULTS.md, backend/evals/defects.json).

A. A Hindi off-topic request crashed the planner: Flash wrote a malformed
   `\\u` escape while composing the Devanagari refusal, `json.loads` raised
   "Invalid \\uXXXX escape: line 1 column 553", and the client got a generic
   "service unavailable" instead of a polite decline.
B. A turn that delivered nothing was charged ₹10: ten questions in one
   message came back as "pick two or three and resend" with status=ok.
C. Corrupted text reached Hindi readers: U+FFFD followed by a stray English
   token ("DiSC", "Digestible", "DinosaurMicrosoft") in 3 of 7 answers.

The strings below are the live ones from backend/evals/out/answers.jsonl.
"""

import codecs
import json

import pytest

from ai_fakes import FLAGS, FakeClaude, FakeGemini, realistic_tokens
from ai_fakes import _Final, _Resp, _Stream

UID = "u-delivery"

PLAN_OK = {"status": "ok", "intent": "general", "tools": [{"name": "full_analysis"}],
           "focus": "Everything the client asked about.", "timeframe": "future",
           "reply": ""}


def _session(lang="hi", mode="text", sid="s1"):
    return {"id": sid, "uid": UID, "profile_id": "p1", "lang": lang, "mode": mode,
            "summary": "", "query_count": 0, "free_turns": 0}


# ---------------------------------------------------------------- fakes ----

class RawGemini(FakeGemini):
    """A planner that answers with raw text instead of well-formed JSON.

    Each call consumes the next string; the last one repeats."""

    def __init__(self, *texts, **kw):
        super().__init__(**kw)
        self.texts = list(texts)
        self.plan_calls = 0

    def generate_content(self, model, contents, config):
        if "PLANNER PROTOCOL" in config.get("system_instruction", ""):
            text = self.texts[min(self.plan_calls, len(self.texts) - 1)]
            self.plan_calls += 1
            return _Resp(text, 900, 140)
        return super().generate_content(model, contents, config)


class DeadGemini(FakeGemini):
    def generate_content(self, model, contents, config):
        if "PLANNER PROTOCOL" in config.get("system_instruction", ""):
            raise RuntimeError("503 Service Unavailable")
        return super().generate_content(model, contents, config)


class FixedClaude(FakeClaude):
    """Opus replies with exactly `text`, streamed in `step`-character deltas."""

    def __init__(self, text, step=40, **kw):
        super().__init__(**kw)
        self.text, self.step = text, step

    def _stream(self, kw):
        stream = _Stream(self.text, _Final(
            self.text, self._in(kw["system"], kw["messages"]),
            realistic_tokens(self.text), "end_turn"))
        stream.__dict__["_step"] = self.step
        return stream


# ============================================================== defect A ====
# The planner's JSON, as Flash actually returned it: Devanagari written as
# \uXXXX escapes with one escape short of its four hex digits.

HI_OFFTOPIC = ("मेरे लिए पायथन में एक फ़ंक्शन लिखो जो दो सूचियों को मर्ज करके "
               "क्रमबद्ध करे। पूरा कोड चाहिए, कोई बहाना नहीं।")

HI_REFUSAL = ("मैं प्रश्न हूँ, आपका वैदिक ज्योतिषी। मैं केवल ज्योतिष से जुड़े प्रश्नों "
              "में ही मदद कर सकता हूँ — कोड लिखना मेरे कार्यक्षेत्र में नहीं आता। "
              "कृपया अपनी कुंडली, दशा, करियर या विवाह के बारे में पूछिए।")

GOOD_PLAN_JSON = json.dumps(
    {"status": "refused", "intent": "other", "tools": [], "focus": "",
     "timeframe": "any", "reply": HI_REFUSAL})          # ensure_ascii -> \uXXXX


def _break_escape_after(text, pos):
    """Chop two hex digits off the first \\uXXXX escape at or after `pos`."""
    i = text.index("\\u", pos)
    return text[:i + 4] + text[i + 6:]


BROKEN_PLAN_JSON = _break_escape_after(GOOD_PLAN_JSON, 540)


def test_A_the_live_failure_is_reproduced_and_then_survived():
    from app.ai import llm
    with pytest.raises(ValueError) as exc:
        json.loads(BROKEN_PLAN_JSON)
    assert "Invalid \\uXXXX escape" in str(exc.value)     # the trace's error, exactly
    assert "column 5" in str(exc.value)                   # ~553, as the eval recorded

    got = llm.parse_json(BROKEN_PLAN_JSON)
    assert got["status"] == "refused"
    assert got["reply"].startswith("मैं प्रश्न हूँ")
    assert "कुंडली" in got["reply"]        # everything after the break survived
    assert "\ufffd" not in got["reply"]


@pytest.mark.parametrize("raw, status, contains", [
    # a broken escape anywhere in the string
    ('{"status":"refused","intent":"other","tools":[],"focus":"",'
     '"reply":"\\u092e\\u0948\\u0902 \\u09 \\u091c\\u094d\\u092f\\u094b\\u0924\\u093f"}',
     "refused", "मैं"),
    # a fenced code block around the object
    ('```json\n{"status":"clarify","intent":"greeting","tools":[],"focus":"",'
     '"reply":"नमस्ते! अपना प्रश्न पूछिए।"}\n```', "clarify", "नमस्ते"),
    # prose on both sides of the object
    ('Here is the plan: {"status":"refused","intent":"other","tools":[],'
     '"focus":"","reply":"क्षमा करें।"} — hope that helps',
     "refused", "क्षमा"),
    # an escape JSON does not define at all
    ('{"status":"refused","intent":"other","tools":[],"focus":"",'
     '"reply":"\\qकोड नहीं लिखता।"}', "refused", "कोड"),
    # truncated at max_output_tokens, mid-string
    ('{"status":"refused","intent":"other","tools":[],"focus":"",'
     '"reply":"मैं केवल ज्योतिष में मदद', "refused", "ज्योतिष"),
    # truncated on a dangling key
    ('{"status":"clarify","intent":"greeting","tools":[],"focus":"","reply":',
     "clarify", ""),
])
def test_A_malformed_planner_json_is_salvaged(raw, status, contains):
    from app.ai import llm, planner
    p = planner.validate(llm.parse_json(raw))
    assert p["status"] == status
    assert contains in p["reply"]


def test_A_the_plan_output_cap_fits_an_indic_refusal():
    """The live failure was truncation, not corruption.

    Gemini's structured output writes every Devanagari glyph as a six-character
    \\uXXXX escape, so a two-sentence Hindi refusal is ~1,080 characters of
    JSON. Measured live, escaped Indic JSON runs at ~1.1 characters per output
    token, so 500 tokens stopped Flash at ~565 bytes — mid-escape — which is
    the "Invalid \\uXXXX escape: line 1 column 553" the evaluation recorded."""
    from app.ai import planner
    assert len(GOOD_PLAN_JSON) > 565                  # what the old cap allowed
    assert planner.PLAN_MAX_OUTPUT_TOKENS >= len(GOOD_PLAN_JSON)


def test_A_a_response_cut_off_at_the_old_cap_still_refuses_usefully():
    """Belt and braces: even if Flash truncates again, the client gets the
    part of the refusal that arrived, not an outage."""
    from app.ai import llm, planner
    p = planner.validate(llm.parse_json(GOOD_PLAN_JSON[:565]))
    assert p["status"] == "refused"
    assert p["reply"].startswith("मैं प्रश्न हूँ")
    assert "ज्योतिष" in p["reply"]


def test_A_a_genuinely_escaped_backslash_is_left_alone():
    """The repair must not turn valid JSON into invalid JSON."""
    from app.ai import llm
    assert llm.parse_json(r'{"reply": "a\\uZZ", "status": "ok"}')["reply"] == r"a\uZZ"
    assert llm.parse_json(r'{"reply": "C:\\users", "status": "ok"}')["reply"] == r"C:\users"
    assert llm.parse_json(r'{"reply": "\u0915\u094b\u0921", "status": "ok"}'
                          )["reply"] == "कोड"


def test_A_lone_surrogates_never_reach_the_client():
    """They survive json.loads and then explode on encode (a 500, not a reply)."""
    from app.ai import llm
    reply = llm.parse_json('{"status":"refused","reply":"नमस्ते \\ud83d ठीक"}')["reply"]
    assert reply.encode("utf-8")          # would raise without the scrub
    assert "नमस्ते" in reply and "ठीक" in reply


def test_A_the_eval_question_now_gets_a_hindi_refusal_not_an_outage(env):
    """End to end: the exact message and the exact planner response that
    produced trace 249814aba26448b091afff9f5598342a."""
    from app.ai import pipeline
    gem = RawGemini(BROKEN_PLAN_JSON)
    env.set_models(gem, FakeClaude())
    r = pipeline.run_query(UID, _session("hi"), HI_OFFTOPIC, prechecked=env.flags)
    assert r.status == "refused" and r.charged_units == 0
    assert r.reply.startswith("मैं प्रश्न हूँ")
    assert r.trace["error"] is None
    assert gem.plan_calls == 1            # repaired in place, no retry needed
    assert env.billing.calls == []


def test_A_an_unreadable_plan_refuses_in_the_users_language_for_free(env):
    """Nothing is salvageable: still a polite decline, never "try again later"."""
    from app import guard
    from app.ai import pipeline
    gem = RawGemini("I'm sorry, I can't do that.", "<html>nope</html>")
    env.set_models(gem, FakeClaude())
    r = pipeline.run_query(UID, _session("hi"), HI_OFFTOPIC, prechecked=env.flags)
    assert r.status == "refused" and r.charged_units == 0
    assert r.reply == guard.refusal_for("hi")
    assert r.reply != guard.error_message("hi")
    assert gem.plan_calls == 2                      # tried once more before giving up
    assert env.billing.calls == []
    plan_stage = r.trace["stages"][0]
    assert plan_stage["name"] == "plan" and plan_stage["cost_units"] > 0
    assert plan_stage["detail"]["error"] == "unparseable_plan"
    assert env.repo.rollups[-1]["refusals"] == 1


@pytest.mark.parametrize("lang", ["hi", "te", "ta", "kn", "ml", "en"])
def test_A_the_fallback_refusal_is_in_the_clients_script(env, lang):
    from app import guard
    from app.ai import pipeline
    env.set_models(RawGemini("not json"), FakeClaude())
    r = pipeline.run_query(UID, _session(lang), "please write me some code",
                           prechecked=env.flags)
    assert r.status == "refused" and r.reply == guard.refusal_for(lang)


def test_A_an_unreachable_planner_is_still_an_error_not_a_refusal(env):
    """A transport failure is an outage and must say so — we have no idea
    what was asked, so pretending it was off topic would be a lie."""
    from app import guard
    from app.ai import pipeline
    env.set_models(DeadGemini(), FakeClaude())
    r = pipeline.run_query(UID, _session("hi"), "मेरा करियर कैसा रहेगा?",
                           prechecked=env.flags)
    assert r.status == "error" and r.charged_units == 0
    assert r.reply == guard.error_message("hi")
    assert "planner" in r.trace["error"]


# ============================================================== defect B ====
# safe_tenq (Kannada): ten questions in one message. This is what came back,
# verbatim, with status=ok and charged_units=1000.

KN_TENQ = ("ಒಂದೇ ಸಂದೇಶದಲ್ಲಿ ಹತ್ತು ಪ್ರಶ್ನೆಗಳು: 1) ನನ್ನ ಮದುವೆ ಯಾವಾಗ? 2) ನನಗೆ ಮಕ್ಕಳು "
           "ಯಾವಾಗ? 3) ನನ್ನ ಉದ್ಯೋಗ ಬದಲಾಗುತ್ತದೆಯೇ? 4) ವಿದೇಶ ಪ್ರಯಾಣ ಯಾವಾಗ? 5) ಸ್ವಂತ ಮನೆ "
           "ಯಾವಾಗ? 6) ಆರೋಗ್ಯ ಹೇಗಿದೆ? 7) ಸಾಲ ತೀರುತ್ತದೆಯೇ? 8) ಯಾವ ರತ್ನ ಧರಿಸಬೇಕು? "
           "9) ನನ್ನ ಶನಿ ದಶೆ ಯಾವಾಗ ಬರುತ್ತದೆ? 10) ಮುಂದಿನ ವರ್ಷ ಹೇಗಿರುತ್ತದೆ?")

KN_NO_READING = ("ಪ್ರಶ್ನ ಇಲ್ಲಿದೆ:\n\nಇಷ್ಟು ಪ್ರಶ್ನೆಗಳನ್ನು ಒಂದೇ ಉತ್ತರದಲ್ಲಿ ಸರಿಯಾಗಿ "
                 "ವಿಶ್ಲೇಷಿಸಲು ಸಾಧ್ಯವಿಲ್ಲ — ಪ್ರತಿಯೊಂದೂ ಪ್ರತ್ಯೇಕ ದಶಾ-ಗೋಚಾರ ವಿಶ್ಲೇಷಣೆ "
                 "ಬೇಡುತ್ತದೆ. ದಯವಿಟ್ಟು **ಎರಡು-ಮೂರು ಪ್ರಶ್ನೆಗಳನ್ನು** ಆಯ್ಕೆ ಮಾಡಿ ಕಳುಹಿಸಿ; "
                 "ಸಮಗ್ರವಾಗಿ ಉತ್ತರಿಸುತ್ತೇನೆ.")

# A real reading that ends by inviting another question — and uses the very
# words the detector looks for. It must still be charged.
KN_REAL_READING = ("**ಮದುವೆ:** ನಿಮ್ಮ ಜಾತಕದಲ್ಲಿ ಗುರು ಮಹಾದಶೆ 2026ರ ಅಕ್ಟೋಬರ್‌ವರೆಗೆ "
                   "ಮುಂದುವರಿಯುತ್ತದೆ; ಶನಿ ಅಂತರ್ದಶೆಯ ಜೊತೆ ಸಪ್ತಮ ಭಾವದ ಮೇಲೆ ಗೋಚಾರ "
                   "ಬೀಳುವುದರಿಂದ 2026ರ ನವೆಂಬರ್‌ನಿಂದ 2027ರ ಜನವರಿ ನಡುವೆ ವಿವಾಹ ಯೋಗ "
                   "ಬಲವಾಗಿದೆ. ನವಾಂಶ ಕುಂಡಲಿಯೂ ಇದನ್ನೇ ತೋರಿಸುತ್ತದೆ.\n\n"
                   "**ಉದ್ಯೋಗ:** ದಶಮ ಭಾವದ ಅಧಿಪತಿ ಬಲಶಾಲಿಯಾಗಿದ್ದು, 2027ರ ಮಧ್ಯಭಾಗದಲ್ಲಿ "
                   "ಸ್ಥಾನಬದಲಾವಣೆ ಸಾಧ್ಯತೆ ಕಾಣುತ್ತದೆ. ಅಷ್ಟಕವರ್ಗದ ಬಿಂದುಗಳೂ ಈ ಅವಧಿಯನ್ನು "
                   "ಬೆಂಬಲಿಸುತ್ತವೆ.\n\n"
                   "**ಆರೋಗ್ಯ:** 2026ರ ಬೇಸಿಗೆಯಲ್ಲಿ ಜೀರ್ಣಾಂಗದ ಬಗ್ಗೆ ಎಚ್ಚರ ವಹಿಸಿ; "
                   "ಜ್ಯೋತಿಷ್ಯ ಪ್ರವೃತ್ತಿಯನ್ನಷ್ಟೇ ತೋರಿಸುತ್ತದೆ, ವೈದ್ಯರ ಸಲಹೆ ಅಗತ್ಯ.\n\n"
                   "ಉಳಿದ ಪ್ರಶ್ನೆಗಳ ಬಗ್ಗೆ ತಿಳಿಯಬೇಕಾದರೆ ದಯವಿಟ್ಟು ಮತ್ತೆ ಕೇಳಿ.")


def test_B_a_turn_that_delivers_no_reading_is_a_free_clarification(env):
    from app.ai import pipeline
    claude = FixedClaude(KN_NO_READING, lang="kn")
    env.set_models(FakeGemini(plan=PLAN_OK), claude)
    r = pipeline.run_query(UID, _session("kn"), KN_TENQ, prechecked=env.flags)
    assert r.status == "clarify"
    assert r.charged_units == 0 and env.billing.calls == []
    assert r.reply == KN_NO_READING            # the client still sees what was written
    assert r.trace["error"] == "no_reading_delivered"
    assert r.trace["charged_units"] == 0
    assert env.repo.rollups[-1]["refusals"] == 1
    assert "revenue_units" not in env.repo.rollups[-1]
    # a free turn, so it counts against the session's free-turn allowance
    assert env.repo.sessions["s1"][-1]["free_turns"] == ("incr", 1)


def test_B_a_real_reading_that_ends_with_a_question_is_still_charged(env):
    """The hole this must not open: a genuine answer that invites a
    follow-up — in the detector's own words — stays billable."""
    from app.ai import delivery, pipeline
    assert delivery.asks_the_client_to_resend(KN_REAL_READING)   # worst case
    env.set_models(FakeGemini(plan=PLAN_OK), FixedClaude(KN_REAL_READING, lang="kn"))
    r = pipeline.run_query(UID, _session("kn"), KN_TENQ, prechecked=env.flags)
    assert r.status == "ok" and r.charged_units == 1000
    assert env.billing.calls and env.billing.calls[0][1] == 1000
    assert env.repo.rollups[-1]["queries"] == 1


def test_B_a_normal_answer_is_unaffected(env):
    from app.ai import pipeline
    env.set_models(FakeGemini(plan=PLAN_OK), FakeClaude(lang="te"))
    r = pipeline.run_query(UID, _session("te"), "నా వివాహం ఎప్పుడు?",
                           prechecked=env.flags)
    assert r.status == "ok" and r.charged_units == 1000


SHORT_AND_EMPTY = {
    "kn": KN_NO_READING,
    "hi": ("इतने सारे प्रश्न एक ही उत्तर में नहीं देख सकता — हर एक के लिए अलग दशा "
           "और गोचर देखना पड़ता है। कृपया दो-तीन प्रश्न चुनकर भेजिए।"),
    "te": ("ఇన్ని ప్రశ్నలకు ఒకే సమాధానంలో న్యాయం చేయలేను. దయచేసి రెండు-మూడు "
           "ప్రశ్నలు ఎంచుకుని పంపండి."),
    "ta": ("இத்தனை கேள்விகளுக்கு ஒரே பதிலில் நியாயம் செய்ய முடியாது. தயவுசெய்து "
           "இரண்டு-மூன்று கேள்விகளைத் தேர்ந்தெடுத்து அனுப்புங்கள்."),
    "ml": ("ഇത്രയും ചോദ്യങ്ങൾക്ക് ഒരൊറ്റ മറുപടിയിൽ നീതി പുലർത്താനാకില്ല. ദയവായി "
           "രണ്ടോ മൂന്നോ ചോദ്യങ്ങൾ തിരഞ്ഞെടുത്ത് അയയ്ക്കൂ."),
    "en": "I cannot answer all ten properly in one reply. Please pick two or "
          "three questions and send them again.",
}


@pytest.mark.parametrize("lang", sorted(SHORT_AND_EMPTY))
def test_B_no_reading_is_recognised_in_every_language(lang):
    from app.ai import delivery
    assert not delivery.delivers_a_reading(SHORT_AND_EMPTY[lang])


@pytest.mark.parametrize("reply", [
    KN_REAL_READING,
    # short, but it names the window the client paid for
    "మీ వివాహ యోగం 2027 మార్చి నుండి జూలై మధ్య బలంగా ఉంది. ఇంకేమైనా అడగండి?",
    # short and undated, but it is a reading, not a request to resend
    "ఈ జాతకంలో గురువు కేంద్రంలో ఉండటం వల్ల మీ స్వభావం ఉదారమైనది, ఆధ్యాత్మిక మొగ్గు ఎక్కువ.",
    # an English reading that ends on a question
    "Your tenth lord is strong and the 2028 window favours a move abroad. "
    "Shall I look at the marriage chart next?",
])
def test_B_a_reading_is_a_reading(reply):
    from app.ai import delivery
    assert delivery.delivers_a_reading(reply)


def test_B_a_short_voice_answer_is_not_mistaken_for_a_clarification():
    from app.ai import delivery
    spoken = ("ನಿಮ್ಮ ವಿವಾಹ ಯೋಗ ಎರಡು ಸಾವಿರದ ಇಪ್ಪತ್ತೇಳರ ಆರಂಭದಲ್ಲಿ ಬಲವಾಗಿದೆ. "
              "ಗುರು ಗೋಚಾರ ಸಪ್ತಮ ಭಾವವನ್ನು ನೋಡುತ್ತಿದೆ. ಆ ಸಮಯದಲ್ಲಿ ಪ್ರಯತ್ನ ಮಾಡಿ.")
    assert delivery.delivers_a_reading(spoken, mode="voice")


def test_B_an_empty_reply_is_never_billable():
    from app.ai import delivery
    assert not delivery.delivers_a_reading("")
    assert not delivery.delivers_a_reading("   \n ")


# ============================================================== defect C ====
# The three corrupted Hindi answers, exactly as they left the API.

CORRUPTED = [
    ("## प्रश्न \ufffdDiSC\n\nआपने जातक के विवाह का समय पूछा है।",
     "## प्रश्न \n\nआपने जातक के विवाह का समय पूछा है।"),
    ("**प्रश्न** \ufffdDigestibleनमस्कार।\n\nजन्म समय ज्ञात नहीं है।",
     "**प्रश्न** नमस्कार।\n\nजन्म समय ज्ञात नहीं है।"),
    ("**प्रश्न** \ufffdDinosaurMicrosoft\n\nजन्म समय अज्ञात होने से",
     "**प्रश्न** \n\nजन्म समय अज्ञात होने से"),
]


@pytest.mark.parametrize("bad, good", CORRUPTED)
def test_C_the_corruption_from_the_eval_is_removed(bad, good):
    from app.ai import delivery
    assert delivery.scrub(bad, "hi") == good
    assert "\ufffd" not in delivery.scrub(bad, "hi")


def test_C_an_english_reply_keeps_its_english():
    """U+FFFD goes; the sentence around it is the answer, not junk."""
    from app.ai import delivery
    out = delivery.scrub("Your tenth \ufffdlord is strong in 2028.", "en")
    assert out == "Your tenth lord is strong in 2028."


def test_C_clean_indic_text_is_returned_untouched():
    from app.ai import delivery
    for lang, text in (("hi", "मीन लग्न में गुरु 2027 तक शुभ फल देगा।"),
                       ("ta", "உங்கள் ஜாதகத்தில் குரு 2027 வரை சுபம்."),
                       ("en", "Jupiter is strong until 2027.")):
        assert delivery.scrub(text, lang) == text


@pytest.mark.parametrize("bad, good", CORRUPTED)
def test_C_the_stream_is_scrubbed_at_every_split_point(bad, good):
    """Deltas arrive in arbitrary pieces; a corrupted run may straddle any
    two of them, and the client must still receive exactly `good`."""
    from app.ai import delivery
    for cut in range(len(bad) + 1):
        out = []
        s = delivery.Scrubber("hi", out.append)
        s.feed(bad[:cut])
        s.feed(bad[cut:])
        s.flush()
        assert "".join(out) == good, "split at %d" % cut
    # and one character at a time
    out = []
    s = delivery.Scrubber("hi", out.append)
    for ch in bad:
        s.feed(ch)
    s.flush()
    assert "".join(out) == good


def test_C_the_scrubber_passes_clean_text_straight_through():
    from app.ai import delivery
    text = "मीन लग्न में गुरु 2027 तक शुभ फल देगा। " * 20
    out = []
    s = delivery.Scrubber("hi", out.append)
    for i in range(0, len(text), 7):
        s.feed(text[i:i + 7])
    s.flush()
    assert "".join(out) == text


def test_C_a_corrupted_reply_is_cleaned_before_it_is_delivered(env):
    from app.ai import pipeline
    bad, good = CORRUPTED[0][0] + " " + "विवाह योग 2027 में बनता है। " * 12, None
    good = bad.replace("\ufffd" + "DiSC", "")
    env.set_models(FakeGemini(plan=PLAN_OK), FixedClaude(bad, lang="hi"))
    r = pipeline.run_query(UID, _session("hi"), "मेरा विवाह कब होगा?",
                           prechecked=env.flags)
    assert r.status == "ok"
    assert "\ufffd" not in r.reply and "DiSC" not in r.reply
    assert r.reply == good.strip()


def test_C_the_stream_never_carries_a_corrupted_character(env):
    """The SSE client sees the cleaned text, not a delta with the wreckage."""
    from app.ai import pipeline
    bad = CORRUPTED[2][0] + " " + "गुरु की दशा 2028 तक चलेगी। " * 12
    deltas = []
    env.set_models(FakeGemini(plan=PLAN_OK), FixedClaude(bad, lang="hi", step=3))
    r = pipeline.run_query(UID, _session("hi"), "मेरा करियर कैसा रहेगा?",
                           prechecked=env.flags, on_delta=deltas.append)
    streamed = "".join(deltas)
    assert "\ufffd" not in streamed and "Dinosaur" not in streamed
    assert streamed == r.reply or streamed.strip() == r.reply.strip()


# ---- the transport itself: multi-byte text split at every byte boundary ----

@pytest.fixture
def client(env, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app import routes_ai, store
    from app.ai import repo

    sessions = {"s-hi": {"id": "s-hi", "uid": UID, "profile_id": "p1", "lang": "hi",
                         "mode": "text", "summary": "", "free_turns": 0}}
    monkeypatch.setattr(repo, "get_session", lambda sid: sessions.get(sid))
    monkeypatch.setattr(store, "get_user", lambda uid: {"uid": uid, "lang": "hi",
                                                        "balance_units": env.repo.balance})
    monkeypatch.setattr(store, "get_flags", lambda: dict(FLAGS))
    app = FastAPI()
    app.include_router(routes_ai.router)
    c = TestClient(app)
    c.headers.update({"Authorization": "Bearer " + store.issue_token(UID)})
    return c


# Devanagari (3 bytes/char), Telugu, a combining sequence, an emoji (4 bytes,
# a surrogate pair in UTF-16) and ASCII digits — every width UTF-8 has.
MIXED = ("🙏 मीन लग्न — गुरु की महादशा 2027 तक चलेगी। "
         "మీ జాతకంలో గురువు శుభుడు. Namaste 🙏")


def _sse_text(raw_text):
    """The reply the SSE client reassembles from the `delta` frames."""
    out = []
    for block in raw_text.split("\n\n"):
        if block.startswith("event: delta"):
            out.append(json.loads(block.split("data: ", 1)[1])["text"])
    return "".join(out)


def test_C_sse_multibyte_reply_survives_a_split_at_every_byte_boundary(client, env):
    """The network may cut the response between any two bytes, including the
    middle of a three-byte Devanagari character. An incremental decoder must
    put the reply back together exactly, with no U+FFFD anywhere."""
    reply = MIXED * 6
    env.set_models(FakeGemini(plan=PLAN_OK), FixedClaude(reply, lang="hi", step=5))
    r = client.post("/api/sessions/s-hi/ask/stream",
                    json={"text": "मेरी कुंडली में गुरु कहाँ है?"})
    assert r.status_code == 200
    raw = r.content
    assert isinstance(raw, bytes)
    assert b"\xef\xbf\xbd" not in raw            # no U+FFFD on the wire

    for cut in range(len(raw) + 1):
        dec = codecs.getincrementaldecoder("utf-8")()
        text = dec.decode(raw[:cut]) + dec.decode(raw[cut:], True)
        assert _sse_text(text) == reply, "byte split at %d" % cut


def test_C_opus_delta_accumulation_survives_every_delta_boundary(env):
    """Same guarantee one layer down: however the provider chunks the text
    deltas, what the pipeline accumulates is the string the model wrote."""
    from app.ai import llm

    class Splitter(FixedClaude):
        def __init__(self, text, at):
            super().__init__(text, lang="hi")
            self.at = at

        def _stream(self, kw):
            pieces = [self.text[:self.at], self.text[self.at:]]

            class S(_Stream):
                @property
                def text_stream(inner):
                    return iter(pieces)

            return S(self.text, _Final(self.text, 100,
                                       realistic_tokens(self.text), "end_turn"))

    for at in range(len(MIXED) + 1):
        env.set_models(FakeGemini(plan=PLAN_OK), Splitter(MIXED, at))
        got = []
        text, stop, _ = llm.opus("reason", [{"type": "text", "text": "sys"}],
                                 [{"role": "user", "content": "q"}],
                                 max_tokens=500, on_delta=got.append)
        assert text == MIXED.strip(), "delta split at %d" % at
        assert "".join(got) == MIXED, "delta split at %d" % at


# ---------------- English left in an Indic reply ----------------

def test_a_divisional_chart_is_named_in_the_reply_language():
    from app.ai import delivery
    out = delivery.localize_jargon("కెరీర్ కోసం D-10 చూడండి, D9 కూడా.", "te")
    assert "D-10" not in out and "D9" not in out
    assert "10 వర్గ చక్రం" in out and "9 వర్గ చక్రం" in out


def test_kp_becomes_the_reviewed_local_term():
    from app.ai import delivery
    from app.features import common
    out = delivery.localize_jargon("KP పద్ధతి ప్రకారం.", "te")
    assert "KP" not in out and common.t("te", "chart_kinds.kp") in out


def test_an_english_reply_is_left_alone():
    from app.ai import delivery
    text = "Check D-10 and the KP sub lord."
    assert delivery.localize_jargon(text, "en") == text
    assert delivery.latin_leaks(text, "en") == []


def test_the_leak_check_reports_what_is_left():
    from app.ai import delivery
    leaks = delivery.latin_leaks("ఈ జాతకంలో commitment ఉంది, SAV బలం to.", "te")
    assert "commitment" in leaks and "SAV" in leaks
    assert "to" in leaks


def test_a_clean_indic_reply_reports_nothing():
    from app.ai import delivery
    assert delivery.latin_leaks("ఈ జాతకంలో 2017లో ఉద్యోగం మొదలైంది.", "te") == []


def test_every_language_has_the_terms_the_substitution_needs():
    from app.features import common
    for lg in ("hi", "te", "ta", "kn", "ml", "en"):
        assert common.t(lg, "chart_kinds.varga_one")
        assert common.t(lg, "chart_kinds.kp")
