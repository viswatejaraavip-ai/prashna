"""Cloud voice path: Google Cloud Speech-to-Text V2 and Text-to-Speech.

On-device Android STT/TTS is the default (free); this path serves devices
without the language pack. Both costs count toward the per-query ceiling.

STT: V2 `recognize` (synchronous, <= 60 s) with a Chirp model. Chirp models
are regional — STT_LOCATION must be a region that serves STT_MODEL for the
Indic locales (verify with scripts/ai_cost_probe.py --voice after deploy).
TTS: Standard voices by default (every one of hi/te/ta/kn/ml has them);
WaveNet via TTS_VOICE_<LANG>. Premium tiers (Neural2, Chirp HD, Studio) are
refused so a config change can't blow the budget.
"""

import logging
import os
import struct
import time
from typing import Optional, Tuple

from . import costs, llm

log = logging.getLogger("udhyath.ai.speech")

STT_MODEL = os.environ.get("STT_MODEL", "chirp_2")
STT_LOCATION = os.environ.get("STT_LOCATION", "asia-southeast1")
VOICE_MAX_AUDIO_SECONDS = float(os.environ.get("VOICE_MAX_AUDIO_SECONDS", "45"))
LOCALES = {"hi": "hi-IN", "te": "te-IN", "ta": "ta-IN", "kn": "kn-IN", "ml": "ml-IN", "en": "en-IN"}
DEFAULT_VOICES = {"hi": "hi-IN-Standard-A", "te": "te-IN-Standard-A",
                  "ta": "ta-IN-Standard-A", "kn": "kn-IN-Standard-A",
                  "ml": "ml-IN-Standard-A", "en": "en-IN-Standard-A"}
_TTS_MAX_BYTES = 4500   # API limit is 5000 bytes of input per request

_stt = None
_tts = None


def set_clients(stt=None, tts=None) -> None:
    global _stt, _tts
    if stt is not None:
        _stt = stt
    if tts is not None:
        _tts = tts


def _stt_client():
    global _stt
    if _stt is None:
        from google.cloud.speech_v2 import SpeechClient
        opts = None
        if STT_LOCATION != "global":
            from google.api_core.client_options import ClientOptions
            opts = ClientOptions(api_endpoint="%s-speech.googleapis.com" % STT_LOCATION)
        _stt = SpeechClient(client_options=opts)
    return _stt


def _tts_client():
    global _tts
    if _tts is None:
        from google.cloud import texttospeech
        _tts = texttospeech.TextToSpeechClient()
    return _tts


class AudioError(ValueError):
    pass


def audio_format(data: bytes) -> str:
    if data[:4] == b"OggS":
        return "ogg_opus"
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "wav"
    return "linear16"


def audio_seconds(data: bytes) -> float:
    """Duration without decoding: PCM from byte count, Ogg from the last
    page's granule position (Opus granules are always 48 kHz)."""
    fmt = audio_format(data)
    if fmt == "linear16":
        return len(data) / 32000.0
    if fmt == "wav":
        try:
            rate, = struct.unpack("<I", data[24:28])
            ch, = struct.unpack("<H", data[22:24])
            bits, = struct.unpack("<H", data[34:36])
            return max(0, len(data) - 44) / float(rate * ch * bits // 8)
        except Exception:
            return len(data) / 32000.0
    pos = data.rfind(b"OggS")
    if pos < 0 or pos + 14 > len(data):
        raise AudioError("unreadable ogg")
    granule, = struct.unpack("<q", data[pos + 6:pos + 14])
    return max(0.0, (granule - 312) / 48000.0)   # 312 = default Opus pre-skip


def transcribe(data: bytes, lang: str) -> Tuple[str, "llm.Stage"]:
    secs = audio_seconds(data)
    if secs > VOICE_MAX_AUDIO_SECONDS + 0.5:
        raise AudioError("audio longer than %d s" % VOICE_MAX_AUDIO_SECONDS)
    if secs < 0.3:
        raise AudioError("audio too short")
    from google.cloud.speech_v2.types import cloud_speech
    project = llm.GCP_PROJECT
    fmt = audio_format(data)
    if fmt == "linear16":
        dec = {"explicit_decoding_config": cloud_speech.ExplicitDecodingConfig(
            encoding=cloud_speech.ExplicitDecodingConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=16000, audio_channel_count=1)}
    else:
        dec = {"auto_decoding_config": cloud_speech.AutoDetectDecodingConfig()}
    config = cloud_speech.RecognitionConfig(
        language_codes=[LOCALES.get(lang, "hi-IN")], model=STT_MODEL,
        features=cloud_speech.RecognitionFeatures(enable_automatic_punctuation=True),
        **dec)
    req = cloud_speech.RecognizeRequest(
        recognizer="projects/%s/locations/%s/recognizers/_" % (project, STT_LOCATION),
        config=config, content=data)
    t0 = time.time()
    resp = _stt_client().recognize(request=req, timeout=30)
    text = " ".join(r.alternatives[0].transcript.strip()
                    for r in resp.results if r.alternatives).strip()
    billed = secs
    try:
        d = resp.metadata.total_billed_duration
        billed = float(getattr(d, "total_seconds", lambda: d.seconds + d.nanos / 1e9)())
    except Exception:
        pass
    billed = max(billed, secs)
    stage = llm.Stage(name="stt", model=STT_MODEL, units=round(billed, 2),
                      cost=costs.stt_cost(STT_MODEL, billed),
                      latency_ms=int((time.time() - t0) * 1000))
    return text, stage


def voice_for(lang: str) -> Tuple[str, Optional[str]]:
    name = os.environ.get("TTS_VOICE_%s" % lang.upper(), DEFAULT_VOICES.get(lang, ""))
    return name, costs.tts_tier(name)


def tts_tier_for(lang: str) -> Optional[str]:
    return voice_for(lang)[1]


def _chunks(text: str):
    """Split on sentence ends so each request stays under the byte limit."""
    buf = ""
    for piece in _split_sentences(text):
        if len((buf + piece).encode("utf-8")) > _TTS_MAX_BYTES and buf:
            yield buf
            buf = ""
        while len(piece.encode("utf-8")) > _TTS_MAX_BYTES:
            cut = len(piece) // 2
            yield piece[:cut]
            piece = piece[cut:]
        buf += piece
    if buf.strip():
        yield buf


def _split_sentences(text: str):
    out, cur = [], ""
    for ch in text:
        cur += ch
        if ch in ".?!।॥\n":
            out.append(cur)
            cur = ""
    if cur:
        out.append(cur)
    return out


def synthesize(text: str, lang: str) -> Tuple[bytes, "llm.Stage"]:
    """MP3 (frames concatenate cleanly across chunks)."""
    name, tier = voice_for(lang)
    if tier is None:
        raise ValueError("TTS voice %r is not a Standard/WaveNet voice" % name)
    from google.cloud import texttospeech as tts
    t0 = time.time()
    audio = b""
    chars = 0
    for chunk in _chunks(text):
        chars += len(chunk)
        r = _tts_client().synthesize_speech(
            input=tts.SynthesisInput(text=chunk),
            voice=tts.VoiceSelectionParams(language_code=LOCALES.get(lang, "hi-IN"),
                                           name=name),
            audio_config=tts.AudioConfig(audio_encoding=tts.AudioEncoding.MP3),
            timeout=30)
        audio += r.audio_content
    stage = llm.Stage(name="tts", model=name, units=chars,
                      cost=costs.tts_cost(tier, chars),
                      latency_ms=int((time.time() - t0) * 1000))
    return audio, stage
