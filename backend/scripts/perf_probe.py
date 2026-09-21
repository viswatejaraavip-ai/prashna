#!/usr/bin/env python3
"""Latency probe for every non-AI endpoint of the Prashna API.

Times each endpoint over N runs against a live base URL and prints p50/p95
plus payload sizes (wire bytes vs decoded bytes, so you can see whether gzip
actually kicked in). The first pass is reported separately as "cold" — on
Cloud Run with ``min_instance_count = 0`` the very first request after ~15
minutes of idle pays the container cold start, so run this probe against an
idle service to see the real first-launch experience.

Usage::

    # token from the JWT secret in Secret Manager
    JWT_SECRET=$(gcloud secrets versions access latest \
        --secret=udhyath-jwt-secret --project your-gcp-project) \
    python backend/scripts/perf_probe.py \
        --base-url https://your-service.run.app \
        --uid <a funded test user's uid> \
        --profile jY9caYAi8NJgwpShDeVW --runs 5

    # or with an app JWT you already have
    python backend/scripts/perf_probe.py --base-url ... --token eyJ...

Options of note::

    --cold-only     one pass only (measure a cold start, then stop)
    --sleep N       seconds between passes
    --only PAT      only probe endpoints whose name contains PAT
    --json FILE     also write the raw numbers, for before/after diffing
    --compare FILE  print a before/after table against an earlier --json run

``backend/scripts/perf_baseline.json`` holds the numbers measured against the
live service on 2026-09-20, before the cold-start / sign-in / dosha-scan work,
so after a deploy::

    python backend/scripts/perf_probe.py --runs 5 \
        --compare backend/scripts/perf_baseline.json

Nothing here writes to the database: every probed endpoint is a GET, except
``auth/firebase`` which is deliberately sent a syntactically valid but
unsigned token so it exercises ``verify_id_token`` (cert fetch + verify) and
fails at 401 without creating a user.
"""

from __future__ import annotations

import argparse
import base64
import gzip
import io
import json
import os
import statistics
import sys
import time
from typing import Dict, List, Optional, Tuple

DEFAULT_BASE = "https://your-service.run.app"
DEFAULT_UID = ""
DEFAULT_PROFILE = "jY9caYAi8NJgwpShDeVW"

# Chart kinds a normal (non-Pro) user can ask for; these are the ones the app
# actually renders on the Charts tab.
CHART_KINDS = ("rasi", "navamsa", "bhava", "dashas", "panchanga", "yogas",
               "doshas", "gemstones")


# --------------------------------------------------------------------------- token


def mint_token(uid: str, secret: str, hours: int = 24) -> str:
    """Same HS256 app JWT as ``store.issue_token`` (kept dependency-free so the
    probe runs without the backend venv)."""
    import hashlib
    import hmac

    def seg(obj) -> bytes:
        raw = json.dumps(obj, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=")

    now = int(time.time())
    head = seg({"alg": "HS256", "typ": "JWT"})
    body = seg({"sub": uid, "iat": now, "exp": now + hours * 3600})
    signing = head + b"." + body
    sig = hmac.new(secret.encode(), signing, hashlib.sha256).digest()
    return (signing + b"." + base64.urlsafe_b64encode(sig).rstrip(b"=")).decode()


# --------------------------------------------------------------------------- http


class Result:
    __slots__ = ("status", "ms", "wire", "body", "encoding", "err")

    def __init__(self, status: int, ms: float, wire: int, body: int,
                 encoding: str, err: str = ""):
        self.status, self.ms, self.wire, self.body = status, ms, wire, body
        self.encoding, self.err = encoding, err


class Client:
    """One keep-alive HTTPS connection, like OkHttp's pool in the app.

    Without this every sample also pays a TCP + TLS handshake (~110 ms from a
    laptop to asia-south1), which swamps the server-side numbers we are
    trying to compare. ``keepalive=False`` reproduces the first-request cost.
    """

    def __init__(self, base_url: str, timeout: float = 120.0, keepalive: bool = True):
        from urllib.parse import urlsplit
        u = urlsplit(base_url)
        self.host = u.netloc
        self.https = u.scheme != "http"
        self.prefix = u.path.rstrip("/")
        self.timeout, self.keepalive = timeout, keepalive
        self._conn = None

    def connect(self):
        import http.client
        if self._conn is None:
            cls = http.client.HTTPSConnection if self.https else http.client.HTTPConnection
            self._conn = cls(self.host, timeout=self.timeout)
            self._conn.connect()
        return self._conn

    def close(self):
        if self._conn is not None:
            try:
                self._conn.close()
            finally:
                self._conn = None

    def request(self, method: str, path: str, token: Optional[str], lang: str,
                payload: Optional[dict] = None) -> Result:
        data = json.dumps(payload).encode() if payload is not None else None
        headers = {"Accept": "application/json", "Accept-Encoding": "gzip",
                   "X-Client": "perf-probe", "Host": self.host}
        if lang:
            headers["Accept-Language"] = lang
        if token:
            headers["Authorization"] = "Bearer " + token
        if data is not None:
            headers["Content-Type"] = "application/json"
        if not self.keepalive:
            self.close()
        t0 = time.perf_counter()
        for attempt in (0, 1):  # a pooled connection the server closed: retry once
            try:
                conn = self.connect()
                conn.request(method, self.prefix + path, body=data, headers=headers)
                resp = conn.getresponse()
                raw = resp.read()
                break
            except Exception as exc:
                self.close()
                if attempt:
                    return Result(0, (time.perf_counter() - t0) * 1000, 0, 0, "", repr(exc))
                t0 = time.perf_counter()
        ms = (time.perf_counter() - t0) * 1000
        enc = (resp.getheader("content-encoding") or "").lower()
        decoded = raw
        if enc == "gzip":
            try:
                decoded = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
            except Exception:
                pass
        if not self.keepalive:
            self.close()
        return Result(resp.status, ms, len(raw), len(decoded), enc)


# --------------------------------------------------------------------------- probes


def build_probes(profile: str) -> List[Tuple[str, str, str, Optional[dict], bool]]:
    """(name, method, path, json body or None, needs_auth)."""
    p = profile
    probes: List[Tuple[str, str, str, Optional[dict], bool]] = [
        # /healthz measures the network floor only: the Google Front End
        # answers it with its own 404 and never forwards it to the container.
        # /api/healthz is the same handler but actually reaches the app, so
        # the gap between the two is the Cloud Run round trip.
        ("healthz(gfe)", "GET", "/healthz", None, False),
        ("healthz(app)", "GET", "/api/healthz", None, False),
        # Exercises firebase_admin.verify_id_token (Google cert fetch on a cold
        # process) without creating anything: the token is well-formed JWT
        # shaped but unsigned, so it always ends in 401.
        ("auth/firebase(verify)", "POST", "/api/auth/firebase",
         {"id_token": mint_token("probe-not-a-real-firebase-uid", "probe"),
          "device_id": "", "lang": "te"}, False),
        ("me", "GET", "/api/me", None, True),
        ("pricing", "GET", "/api/pricing", None, False),
        ("profiles", "GET", "/api/profiles", None, True),
        ("snapshot", "GET", "/api/profiles/%s/snapshot" % p, None, True),
        ("daily", "GET", "/api/daily?profile_id=%s" % p, None, True),
    ]
    for kind in CHART_KINDS:
        probes.append(("chart:%s" % kind, "GET",
                       "/api/profiles/%s/chart?kind=%s" % (p, kind), None, True))
    probes += [
        ("chart:rasi?raw=0", "GET",
         "/api/profiles/%s/chart?kind=rasi&raw=0" % p, None, True),
        ("alerts", "GET", "/api/profiles/%s/alerts" % p, None, True),
        ("places?q=hyd", "GET", "/api/places?q=hyd", None, True),
        ("legal/terms", "GET", "/api/legal/terms", None, False),
        ("wallet/ledger", "GET", "/api/wallet/ledger?limit=50", None, True),
    ]
    return probes


def pct(values: List[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    idx = min(len(s) - 1, max(0, int(round(q * (len(s) - 1)))))
    return s[idx]


def kb(n: float) -> str:
    return "-" if not n else ("%.1f" % (n / 1024.0))


def run(args) -> Dict[str, Dict]:
    token = args.token
    if not token:
        secret = args.secret or os.environ.get("JWT_SECRET", "")
        if not secret:
            sys.exit("need --token, or --secret / $JWT_SECRET to mint one "
                     "(gcloud secrets versions access latest "
                     "--secret=udhyath-jwt-secret --project your-gcp-project)")
        token = mint_token(args.uid, secret)
    base = args.base_url.rstrip("/")
    probes = build_probes(args.profile)
    if args.only:
        probes = [p for p in probes if args.only in p[0]]
    passes = 1 if args.cold_only else args.runs
    client = Client(base, timeout=args.timeout, keepalive=not args.no_keepalive)

    out: Dict[str, Dict] = {}
    for i in range(passes):
        if i and args.sleep:
            time.sleep(args.sleep)
        label = "cold" if i == 0 else "warm"
        for name, method, path, body, needs_auth in probes:
            r = client.request(method, path, token if needs_auth else None,
                               args.lang, body)
            rec = out.setdefault(name, {"cold": None, "warm": [], "status": r.status,
                                        "wire": r.wire, "body": r.body,
                                        "encoding": r.encoding, "err": r.err})
            rec["status"], rec["encoding"] = r.status, r.encoding
            if r.wire:
                rec["wire"], rec["body"] = r.wire, r.body
            if r.err:
                rec["err"] = r.err
            if label == "cold":
                rec["cold"] = r.ms
            else:
                rec["warm"].append(r.ms)
            if args.verbose:
                print("  %-22s %-5s %3d %7.0f ms %8s B" %
                      (name, label, r.status, r.ms, r.wire), file=sys.stderr)
    client.close()
    return out


def table(out: Dict[str, Dict], title: str) -> None:
    print("\n%s" % title)
    print("%-24s %5s %9s %9s %9s %9s %9s  %s" %
          ("endpoint", "code", "cold ms", "p50 ms", "p95 ms", "wire KB",
           "json KB", "enc"))
    print("-" * 96)
    for name, rec in out.items():
        warm = rec["warm"]
        print("%-24s %5s %9s %9s %9s %9s %9s  %s" % (
            name, rec["status"],
            "%.0f" % rec["cold"] if rec["cold"] is not None else "-",
            "%.0f" % pct(warm, 0.5) if warm else "-",
            "%.0f" % pct(warm, 0.95) if warm else "-",
            kb(rec["wire"]), kb(rec["body"]), rec["encoding"] or "none"))
        if rec.get("err"):
            print("    ! %s" % rec["err"])
    warms = [m for rec in out.values() for m in rec["warm"]]
    if warms:
        print("-" * 96)
        print("all warm requests: n=%d  p50=%.0f ms  p95=%.0f ms  mean=%.0f ms"
              % (len(warms), pct(warms, 0.5), pct(warms, 0.95),
                 statistics.fmean(warms)))


def compare(before: Dict[str, Dict], after: Dict[str, Dict]) -> None:
    print("\nbefore -> after (warm p50 / p95, wire KB)")
    print("%-24s %19s %19s %15s" % ("endpoint", "p50 ms", "p95 ms", "wire KB"))
    print("-" * 82)
    for name, rec in after.items():
        b = before.get(name)
        if not b:
            continue
        def cell(bv, av, fmt="%.0f"):
            arrow = "->"
            delta = ""
            if bv and av:
                delta = " (%+.0f%%)" % ((av - bv) * 100.0 / bv)
            return ("%s %s %s%s" % (fmt % bv if bv else "-", arrow,
                                    fmt % av if av else "-", delta))
        print("%-24s %19s %19s %15s" % (
            name,
            cell(pct(b["warm"], 0.5), pct(rec["warm"], 0.5)),
            cell(pct(b["warm"], 0.95), pct(rec["warm"], 0.95)),
            "%s -> %s" % (kb(b["wire"]), kb(rec["wire"]))))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", default=os.environ.get("PROBE_BASE_URL", DEFAULT_BASE))
    ap.add_argument("--token", default=os.environ.get("PROBE_TOKEN", ""))
    ap.add_argument("--secret", default="")
    ap.add_argument("--uid", default=DEFAULT_UID)
    ap.add_argument("--profile", default=DEFAULT_PROFILE)
    ap.add_argument("--lang", default="te")
    ap.add_argument("--runs", type=int, default=5, help="passes; the 1st is 'cold'")
    ap.add_argument("--sleep", type=float, default=0.0, help="seconds between passes")
    ap.add_argument("--timeout", type=float, default=120.0)
    ap.add_argument("--cold-only", action="store_true")
    ap.add_argument("--no-keepalive", action="store_true",
                    help="new TCP+TLS connection per request (worst case)")
    ap.add_argument("--only", default="")
    ap.add_argument("--json", default="", help="write raw numbers here")
    ap.add_argument("--compare", default="", help="an earlier --json file")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    out = run(args)
    table(out, "%s  (%d pass%s, lang=%s)"
          % (args.base_url, 1 if args.cold_only else args.runs,
             "" if args.cold_only else "es", args.lang))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=1)
        print("\nwrote %s" % args.json)
    if args.compare:
        with open(args.compare, encoding="utf-8") as fh:
            compare(json.load(fh), out)


if __name__ == "__main__":
    main()
