"""AI endpoints (CONTRACT.md "AI — routes_ai.py"): consultation sessions
(text, SSE, cloud voice) and the Mega life report. Exposes `router`.
"""

import functools
import json
import logging
import queue
import threading
from typing import Dict

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from . import guard, store
from .ai import pipeline, repo
from .ai.pipeline import AiError

log = logging.getLogger("udhyath.routes_ai")

router = APIRouter()

MAX_AUDIO_BYTES = 2_000_000   # 45 s of 16 kHz LINEAR16 is 1.44 MB


def _err(status: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": detail, "code": code})


def _errors(fn):
    """Turn AiError into the contract's {"detail", "code"} body."""
    @functools.wraps(fn)
    def wrapper(*a, **kw):
        try:
            return fn(*a, **kw)
        except AiError as e:
            return _err(e.status_code, e.code, e.detail)
    return wrapper


def _owned_session(sid: str, uid: str) -> Dict:
    s = repo.get_session(sid)
    if not s or s.get("uid") != uid:
        raise AiError(404, "not_found", "Session not found")
    return s


# ---------------- sessions ----------------

class SessionIn(BaseModel):
    profile_id: str
    mode: str = Field("text", pattern="^(text|voice)$")


class AskIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)


@router.post("/api/sessions")
@_errors
def create_session(body: SessionIn, request: Request,
                   uid: str = Depends(store.current_uid)):
    if not repo.get_profile(uid, body.profile_id):
        raise AiError(404, "not_found", "Profile not found")
    lang = store.lang_of(request, store.get_user(uid))
    return {"session_id": repo.create_session(uid, body.profile_id, lang, body.mode)}


@router.get("/api/sessions")
@_errors
def list_sessions(limit: int = 20, uid: str = Depends(store.current_uid)):
    rows = repo.list_sessions(uid, max(1, min(limit, 100)))
    keep = ("id", "profile_id", "lang", "mode", "created_at", "updated_at",
            "query_count", "title")
    # `summary` is the pipeline's internal English memory and is never shown.
    return [{("session_id" if k == "id" else k): r.get(k) for k in keep} for r in rows]


@router.get("/api/sessions/{sid}/messages")
@_errors
def list_messages(sid: str, uid: str = Depends(store.current_uid)):
    _owned_session(sid, uid)
    return [{k: m.get(k) for k in ("role", "text", "charged_units", "trace_id", "created_at")}
            for m in repo.list_messages(sid)]


def _validate_text(text: str) -> str:
    text = guard.sanitize(text)
    if not text:
        raise AiError(400, "invalid", "Empty question")
    if guard.too_long(text):
        raise AiError(400, "invalid", "Question too long (max %d characters)"
                      % guard.MAX_QUESTION_CHARS)
    return text


@router.post("/api/sessions/{sid}/ask")
@_errors
def ask(sid: str, body: AskIn, uid: str = Depends(store.current_uid)):
    session = _owned_session(sid, uid)
    text = _validate_text(body.text)
    r = pipeline.run_query(uid, session, text)
    return {"reply": r.reply, "charged_units": r.charged_units,
            "balance_units": r.balance_units, "status": r.status, "trace_id": r.trace_id}


def _sse(event: str, data: Dict) -> str:
    return "event: %s\ndata: %s\n\n" % (event, json.dumps(data, ensure_ascii=False))


@router.post("/api/sessions/{sid}/ask/stream")
@_errors
def ask_stream(sid: str, body: AskIn, uid: str = Depends(store.current_uid)):
    session = _owned_session(sid, uid)
    text = _validate_text(body.text)
    f = pipeline.precheck(uid)          # HTTP errors before the stream opens
    q: "queue.Queue" = queue.Queue()
    streamed = {"any": False}

    def on_delta(t: str):
        streamed["any"] = True
        q.put(("delta", {"text": t}))

    def on_done(done: Dict, reply: str):
        # refusals / clarifications / errors are not streamed by the model:
        # send them as one delta right before `done`.
        if not streamed["any"] and reply:
            q.put(("delta", {"text": reply}))
        q.put(("done", done))

    def worker():
        try:
            pipeline.run_query(uid, session, text, on_delta=on_delta,
                               on_done=on_done, prechecked=f)
        except AiError as e:
            q.put(("error", {"detail": e.detail, "code": e.code}))
        except Exception:  # pragma: no cover - defensive
            log.exception("stream worker failed")
            q.put(("error", {"detail": "internal error", "code": "invalid"}))
        finally:
            q.put(("end", None))

    threading.Thread(target=worker, daemon=True).start()

    def gen():
        while True:
            try:
                ev, data = q.get(timeout=15)
            except queue.Empty:
                yield ": ping\n\n"
                continue
            if ev == "end":
                return
            yield _sse(ev, data)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@router.post("/api/sessions/{sid}/voice")
@_errors
def voice(sid: str, audio: UploadFile = File(...), tts: bool = Form(False),
          uid: str = Depends(store.current_uid)):
    session = _owned_session(sid, uid)
    data = audio.file.read(MAX_AUDIO_BYTES + 1)
    if not data or len(data) > MAX_AUDIO_BYTES:
        raise AiError(400, "invalid", "Audio missing or too large")
    r = pipeline.run_query(uid, session, audio=data, want_tts=bool(tts))
    out = {"transcript": r.transcript or "", "reply": r.reply,
           "charged_units": r.charged_units, "balance_units": r.balance_units,
           "status": r.status, "trace_id": r.trace_id}
    if r.audio_b64:
        out["audio_b64"] = r.audio_b64
    return out


# ---------------- Mega life report ----------------

class ReportIn(BaseModel):
    profile_id: str
    brand: bool = False


class TeaserIn(BaseModel):
    profile_id: str


def _reports():
    from . import reports
    return reports


@router.post("/api/reports")
@_errors
def create_report(body: ReportIn, request: Request, uid: str = Depends(store.current_uid)):
    lang = store.lang_of(request, store.get_user(uid))
    return _reports().start_report(uid, body.profile_id, lang, brand=body.brand)


@router.get("/api/reports")
@_errors
def my_reports(uid: str = Depends(store.current_uid)):
    return _reports().list_reports(uid)


@router.post("/api/reports/teaser")
@_errors
def report_teaser(body: TeaserIn, request: Request, uid: str = Depends(store.current_uid)):
    lang = store.lang_of(request, store.get_user(uid))
    return _reports().generate_teaser(uid, body.profile_id, lang)


@router.get("/api/reports/{report_id}")
@_errors
def get_report(report_id: str, uid: str = Depends(store.current_uid)):
    return _reports().get_report(uid, report_id)


@router.post("/api/reports/{report_id}/resume")
@_errors
def resume_report(report_id: str, uid: str = Depends(store.current_uid)):
    return _reports().resume_report(uid, report_id)


@router.get("/api/reports/{report_id}/pdf")
@_errors
def report_pdf(report_id: str, uid: str = Depends(store.current_uid)):
    return {"url": _reports().pdf_url(uid, report_id)}
