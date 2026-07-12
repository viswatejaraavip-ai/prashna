"""Claude-powered Vedic astrology agent with a manual tool-use loop.

The agent calls the Jyotish engine directly (in-process) via tools whose
schemas mirror the MCP server, so external agents and this web agent see
the same capabilities.
"""

import json
import os
import sys
from typing import Dict, List, Optional, Tuple

import anthropic

from . import config

# Make the engine importable both from the repo layout and the Docker image.
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_ENGINE = os.environ.get("ENGINE_PATH", os.path.join(_ROOT, "engine"))
if _ENGINE not in sys.path:
    sys.path.insert(0, _ENGINE)

from jyotish import api as jyotish_api  # noqa: E402

_client = None


def client():
    """Anthropic client for the configured provider.

    Bedrock: AnthropicBedrockMantle resolves AWS credentials the standard way
    (env vars, shared profile, or the task/instance IAM role on AWS) — no
    Anthropic API key involved. First-party: uses ANTHROPIC_API_KEY.
    """
    global _client
    if _client is None:
        if config.INFERENCE_PROVIDER == "bedrock":
            _client = anthropic.AnthropicBedrockMantle(aws_region=config.AWS_REGION)
        else:
            _client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY or None)
    return _client


SYSTEM_PROMPT = """You are Udhyath, an expert Vedic astrologer chatting with a paying client.

You have precise Swiss Ephemeris calculation tools. NEVER estimate planetary
positions, dashas, or panchanga from memory — always call a tool. All results
are sidereal (Lahiri ayanamsa by default).

Language: reply in the language the client uses — Telugu, Hindi, Tamil,
Kannada, Malayalam, Bengali, Marathi, Gujarati, Punjabi, Odia, English or any
other. Use the language's familiar astrological vocabulary (Telugu: జాతకం,
లగ్నం, దశ, గోచారం, నక్షత్రం; Hindi: कुंडली, लग्न, दशा, गोचर, नक्षत्र; and so
on). Match their register — conversational, spoken-sounding sentences for
voice-style messages.

How to work:
- To analyze anything you need the client's birth details: date, time (as exact
  as possible), and place. Ask for the city and resolve it yourself to latitude,
  longitude and IANA timezone (you know coordinates of world cities well).

SYNTHESIS PROTOCOL — mandatory before ANY prediction or event judgment:
- First call full_analysis (once per client; it returns everything). Do not
  answer predictive questions from a single chart or a single system.
- Cross-check each conclusion across the bundle before stating it:
  * houses: compare whole-sign placement with bhava chalit — a planet that
    shifts houses in chalit changes the reading;
  * strength: Ashtakavarga (SAV >= 28 strong, < 25 weak; the transiting
    planet's own BAV bindus in the sign it transits) plus D-9 confirmation;
  * precision: KP cuspal sub lords and the planet/house significator tables
    for yes/no questions;
  * delivery: Nadi stellar chains — a planet delivers its star lord's houses,
    not its own — plus BNN links and the Jupiter jeeva timeline;
  * timing: NEVER time an event from vimshottari alone. Compare at least two
    dasha systems (vimshottari maha/antar/pratyantar plus chara, yogini or
    kalachakra) and confirm with year_transits or the Jupiter timeline. Offer
    a date window only where the systems overlap.
- Weight agreement: state confidently only what two or more systems support.
  Where systems disagree, say so honestly and give the more conservative
  reading. Name the converging factors briefly in your answer
  (e.g. "Jupiter–Saturn antar, Chara Pisces dasha and SAV 30 all point to...").
- Pull a specific varga when the question needs it (career -> D-10,
  marriage -> D-9, children -> D-7, parents -> D-12, etc.).
- Use your world knowledge — professions, industries, education systems,
  life events, places — to translate chart factors into concrete,
  relevant guidance for the client's situation.
- Explain in warm, clear language a layperson understands. Name the chart
  factors behind each statement (e.g. "Saturn in the 10th in D-1 and D-10...").
- Be honest about uncertainty; astrology describes tendencies, not certainties.
  Never make medical, legal, or financial guarantees. For serious health,
  legal or mental-health matters, advise consulting a qualified professional.
- Keep answers focused; this is a paid, metered session. Do not pad. For
  voice-style conversations, prefer shorter, spoken-sounding sentences.
"""


def _birth_props() -> Dict:
    return {
        "year": {"type": "integer"}, "month": {"type": "integer"},
        "day": {"type": "integer"}, "hour": {"type": "integer", "description": "0-23 local"},
        "minute": {"type": "integer"},
        "latitude": {"type": "number"}, "longitude": {"type": "number"},
        "tz_name": {"type": "string", "description": "IANA timezone, e.g. Asia/Kolkata"},
        "utc_offset_hours": {"type": "number", "description": "Alternative to tz_name"},
        "ayanamsa": {"type": "string", "description": "lahiri (default), raman, kp"},
    }


_BIRTH_REQUIRED = ["year", "month", "day", "hour", "minute", "latitude", "longitude"]


def _birth_tool(name: str, description: str, extra_props: Optional[Dict] = None,
                extra_required: Optional[List[str]] = None) -> Dict:
    props = _birth_props()
    if extra_props:
        props.update(extra_props)
    return {
        "name": name,
        "description": description,
        "input_schema": {
            "type": "object",
            "properties": props,
            "required": _BIRTH_REQUIRED + (extra_required or []),
        },
    }


TOOLS = [
    _birth_tool("full_analysis",
                "THE synthesis bundle — call this FIRST for any reading or "
                "prediction. One call returns: rasi (D-1), navamsa (D-9), "
                "bhava chalit, KP sub lords + significator tables, "
                "Ashtakavarga BAV/SAV, full Nadi analysis, current transits, "
                "and ALL FOUR dasha systems (vimshottari, yogini, chara, "
                "kalachakra) with full maha timelines and the exact "
                "maha/antar running at at_iso (default now). Use it to "
                "cross-check houses, strength, KP precision, Nadi delivery "
                "and multi-dasha timing before predicting.",
                {"at_iso": {"type": "string",
                            "description": "ISO-8601 moment for 'running now' "
                                           "dashas/transits (default: now)"}}),
    _birth_tool("birth_chart",
                "Rasi (D-1) chart: sidereal positions, signs, nakshatras+padas, "
                "retrogrades, whole-sign houses, lagna, birth panchanga."),
    _birth_tool("varga_chart",
                "One divisional chart: D1,D2,D3,D4,D7,D9,D10,D12,D16,D20,D24,D27,D30,D40,D45,D60.",
                {"varga": {"type": "string", "description": "e.g. D9"}}, ["varga"]),
    _birth_tool("all_varga_charts",
                "All 16 divisional charts compactly (planet->sign per varga)."),
    _birth_tool("bhava_chalit_chart",
                "Sripati bhava chalit house placements (may differ from whole-sign)."),
    _birth_tool("dasha_periods",
                "Dasha timeline. system: vimshottari (default), yogini (36y cycle), "
                "chara (Jaimini sign dasha, K.N. Rao), kalachakra (BPHS). "
                "levels applies to vimshottari only: 1 maha, 2 +antar, 3 +pratyantar.",
                {"levels": {"type": "integer"},
                 "system": {"type": "string",
                            "description": "vimshottari | yogini | chara | kalachakra"}}),
    _birth_tool("current_dasha",
                "Maha/antar/pratyantar lords running now or at at_iso (ISO-8601).",
                {"at_iso": {"type": "string"}}),
    _birth_tool("birth_panchanga",
                "Tithi, paksha, vara, nakshatra, yoga, karana at birth."),
    _birth_tool("nadi_analysis",
                "Nadi analysis: Meena stellar delivery chains (planet delivers "
                "its star lord's houses; deputies), BNN karakas + sign links, "
                "nadi-amsa (D-150), dignity, and an 80-year Jupiter jeeva "
                "timeline with natal contacts. Use for Nadi-style readings and "
                "life-chapter timing via Jupiter's movement."),
    _birth_tool("kp_chart",
                "KP (Krishnamurti Paddhati): sign/star/sub/sub-sub lords for all "
                "planets and the 12 Placidus cusps. Uses KP ayanamsa. Use for "
                "precise KP-style predictions and cuspal sub lord analysis."),
    _birth_tool("ashtakavarga",
                "Ashtakavarga: Bhinnashtakavarga bindus per sign for the 7 planets "
                "and Sarvashtakavarga totals. Use for transit strength judgments "
                "(signs with SAV >= 28 are strong, < 25 weak)."),
    _birth_tool("dosha_analysis",
                "Doshas: Manglik (from Lagna/Moon/Venus with severity and "
                "cancellations), Kaal Sarpa (with type), and life-long "
                "Sadhe Sati / Dhaiya windows with what is active now."),
    _birth_tool("yoga_analysis",
                "Classical yogas present in the chart: Panch Mahapurusha, "
                "Gajakesari, Budhaditya, lunar/solar yogas, Vipareeta Raja, "
                "Parivartana, Dhana, Raja, Neecha Bhanga."),
    {
        "name": "match_making",
        "description": "Kundali matching between two people: Ashtakoot "
                       "36-guna, Dashakoot 10-porutham and Manglik "
                       "cross-check. Provide both birth details.",
        "input_schema": {
            "type": "object",
            "properties": {
                "boy": {"type": "object", "properties": _birth_props(),
                        "required": _BIRTH_REQUIRED},
                "girl": {"type": "object", "properties": _birth_props(),
                         "required": _BIRTH_REQUIRED},
            },
            "required": ["boy", "girl"],
        },
    },
    {
        "name": "muhurta_of_day",
        "description": "Day timings for a date+place: sunrise/sunset, "
                       "Rahu Kalam, Yamaganda, Gulika, Abhijit and Brahma "
                       "muhurta. Use for 'good time today/this date'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "YYYY-MM-DD (default today)"},
                "latitude": {"type": "number"}, "longitude": {"type": "number"},
                "tz_name": {"type": "string"},
            },
        },
    },
    {
        "name": "transits",
        "description": "Current sidereal planetary positions (gochar), or at at_iso.",
        "input_schema": {
            "type": "object",
            "properties": {
                "at_iso": {"type": "string"},
                "ayanamsa": {"type": "string"},
            },
        },
    },
    {
        "name": "year_transits",
        "description": "Transit timeline for a calendar year: per-planet sign "
                       "occupancy periods, exact ingress dates, retro/direct "
                       "stations. Use for timing questions like 'when does "
                       "Jupiter enter Cancer' or 'Saturn retrograde periods'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "year": {"type": "integer"},
                "ayanamsa": {"type": "string"},
                "include_moon": {"type": "boolean"},
            },
            "required": ["year"],
        },
    },
]


def _split_birth(args: Dict) -> Tuple[Dict, Dict]:
    birth_keys = set(_birth_props().keys())
    birth = {k: v for k, v in args.items() if k in birth_keys}
    rest = {k: v for k, v in args.items() if k not in birth_keys}
    return birth, rest


def execute_tool(name: str, args: Dict) -> str:
    try:
        birth, rest = _split_birth(args)
        if name == "full_analysis":
            result = jyotish_api.full_analysis(birth, rest.get("at_iso"))
        elif name == "birth_chart":
            result = jyotish_api.birth_chart(birth)
        elif name == "varga_chart":
            result = jyotish_api.varga_chart(birth, rest["varga"])
        elif name == "all_varga_charts":
            result = jyotish_api.all_vargas(birth)
        elif name == "bhava_chalit_chart":
            result = jyotish_api.bhava_chart(birth)
        elif name == "dasha_periods":
            result = jyotish_api.dasha_periods(birth, rest.get("levels", 2),
                                               rest.get("system", "vimshottari"))
        elif name == "current_dasha":
            result = jyotish_api.current_dasha(birth, rest.get("at_iso"))
        elif name == "birth_panchanga":
            result = jyotish_api.panchanga_for(birth)
        elif name == "kp_chart":
            result = jyotish_api.kp_chart(birth)
        elif name == "nadi_analysis":
            result = jyotish_api.nadi_analysis(birth)
        elif name == "dosha_analysis":
            result = jyotish_api.dosha_analysis(birth)
        elif name == "yoga_analysis":
            result = jyotish_api.yoga_analysis(birth)
        elif name == "match_making":
            result = jyotish_api.match_making(args["boy"], args["girl"])
        elif name == "muhurta_of_day":
            result = jyotish_api.muhurta_of_day(
                args.get("date"), args.get("latitude", 28.6139),
                args.get("longitude", 77.2090),
                args.get("tz_name", "Asia/Kolkata"))
        elif name == "ashtakavarga":
            result = jyotish_api.ashtakavarga_chart(birth)
        elif name == "transits":
            result = jyotish_api.transits(args.get("at_iso"), args.get("ayanamsa", "lahiri"))
        elif name == "year_transits":
            result = jyotish_api.transit_year(args["year"],
                                              args.get("ayanamsa", "lahiri"),
                                              args.get("include_moon", False))
        else:
            return json.dumps({"error": "unknown tool %s" % name})
        return json.dumps(result, default=str)
    except Exception as exc:  # tool errors go back to the model, not the user
        return json.dumps({"error": str(exc)})


def run_agent(history: List[Dict]) -> Tuple[str, int, int]:
    """Run the tool-use loop over the conversation.

    history: [{"role": "user"|"assistant", "content": str}, ...] ending with
    the newest user message. Returns (reply_text, input_tokens, output_tokens)
    with token usage summed across every API call in the loop.
    """
    messages: List[Dict] = list(history)
    total_in = 0
    total_out = 0
    response = None

    for _ in range(config.AGENT_MAX_TOOL_ITERATIONS):
        response = client().messages.create(
            model=config.AGENT_MODEL,
            max_tokens=config.AGENT_MAX_TOKENS,
            system=[{
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }],
            thinking={"type": "adaptive"},
            tools=TOOLS,
            messages=messages,
        )
        total_in += response.usage.input_tokens
        total_out += response.usage.output_tokens

        if response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    result = execute_tool(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })
            messages.append({"role": "user", "content": tool_results})
            continue
        if response.stop_reason == "pause_turn":
            messages.append({"role": "assistant", "content": response.content})
            continue
        break

    if response is None:
        return "The astrologer is unavailable right now. Please try again.", 0, 0
    if response.stop_reason == "refusal":
        return ("I can't help with that particular request. "
                "Let's return to your chart — what would you like to explore?",
                total_in, total_out)

    reply = "".join(b.text for b in response.content if b.type == "text").strip()
    if not reply:
        reply = "(The astrologer had nothing further to add — try rephrasing.)"
    return reply, total_in, total_out
