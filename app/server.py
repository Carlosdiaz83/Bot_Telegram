"""
Sofía Comercial AI — App unificada para Render.

Combina FastAPI (panel web + health check) con el bot de Telegram
(ejecutado en un hilo de fondo). Render necesita un proceso web
que pueda recibir health checks.

Uso:
    python -m app.server
    # o
    gunicorn app.server:app
"""

from __future__ import annotations

import logging
import threading
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.config.settings import BotConfig
from app.utils.logging_config import setup_logging

logger = logging.getLogger(__name__)

_config: BotConfig | None = None


def _run_telegram_bot(config: BotConfig) -> None:
    """Ejecuta el bot de Telegram en un hilo de fondo."""
    try:
        from app.telegram.bot import TelegramBot
        bot = TelegramBot(config)
        bot.run()
    except Exception as e:
        logger.error("Error en bot de Telegram: %s", str(e), exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle: inicia el bot de Telegram al arrancar."""
    global _config
    if _config is None:
        _config = BotConfig.from_env()

    # Iniciar DB
    from app.database.database import get_engine, crear_tablas
    engine = get_engine(_config.database_url)
    crear_tablas(engine)

    # Iniciar Telegram bot en hilo daemon
    telegram_thread = threading.Thread(
        target=_run_telegram_bot,
        args=(_config,),
        daemon=True,
        name="telegram-bot",
    )
    telegram_thread.start()
    logger.info("Bot de Telegram iniciado en hilo de fondo")

    yield

    # Apagado
    from app.database.database import cerrar_engine
    cerrar_engine()
    logger.info("Aplicación detenida")


def create_app() -> FastAPI:
    """Crea la aplicación FastAPI unificada."""
    global _config

    app = FastAPI(
        title="Sofía Comercial AI",
        description="Panel web + Telegram bot para SERVIRED",
        version="1.0.0",
        lifespan=lifespan,
    )

    # Health check
    @app.get("/health")
    async def health():
        return JSONResponse({
            "status": "ok",
            "service": "sofia",
            "version": "1.0.0",
        })

    # Panel web (rutas existentes)
    try:
        from app.panel.routes import router
        app.include_router(router)
    except Exception as e:
        logger.warning("No se pudieron cargar rutas del panel: %s", str(e))

    return app


app = create_app()
