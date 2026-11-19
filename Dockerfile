# ── Stage 1: build dependencies ───────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libssl-dev \
        libffi-dev \
        libpq-dev \
        default-libmysqlclient-dev \
        pkg-config \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

# Non-root user
RUN groupadd --gid 1001 appgroup \
 && useradd  --uid 1001 --gid appgroup --no-create-home appuser

WORKDIR /app

# Runtime OS dependencies (WeasyPrint needs pango/cairo)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libcairo2 \
        libgdk-pixbuf2.0-0 \
        libssl3 \
        default-libmysqlclient-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local

COPY backend/   ./backend/
COPY frontend/  ./frontend/

# Create writable directory for generated briefing PDFs
RUN mkdir -p /app/instance/briefings \
 && chown -R appuser:appgroup /app

USER appuser

EXPOSE 8080

ENV FLASK_ENV=production \
    PDF_DIR=/app/instance/briefings

# Code Engine health check — calls the /healthz endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8080/healthz || exit 1

CMD ["gunicorn", \
     "--bind", "0.0.0.0:8080", \
     "--workers", "2", \
     "--threads", "4", \
     "--timeout", "120", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "backend.app:create_app()"]
