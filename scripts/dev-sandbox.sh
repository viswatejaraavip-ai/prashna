#!/bin/sh
# Run the backend locally with the AICredits dev sandbox as inference provider.
# Usage: ./scripts/dev-sandbox.sh   (then open http://localhost:8890)
cd "$(dirname "$0")/.."
set -a; . backend/.env.dev; set +a
exec .venv/bin/python -m uvicorn app.main:app --app-dir backend --port 8890
