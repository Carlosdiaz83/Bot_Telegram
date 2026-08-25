# ============================================
# Sofía Comercial AI — Dockerfile
# ============================================

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Instalar dependencias del sistema (PostgreSQL driver + Tesseract OCR)
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libpq-dev tesseract-ocr tesseract-ocr-spa libgl1 libglib2.0-0 && \
    rm -rf /var/lib/apt/lists/*

# Instalar dependencias Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ============================================
# Stage: producción
# ============================================
FROM base AS production

RUN mkdir -p /app/data /app/logs

COPY app/ ./app/
COPY pyproject.toml .
COPY servired_knowledge/ ./servired_knowledge/

ENV APP_ENV=production \
    APP_DEBUG=false \
    LOG_LEVEL=INFO

EXPOSE 8000

# Health check real
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# Render y Docker: ejecutar app unificada (FastAPI + Telegram bot)
CMD ["uvicorn", "app.server:app", "--host", "0.0.0.0", "--port", "8000"]
