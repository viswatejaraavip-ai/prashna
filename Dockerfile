FROM python:3.11-slim

WORKDIR /app

# python:3.11 matches pyswisseph's prebuilt manylinux wheels - no compiler needed.
RUN pip install --no-cache-dir --upgrade pip

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

COPY engine /app/engine
COPY backend /app/backend

ENV ENGINE_PATH=/app/engine
ENV PYTHONUNBUFFERED=1

EXPOSE 8000
WORKDIR /app/backend
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
