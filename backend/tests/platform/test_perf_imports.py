"""Cold-start guard rails.

Importing ``app.main_gcp`` is the first thing a Cloud Run container does, and
with ``min_instance_count = 0`` a real user waits for it. Every second of
module import is a second the first sign-in of the day takes, so the heavy
third-party packages must stay behind lazy imports in the code that actually
uses them:

* ``anthropic``        — only in ``agent.client()`` / ``ai.llm``
* ``google.genai``     — only in ``ai.llm``
* ``firebase_admin``   — only in ``platform_auth``
* ``fpdf`` / ``PIL``   — only in report PDFs and share cards
* ``googleapiclient``  — only in the Play purchase check

The test imports main_gcp in a clean subprocess (pytest itself will have
imported half of these already) and asserts on ``sys.modules``.
"""

import json
import os
import subprocess
import sys

import pytest

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Modules that must NOT be loaded just by importing the app.
FORBIDDEN = ("anthropic", "google.genai", "firebase_admin", "fpdf", "PIL",
             "googleapiclient", "razorpay")

# A cold import that creeps past this on CI hardware means the app's own code
# (not a dependency) started doing work at import time. Generous on purpose:
# this is a regression tripwire, not a benchmark.
MAX_IMPORT_SECONDS = 4.0

_PROBE = r"""
import json, sys, time
t0 = time.perf_counter()
import app.main_gcp  # noqa: F401
elapsed = time.perf_counter() - t0
print(json.dumps({"elapsed": elapsed, "modules": sorted(sys.modules)}))
"""


@pytest.fixture(scope="module")
def cold_import():
    env = dict(os.environ, PYTHONPATH=BACKEND, WARMUP_ON_START="0",
               GOOGLE_CLOUD_PROJECT=os.environ.get("GOOGLE_CLOUD_PROJECT", "test-project"),
               JWT_SECRET=os.environ.get("JWT_SECRET", "test-secret"))
    out = subprocess.run([sys.executable, "-c", _PROBE], cwd=BACKEND, env=env,
                         capture_output=True, text=True, timeout=180)
    assert out.returncode == 0, out.stderr[-4000:]
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_no_heavy_imports_at_startup(cold_import):
    loaded = set(cold_import["modules"])
    offenders = [m for m in FORBIDDEN
                 if m in loaded or any(x.startswith(m + ".") for x in loaded)]
    assert not offenders, (
        "importing app.main_gcp pulled in %s; keep these behind a function-level "
        "import so Cloud Run cold starts stay short" % ", ".join(offenders))


def test_import_is_not_slow(cold_import):
    assert cold_import["elapsed"] < MAX_IMPORT_SECONDS, (
        "app.main_gcp took %.2fs to import" % cold_import["elapsed"])
