# syntax=docker/dockerfile:1

# --- builder stage ---
FROM python:3.11-slim AS builder
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends build-essential && \
    rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN pip install --upgrade pip && pip wheel --wheel-dir /wheels -r requirements.txt

# --- runtime stage ---
FROM python:3.11-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app
WORKDIR /app
# Create non-root user
RUN addgroup --system app && adduser --system --ingroup app app
COPY --from=builder /wheels /wheels
RUN pip install --no-index --find-links=/wheels -r /wheels/..data/requirements.txt 2>/dev/null || pip install --no-index --find-links=/wheels $(ls /wheels/*.whl)
COPY . .
RUN chown -R app:app /app
USER app
EXPOSE 8080
CMD ["python", "-m", "app"]
