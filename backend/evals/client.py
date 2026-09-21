"""Thin clients for the three things the evaluation talks to:

  * the LIVE Prashna HTTP API (profiles, charts, sessions, ask)   -- costs money
  * Firestore, read-only, for the per-query trace and its cost    -- free
  * the Anthropic API for the judge model                         -- costs money

Nothing here imports `app.*`: the point of this evaluation is to exercise the
deployed product over HTTP, not the library in this repo.
"""

import json
import os
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, List, Optional

BASE_URL = os.environ.get(
    "EVAL_API_BASE", "https://your-service.run.app")
TOKEN_FILE = os.environ.get("EVAL_TOKEN_FILE", "/tmp/eval_token.txt")
PROJECT = os.environ.get("EVAL_GCP_PROJECT", "your-gcp-project")
TFVARS = os.environ.get(
    "EVAL_TFVARS",
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "deploy", "gcp", "terraform", "terraform.tfvars"))


class ApiError(RuntimeError):
    def __init__(self, status: int, body: str):
        super().__init__("HTTP %d: %s" % (status, body[:400]))
        self.status, self.body = status, body


def _token() -> str:
    with open(TOKEN_FILE) as fh:
        return fh.read().strip()


def secret(name: str) -> str:
    """Read `name = "value"` out of terraform.tfvars. Never printed."""
    with open(TFVARS) as fh:
        for line in fh:
            if line.strip().startswith(name):
                _, _, rhs = line.partition("=")
                return rhs.strip().strip('"')
    raise KeyError(name)


# ---------------------------------------------------------------- live API

def api(path: str, body: Optional[Dict] = None, lang: str = "en",
        method: Optional[str] = None, timeout: int = 180) -> Dict:
    url = BASE_URL.rstrip("/") + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url, data=data, method=method or ("POST" if data is not None else "GET"),
        headers={"Authorization": "Bearer " + _token(),
                 "Content-Type": "application/json",
                 "Accept-Language": lang})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raise ApiError(e.code, e.read().decode("utf-8", "replace"))


RATE_LIMIT_WAIT_S = 90


def api_retry(path: str, body: Optional[Dict] = None, lang: str = "en",
              tries: int = 3) -> Dict:
    """The app rate-limits a uid to AGENT_RATE_LIMIT_MESSAGES per 5 minutes
    (20 by default) and this harness is a single user firing continuously, so
    a 429 is expected housekeeping, not a product failure. Back off and retry."""
    last = None
    for attempt in range(tries):
        try:
            return api(path, body, lang)
        except ApiError as e:
            last = e
            if e.status != 429 and "rate_limited" not in e.body:
                raise
            print("      rate-limited, waiting %ds (attempt %d/%d)"
                  % (RATE_LIMIT_WAIT_S, attempt + 1, tries), flush=True)
            time.sleep(RATE_LIMIT_WAIT_S)
    raise last


def create_profile(name: str, relation: str, birth: Dict, time_known: bool,
                   gender: Optional[str]) -> Dict:
    return api("/api/profiles", {"name": name, "relation": relation, "birth": birth,
                                 "time_known": time_known, "gender": gender})


def list_profiles() -> List[Dict]:
    return api("/api/profiles?include_clients=true")["profiles"]


def chart(pid: str, kind: str) -> Dict:
    return api("/api/profiles/%s/chart?kind=%s" % (pid, kind), lang="en")


def ask(pid: str, text: str, lang: str) -> Dict:
    """One real, charged consultation turn. Returns the API body plus timing."""
    t0 = time.time()
    sid = api_retry("/api/sessions", {"profile_id": pid, "mode": "text"},
                    lang=lang)["session_id"]
    out = api_retry("/api/sessions/%s/ask" % sid, {"text": text}, lang=lang)
    out["session_id"] = sid
    out["wall_ms"] = int((time.time() - t0) * 1000)
    return out


# ---------------------------------------------------------- Firestore (RO)

_at_cache = {"tok": "", "at": 0.0}


def _access_token() -> str:
    if time.time() - _at_cache["at"] > 1800:
        _at_cache["tok"] = subprocess.check_output(
            ["gcloud", "auth", "print-access-token"], text=True, timeout=90).strip()
        _at_cache["at"] = time.time()
    return _at_cache["tok"]


def _decode(v: Dict):
    (k, val), = v.items()
    if k == "integerValue":
        return int(val)
    if k == "doubleValue":
        return float(val)
    if k == "booleanValue":
        return bool(val)
    if k == "nullValue":
        return None
    if k == "mapValue":
        return {kk: _decode(vv) for kk, vv in (val.get("fields") or {}).items()}
    if k == "arrayValue":
        return [_decode(x) for x in (val.get("values") or [])]
    return val


def trace(trace_id: str, retries: int = 6) -> Optional[Dict]:
    """The pipeline files the trace on a background thread, so poll briefly."""
    url = ("https://firestore.googleapis.com/v1/projects/%s/databases/(default)"
           "/documents/traces/%s" % (PROJECT, urllib.parse.quote(trace_id)))
    for i in range(retries):
        req = urllib.request.Request(
            url, headers={"Authorization": "Bearer " + _access_token()})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                doc = json.loads(resp.read().decode())
            return {k: _decode(v) for k, v in (doc.get("fields") or {}).items()}
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
        time.sleep(1.5 * (i + 1))
    return None
