"""Prashna AI pipeline: Gemini Flash plans/executes, Claude
Opus 4.5 reasons. See docs/launch/CONTRACT.md ("AI pipeline", `traces`).

    planner.py   Flash: guard + intent + tool plan (JSON)            stage "plan"
    executor.py  engine tools, then Flash condenses to a facts brief stages "tools", "brief"
    reasoner.py  Opus 4.5: the answer the user reads/hears            stage "reason"
    memory.py    Flash: rolling session summary + per-profile facts  stage "memory"
    speech.py    Cloud STT / TTS for the cloud voice path            stages "stt", "tts"
    budget.py    per-query cost ceiling (enforced before Opus)
    costs.py     THE price table (single source of truth)
    pipeline.py  orchestration, billing, traces, rollups
"""
