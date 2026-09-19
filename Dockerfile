FROM python:3.11-slim

# python:3.11 matches pyswisseph's prebuilt manylinux wheels - no compiler needed.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    ENGINE_PATH=/app/engine \
    PORT=8080

WORKDIR /app

RUN pip install --upgrade pip

# Dependencies first so code edits don't bust the layer cache.
COPY backend/requirements.txt backend/requirements-gcp.txt /app/backend/
RUN pip install -r /app/backend/requirements.txt -r /app/backend/requirements-gcp.txt

# Keep the engine path layout: /app/engine (jyotish package) + /app/backend.
COPY engine /app/engine
COPY backend /app/backend

RUN useradd --system --uid 10001 --home /app udhyath \
    && rm -f /app/backend/local.db \
    && chown -R udhyath /app
USER udhyath

WORKDIR /app/backend
EXPOSE 8080
# Cloud Run sets $PORT. One process per container; Cloud Run scales out.
# timeout-keep-alive > the Cloud Run LB idle timeout avoids 502s on reuse.
CMD exec uvicorn app.main_gcp:app --host 0.0.0.0 --port ${PORT} \
    --proxy-headers --forwarded-allow-ips='*' --timeout-keep-alive 650
