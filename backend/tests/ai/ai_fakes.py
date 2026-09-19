"""Fakes for the AI pipeline tests (imported by conftest.py and tests): Gemini + Claude clients that return
realistic token usage, speech stubs priced through costs.py, in-memory repo
and billing. No network, no Firestore."""

import json
import math
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.abspath(os.path.join(HERE, "..", ".."))
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)
os.environ.setdefault("JWT_SECRET", "test-secret-for-ai-pipeline-tests-0123456789")

_DRAV = ((0x0C00, 0x0C7F), (0x0B80, 0x0BFF), (0x0C80, 0x0CFF), (0x0D00, 0x0D7F))


def realistic_tokens(text: str, drav=1.4, deva=2.0, ascii_=3.6, other=2.0) -> int:
    """What a real tokenizer roughly does (less pessimistic than
    costs.estimate_tokens)."""
    n = {"d": 0, "v": 0, "a": 0, "o": 0}
    for ch in text or "":
        cp = ord(ch)
        if cp < 128:
            n["a"] += 1
        elif 0x0900 <= cp <= 0x097F:
            n["v"] += 1
        elif any(lo <= cp <= hi for lo, hi in _DRAV):
            n["d"] += 1
        else:
            n["o"] += 1
    return int(math.ceil(n["d"] / drav + n["v"] / deva + n["a"] / ascii_ + n["o"] / other))


# ---------------- Gemini ----------------

class _Usage:
    def __init__(self, prompt, out):
        self.prompt_token_count = prompt
        self.candidates_token_count = out
        self.thoughts_token_count = 0
        self.cached_content_token_count = 0


class _Resp:
    def __init__(self, text, prompt, out):
        self.text = text
        self.usage_metadata = _Usage(prompt, out)


class FakeGemini:
    """Routes on the system prompt. `use_full_output=True` makes every call
    emit its whole max_output_tokens (worst case)."""

    def __init__(self, plan=None, use_full_output=False, json_chars_per_token=2.6):
        self.plan = plan or {"status": "ok", "intent": "career",
                             "tools": [{"name": "full_analysis"},
                                       {"name": "varga_chart", "varga": "D10"}],
                             "focus": "Career prospects in the next two years.",
                             "reply": ""}
        self.full = use_full_output
        self.jcpt = json_chars_per_token
        self.calls = []
        self.models = self

    def generate_content(self, model, contents, config):
        system = config.get("system_instruction", "")
        max_out = config["max_output_tokens"]
        # engine JSON tokenizes densely (digits, punctuation)
        prompt = realistic_tokens(system) + int(len(contents) / self.jcpt) \
            if "RAW ENGINE OUTPUT" in contents else realistic_tokens(system + contents)
        if "PLANNER PROTOCOL" in system:
            name, text, out = "plan", json.dumps(self.plan), 140
        elif "FACTS BRIEF PROTOCOL" in system:
            out = max_out if self.full else int(max_out * 0.8)
            name, text = "brief", ("- Lagna Virgo; 10th lord Mercury in 9th. " * 200)[:out * 4]
        elif "maintain memory" in system:
            name, out = "memory", (max_out if self.full else 260)
            text = json.dumps({"summary": "Client asked about career; told 2027-28 "
                                          "is favourable (Jupiter-Saturn antar).",
                               "facts": ["Works as a software engineer in Kochi"]})
        else:
            name, text, out = "other", "{}", 50
        self.calls.append({"name": name, "model": model, "prompt": prompt, "out": out,
                           "max_out": max_out})
        return _Resp(text, prompt, min(out, max_out))


# ---------------- Claude ----------------

class _Block:
    type = "text"

    def __init__(self, text):
        self.text = text


class _Final:
    def __init__(self, text, in_tok, out_tok, stop):
        self.content = [_Block(text)]
        self.usage = types.SimpleNamespace(input_tokens=in_tok, output_tokens=out_tok,
                                           cache_read_input_tokens=0,
                                           cache_creation_input_tokens=0)
        self.stop_reason = stop


class _Stream:
    def __init__(self, text, final):
        self._text, self._final = text, final

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    @property
    def text_stream(self):
        step = 40
        for i in range(0, len(self._text), step):
            yield self._text[i:i + step]

    def get_final_message(self):
        return self._final


class FakeClaude:
    """`out_fraction=1.0` = Opus spends every max_token (worst case).
    `count_ok=False` = count-tokens unavailable (estimates used).
    `report_in` = 'realistic' | 'estimate' (adversarial: input as large as
    our pessimistic estimate)."""

    def __init__(self, lang="te", out_fraction=0.6, count_ok=True, report_in="realistic",
                 reject_effort=False):
        self.lang, self.frac, self.count_ok = lang, out_fraction, count_ok
        self.report_in, self.reject_effort = report_in, reject_effort
        self.calls = []
        self.messages = self

    def with_options(self, **kw):
        return self

    def _in(self, system, messages):
        text = "".join(b["text"] for b in system) + "".join(m["content"] for m in messages)
        if self.report_in == "estimate":
            from app.ai import costs
            return costs.estimate_tokens(text) + 10
        return realistic_tokens(text)

    def count_tokens(self, model, system, messages):
        if not self.count_ok:
            raise RuntimeError("count-tokens not enabled in this region")
        return types.SimpleNamespace(input_tokens=realistic_tokens(
            "".join(b["text"] for b in system) + "".join(m["content"] for m in messages)))

    def stream(self, **kw):
        if self.reject_effort and "output_config" in kw:
            err = RuntimeError("400 output_config not supported")
            err.status_code = 400
            raise err
        self.calls.append(kw)
        max_tokens = kw["max_tokens"]
        out = max(1, int(max_tokens * self.frac))
        stop = "max_tokens" if self.frac >= 1.0 else "end_turn"
        # Telugu-ish text; ~1.4 chars per token
        sentence = {"ml": "നിങ്ങളുടെ ജാതകത്തിൽ വ്യാഴം ശുഭമാണ്. ",
                    "hi": "आपकी कुंडली में गुरु शुभ है। "}.get(self.lang, "మీ జాతకంలో గురువు శుభుడు. ")
        text = (sentence * 400)[:int(out * 1.4)]
        return _Stream(text, _Final(text, self._in(kw["system"], kw["messages"]), out, stop))


# ---------------- storage / billing ----------------

class FakeRepo:
    def __init__(self, balance=5000):
        self.balance = balance
        self.messages, self.traces, self.rollups, self.sessions = [], [], [], {}
        self.memory = {}

    def install(self, monkeypatch, repo):
        monkeypatch.setattr(repo, "get_profile", lambda uid, pid: dict(PROFILE, id=pid))
        monkeypatch.setattr(repo, "list_profiles", lambda uid, limit=12: [
            {"id": "p1", "name": "Ravi", "relation": "self"}])
        monkeypatch.setattr(repo, "get_memory", lambda uid, pid: list(self.memory.get(pid, [])))
        monkeypatch.setattr(repo, "save_memory",
                            lambda uid, pid, facts: self.memory.__setitem__(pid, facts))
        monkeypatch.setattr(repo, "add_message", lambda *a: self.messages.append(a))
        monkeypatch.setattr(repo, "update_session",
                            lambda sid, f: self.sessions.setdefault(sid, []).append(f))
        monkeypatch.setattr(repo, "write_trace", lambda d: self.traces.append(d))
        monkeypatch.setattr(repo, "incr_rollup", lambda f: self.rollups.append(f))
        monkeypatch.setattr(repo, "get_balance", lambda uid: self.balance)


class InsufficientBalance(Exception):
    pass


class FakeBilling:
    InsufficientBalance = InsufficientBalance

    def __init__(self, repo, fail=False):
        self.repo, self.fail, self.calls = repo, fail, []

    def charge(self, uid, units, type, ref):
        self.calls.append((uid, units, type, ref))
        if self.fail or self.repo.balance < units:
            raise InsufficientBalance()
        self.repo.balance -= units
        return self.repo.balance


PROFILE = {"name": "Ravi", "relation": "self", "time_known": True, "gender": "m",
           "birth": {"date": "1990-05-17", "time": "14:30", "tz": "Asia/Kolkata",
                     "lat": 9.9312, "lon": 76.2673, "place": "Kochi"}}

FLAGS = {"voice_cloud_enabled": True, "opus_enabled": True, "query_price_units": 1000,
         "cost_ceiling_units": 500, "maintenance_message": ""}


