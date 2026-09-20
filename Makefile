# Prashna — local developer tasks.
#
#   make test-integration   every user flow, end to end, offline   <- run before pushing
#   make test-unit          the per-module unit tests
#   make test               unit + integration (what CI runs)
#   make test-android       ./gradlew testDebugUnitTest (needs a JDK + Android SDK)
#   make venv               create .venv and install the backend requirements
#   make run                serve the API locally on :8080
#
# Nothing here needs cloud credentials. See docs/launch/TESTING.md.

SHELL := /bin/bash
ROOT  := $(shell cd $(dir $(lastword $(MAKEFILE_LIST))) && pwd)
VENV  ?= $(ROOT)/.venv
PY    := $(VENV)/bin/python
PIP   := $(VENV)/bin/pip
PYTEST_ARGS ?=

export JWT_SECRET ?= integration-test-secret-0123456789abcdef
export GOOGLE_CLOUD_PROJECT ?= test-project
export ADMIN_EMAILS ?= owner@example.com
export ENGINE_PATH ?= $(ROOT)/engine

.PHONY: help venv test test-unit test-integration test-android run clean

help:
	@grep -E '^#   make ' $(lastword $(MAKEFILE_LIST)) | sed 's/^#   /  /'

venv: $(PY)

$(PY):
	python3 -m venv $(VENV)
	$(PIP) install --quiet --upgrade pip
	$(PIP) install --quiet -r $(ROOT)/backend/requirements.txt \
	                       -r $(ROOT)/backend/requirements-gcp.txt pytest

## Integration: the real app (app.main_gcp) + in-memory Firestore + fake models.
test-integration: venv
	@bash $(ROOT)/backend/scripts/run_integration.sh $(PYTEST_ARGS)

## Unit: each workstream's own tests (platform, ai, features, admin).
## (`tests` minus `tests/integration`: the per-directory conftests share module
##  names, so pytest must be given the parent directory, not a list of dirs.)
test-unit: venv
	@cd $(ROOT)/backend && $(PY) -m pytest tests --ignore=tests/integration \
		-W ignore -q $(PYTEST_ARGS)
	@printf '\033[32m%s\033[0m\n' "PASS — unit tests green."

## Everything CI runs on the backend.
test: test-unit test-integration

## Android unit tests (skipped with a clear message when no JDK/SDK is here).
test-android:
	@if [ ! -f $(ROOT)/android/app/google-services.json ]; then \
	  cp $(ROOT)/android/app/google-services.example.json \
	     $(ROOT)/android/app/google-services.json; \
	  echo "note: using google-services.example.json (UI-only build)"; \
	fi
	@cd $(ROOT)/android && ./gradlew --no-daemon testDebugUnitTest

run: venv
	@cd $(ROOT)/backend && $(PY) -m uvicorn app.main_gcp:app --reload --port 8080

clean:
	find $(ROOT)/backend -name __pycache__ -type d -prune -exec rm -rf {} +
	rm -rf $(ROOT)/.pytest_cache
