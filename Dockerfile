# ============================================
# Sofía Comercial AI — Dockerfile
# ============================================
# Multi-stage build para producción
# ============================================

FROM python:3.12-slim AS base

# Evitar que Python guarde .pyc y forzar salida unbuffered
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Instalar dependencias del sistema
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

# Instalar dependencias Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ============================================
# Stage: producción
# ============================================
FROM base AS production

# Crear directorio de datos y logs
RUN mkdir -p /app/data /app/logs

# Copiar código fuente
COPY app/ ./app/
COPY pyproject.toml .

# Variables de entorno por defecto (sobreescribir en .env o docker-compose)
ENV APP_ENV=production \
    APP_DEBUG=false \
    LOG_LEVEL=INFO \
    DATABASE_URL=sqlite:///./data/health_advisor.db

# Puerto del panel web (opcional)
EXPOSE 8000

# Health check básico
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import sys; sys.exit(0)"

# Comando por defecto: ejecutar el bot de Telegram
CMD ["python", "-m", "app.main"]
