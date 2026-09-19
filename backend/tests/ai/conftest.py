"""pytest wiring for the AI pipeline tests; fakes live in ai_fakes.py (a
unique module name, so running all backend test dirs together is safe)."""

import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (os.path.abspath(os.path.join(HERE, "..", "..")), HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import pytest  # noqa: E402

from ai_fakes import FLAGS, FakeBilling, FakeClaude, FakeGemini, FakeRepo  # noqa: E402


@pytest.fixture
def env(monkeypatch):
    """Wire fakes into the pipeline; returns a namespace to tweak per test."""
    from app.ai import llm, pipeline, repo, speech
    from app.ai import costs

    fr = FakeRepo()
    fr.install(monkeypatch, repo)
    fb = FakeBilling(fr)
    monkeypatch.setattr(pipeline, "_billing", lambda: fb)
    llm.reset_capabilities()

    def set_models(gemini=None, claude=None):
        monkeypatch.setattr(llm, "_gemini", gemini or FakeGemini())
        monkeypatch.setattr(llm, "_claude", claude or FakeClaude())

    def fake_transcribe(data, lang, seconds=45.0, text=None):
        stage = llm.Stage(name="stt", model=speech.STT_MODEL, units=seconds,
                          cost=costs.stt_cost(speech.STT_MODEL, seconds))
        return (text or "ചോദ്യം"), stage

    def fake_synth(text, lang):
        name, tier = speech.voice_for(lang)
        return b"ID3fake", llm.Stage(name="tts", model=name, units=len(text),
                                     cost=costs.tts_cost(tier, len(text)))

    monkeypatch.setattr(speech, "synthesize", fake_synth)
    ns = types.SimpleNamespace(repo=fr, billing=fb, set_models=set_models,
                               fake_transcribe=fake_transcribe, flags=dict(FLAGS),
                               monkeypatch=monkeypatch, speech=speech)
    set_models()
    return ns
