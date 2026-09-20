#!/usr/bin/env bash
# Run the Prashna integration suite locally.
#
#   backend/scripts/run_integration.sh              # the whole suite
#   backend/scripts/run_integration.sh -k astrologer  # extra pytest args
#
# No cloud credentials, no emulator, no network: the suite runs the real
# FastAPI app (app.main_gcp) against an in-memory Firestore and fake model /
# Play / Razorpay / Speech / FCM clients. See docs/launch/TESTING.md.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BACKEND="$ROOT/backend"
VENV="${VENV:-$ROOT/.venv}"
PY="$VENV/bin/python"

red()   { printf '\033[31m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }
info()  { printf '\033[36m%s\033[0m\n' "$*"; }

if [ ! -x "$PY" ]; then
  info "No virtualenv at $VENV — creating one (python3 -m venv)."
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install --quiet --upgrade pip
fi

# Install dependencies only when something is missing, so a warm checkout is fast.
if ! "$PY" -c "import fastapi, pytest, jwt, fpdf, PIL, razorpay" >/dev/null 2>&1; then
  info "Installing backend requirements into $VENV ..."
  "$VENV/bin/pip" install --quiet -r "$BACKEND/requirements.txt" \
                                   -r "$BACKEND/requirements-gcp.txt" pytest
fi

# Deterministic, offline environment. Nothing here points at a real project.
export JWT_SECRET="${JWT_SECRET:-integration-test-secret-0123456789abcdef}"
export GOOGLE_CLOUD_PROJECT="${GOOGLE_CLOUD_PROJECT:-test-project}"
export ADMIN_EMAILS="${ADMIN_EMAILS:-owner@example.com}"
export TRIAL_CREDIT_UNITS="${TRIAL_CREDIT_UNITS:-1000}"
export DEFAULT_LANG="${DEFAULT_LANG:-te}"
export ENGINE_PATH="${ENGINE_PATH:-$ROOT/engine}"
unset GOOGLE_APPLICATION_CREDENTIALS FIRESTORE_EMULATOR_HOST K_SERVICE || true

info "Prashna integration suite  (app.main_gcp + in-memory Firestore + fake models)"
cd "$BACKEND"
set +e
"$PY" -m pytest tests/integration -W ignore -q -rxX --durations=5 "$@"
status=$?
set -e

echo
if [ "$status" -eq 0 ]; then
  green "PASS — every integration flow is green. Safe to commit/push."
else
  red   "FAIL — integration tests did not pass (exit $status). Do not push."
  red   "       Re-run one flow with: backend/scripts/run_integration.sh -k <name> -x -vv"
fi
exit "$status"
