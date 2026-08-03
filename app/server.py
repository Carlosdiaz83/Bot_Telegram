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

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config.settings import BotConfig
from app.utils.logging_config import setup_logging

logger = logging.getLogger(__name__)

_config: BotConfig | None = None
_telegram_thread: threading.Thread | None = None
_telegram_bot = None
_webhook_ready = False


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
    global _config, _telegram_thread, _telegram_bot, _webhook_ready

    logger.info("=== Lifespan iniciado ===")
    logger.info("Main thread: %s", threading.current_thread().name)

    # Cargar configuración
    if _config is None:
        logger.info("Cargando BotConfig.from_env()...")
        _config = BotConfig.from_env()
        logger.info("Config cargada (env=%s, token=%s...)", _config.app_env, _config.telegram_token[:10])

    # Iniciar DB + migraciones
    logger.info("Inicializando base de datos...")
    from app.database.database import get_engine, crear_tablas, get_session_factory
    from app.database.migrations import ejecutar_migraciones
    from app.database.bootstrap import bootstrap_datos
    engine = get_engine(_config.database_url)
    crear_tablas(engine)
    ejecutar_migraciones(engine)

    # Verificar datos esenciales (precios, aportes, knowledge)
    logger.info("Verificando datos iniciales en la base de datos...")
    session_factory = get_session_factory(engine)
    db = session_factory()
    try:
        bootstrap_datos(db)
    except Exception as exc:
        logger.error("[BOOTSTRAP] Error durante verificación de datos: %s", exc)
    finally:
        db.close()

    logger.info("Base de datos lista")

    # Iniciar Telegram bot: webhook (prod) o polling (dev)
    from app.telegram.bot import TelegramBot

    if _config.telegram_webhook:
        logger.info("[TELEGRAM] Modo WEBHOOK activado (TELEGRAM_WEBHOOK=true)")
        try:
            _telegram_bot = TelegramBot(_config)
            await _telegram_bot.start_webhook()
            _webhook_ready = True
            logger.info("[TELEGRAM] Webhook listo para recibir updates en /webhook/<token>")
        except Exception as exc:
            logger.error("[TELEGRAM] Error inicializando webhook: %s", exc, exc_info=True)
            _webhook_ready = False
    else:
        logger.info("[TELEGRAM] Modo POLLING (desarrollo)")
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
    try:
        if _webhook_ready and _telegram_bot is not None:
            await _telegram_bot.stop_webhook()
            _webhook_ready = False
    except Exception as exc:
        logger.error("[TELEGRAM] Error cerrando webhook: %s", exc)
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

    # Webhook de Telegram: recibe updates vía POST (modo webhook en Render)
    @app.post("/webhook/{token}")
    async def telegram_webhook(token: str, request: Request):
        global _webhook_ready, _telegram_bot
        if _config is None or token != _config.telegram_token:
            return JSONResponse({"ok": False, "error": "token inválido"}, status_code=404)
        if not _webhook_ready or _telegram_bot is None:
            return JSONResponse({"ok": False, "error": "webhook no inicializado"}, status_code=503)

        try:
            payload = await request.json()
            await _telegram_bot.process_update_payload(payload)
            return JSONResponse({"ok": True})
        except Exception as exc:
            logger.error("[WEBHOOK] Error procesando update: %s", exc, exc_info=True)
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)

    # Health check
    @app.get("/health")
    async def health():
        telegram_alive = _telegram_thread is not None and _telegram_thread.is_alive()
        telegram_status = (
            "webhook_ready"
            if _webhook_ready
            else ("running" if telegram_alive else "not_started")
        )
        import subprocess
        try:
            commit = subprocess.run(
                ["git", "log", "--oneline", "-1"],
                capture_output=True, text=True, timeout=5,
            ).stdout.strip()
        except Exception:
            commit = "unknown"

        data_state = None
        try:
            from app.database.database import get_engine, get_session_factory
            from sqlalchemy import text
            engine = get_engine()
            factory = get_session_factory(engine)
            db = factory()
            try:
                counts = {}
                for tabla in ("servired_prices", "servired_aportes_monotributo", "servired_knowledge", "leads"):
                    try:
                        with engine.connect() as conn:
                            counts[tabla] = conn.execute(
                                text(f"SELECT COUNT(*) FROM {tabla}")
                            ).scalar()
                    except Exception:
                        counts[tabla] = None
                data_state = counts
            finally:
                db.close()

            # Self-healing: si la DB está vacía pero existe el conocimiento
            # en disco, repoblar automáticamente (evita depender del bootstrap
            # del lifespan, que puede fallar silenciosamente en Render).
            if (
                data_state is not None
                and (data_state.get("servired_prices") or 0) == 0
            ):
                from app.database.bootstrap import KNOWLEDGE_DIR, bootstrap_datos
                if KNOWLEDGE_DIR.is_dir():
                    logger.warning(
                        "[HEALTH] DB vacía pero knowledge existe en disco — "
                        "repoblando automáticamente"
                    )
                    db2 = factory()
                    try:
                        estado = bootstrap_datos(db2)
                        logger.info(
                            "[HEALTH] Self-healing bootstrap: %s",
                            {k: v for k, v in estado.items()},
                        )
                        mapeo = {
                            "precios": "servired_prices",
                            "aportes": "servired_aportes_monotributo",
                            "knowledge": "servired_knowledge",
                        }
                        for k, v in estado.items():
                            tabla = mapeo.get(k, k)
                            if tabla in data_state:
                                data_state[tabla] = v
                    except Exception as exc:
                        logger.error("[HEALTH] Self-healing bootstrap falló: %s", exc)
                    finally:
                        db2.close()
        except Exception:
            data_state = None

        knowledge_dir = None
        knowledge_state = None
        try:
            from app.database.bootstrap import KNOWLEDGE_DIR
            knowledge_dir = str(KNOWLEDGE_DIR.resolve())
            knowledge_state = {
                "exists": KNOWLEDGE_DIR.is_dir(),
                "archivos": sorted(
                    str(p.relative_to(KNOWLEDGE_DIR))
                    for p in KNOWLEDGE_DIR.rglob("*") if p.is_file()
                ) if KNOWLEDGE_DIR.is_dir() else [],
            }
        except Exception:
            pass

        engine_url = None
        try:
            from app.database.database import get_engine
            raw = str(get_engine().url)
            if "@" in raw:
                engine_url = raw.split("@")[0].split("://")[0] + "://***@" + raw.split("@")[-1]
            else:
                engine_url = raw
        except Exception:
            engine_url = None

        warnings = []
        if engine_url and "sqlite" in engine_url:
            warnings.append(
                "DB SQLite efímera: los datos se pierden en cada deploy. "
                "Configurá DATABASE_URL (PostgreSQL) en el dashboard de Render."
            )

        return JSONResponse({
            "status": "ok",
            "service": "sofia",
            "version": "1.0.0",
            "commit": commit,
            "telegram_bot": telegram_status,
            "data": data_state,
            "knowledge_dir": knowledge_dir,
            "knowledge_state": knowledge_state,
            "engine_url": engine_url,
            "warnings": warnings,
        })

    # Bootstrap manual: fuerza la importación de datos
    @app.get("/bootstrap")
    async def bootstrap():
        from app.database.database import get_engine, get_session_factory
        engine = get_engine()
        factory = get_session_factory(engine)
        db = factory()
        try:
            from app.database.bootstrap import bootstrap_datos
            estado = bootstrap_datos(db)
            return JSONResponse({"status": "ok", "data": estado})
        except Exception as exc:
            return JSONResponse({"status": "error", "error": str(exc)}, status_code=500)
        finally:
            db.close()

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
