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
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.config.settings import BotConfig
from app.utils.logging_config import setup_logging

logger = logging.getLogger(__name__)

_config: BotConfig | None = None
_telegram_thread: threading.Thread | None = None


def _run_telegram_bot(config: BotConfig) -> None:
    """Ejecuta el bot de Telegram en un hilo de fondo."""
    thread_name = threading.current_thread().name
    logger.info("[TELEGRAM] Hilo iniciado: %s (pid=%s)", thread_name, __import__("os").getpid())

    try:
        logger.info("[TELEGRAM] Importando TelegramBot...")
        from app.telegram.bot import TelegramBot

        logger.info("[TELEGRAM] Creando instancia TelegramBot...")
        bot = TelegramBot(config)

        logger.info("[TELEGRAM] Llamando bot.run()...")
        bot.run()

        logger.info("[TELEGRAM] bot.run() retornó (esto no debería pasar con polling)")
    except Exception as e:
        logger.error(
            "[TELEGRAM] EXCEPCIÓN en hilo: %s — %s",
            type(e).__name__,
            str(e),
            exc_info=True,
        )
    except KeyboardInterrupt:
        logger.info("[TELEGRAM] Keyboard interrupt recibido")
    finally:
        logger.info("[TELEGRAM] Hilo finalizado: %s", thread_name)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle: inicia el bot de Telegram al arrancar."""
    global _config, _telegram_thread

    logger.info("=== Lifespan iniciado ===")
    logger.info("Main thread: %s", threading.current_thread().name)

    # Cargar configuración
    if _config is None:
        logger.info("Cargando BotConfig.from_env()...")
        _config = BotConfig.from_env()
        logger.info("Config cargada (env=%s, token=%s...)", _config.app_env, _config.telegram_token[:10])

    # Iniciar DB
    logger.info("Inicializando base de datos...")
    from app.database.database import get_engine, crear_tablas
    engine = get_engine(_config.database_url)
    crear_tablas(engine)
    logger.info("Base de datos lista")

    # Iniciar Telegram bot en hilo daemon
    logger.info("[TELEGRAM] Creando hilo daemon...")
    _telegram_thread = threading.Thread(
        target=_run_telegram_bot,
        args=(_config,),
        daemon=True,
        name="telegram-bot",
    )
    _telegram_thread.start()
    logger.info("[TELEGRAM] Hilo creado y start() llamado (is_alive=%s)", _telegram_thread.is_alive())

    # Esperar un momento para verificar que el hilo arrancó
    time.sleep(1.0)
    if _telegram_thread.is_alive():
        logger.info("[TELEGRAM] ✅ Hilo corriendo exitosamente")
    else:
        logger.error("[TELEGRAM] ❌ Hilo murió después de 1 segundo — revisar logs anteriores")

    yield

    # Apagado
    logger.info("Apagando aplicación...")
    from app.database.database import cerrar_engine
    cerrar_engine()
    logger.info("Aplicación detenida")


def create_app() -> FastAPI:
    """Crea la aplicación FastAPI unificada."""
    global _config

    # Configurar logging ANTES de todo
    import os
    env = os.getenv("APP_ENV", "development")
    debug = os.getenv("APP_DEBUG", "false").lower() in ("true", "1", "yes")
    log_level = os.getenv("LOG_LEVEL", "INFO")
    setup_logging(
        level=log_level,
        log_to_file=debug or env == "production",
        structured=env == "production",
    )

    logger.info("=== create_app() iniciado ===")

    app = FastAPI(
        title="Sofía Comercial AI",
        description="Panel web + Telegram bot para SERVIRED",
        version="1.0.0",
        lifespan=lifespan,
    )

    # Health check
    @app.get("/health")
    async def health():
        telegram_alive = _telegram_thread is not None and _telegram_thread.is_alive()
        return JSONResponse({
            "status": "ok",
            "service": "sofia",
            "version": "1.0.0",
            "telegram_bot": "running" if telegram_alive else "not_started",
        })

    # Panel web (rutas existentes)
    try:
        from app.panel.routes import router
        app.include_router(router)
        logger.info("Rutas del panel cargadas")
    except Exception as e:
        logger.warning("No se pudieron cargar rutas del panel: %s", str(e))

    logger.info("=== create_app() completado ===")
    return app


app = create_app()
