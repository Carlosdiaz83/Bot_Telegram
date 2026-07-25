"""
Clase principal del bot de Telegram.

Encapsula la configuración, registro de handlers y ciclo de vida
de la aplicación de python-telegram-bot.

Incluye: manejo de errores, reconexión automática,
logs estructurados y apagado seguro.
"""

from __future__ import annotations

import logging
import signal
import sys
import threading

from telegram.ext import Application, CommandHandler, MessageHandler, filters

from app.config.settings import BotConfig
from app.telegram.handlers import handle_message, handle_start

logger = logging.getLogger(__name__)


class TelegramBot:
    """
    Orquesta el ciclo de vida del bot de Telegram.

    Responsibilities:
        - Construir la Application de python-telegram-bot.
        - Registrar handlers.
        - Manejar errores y reconexión.
        - Apagado seguro.
    """

    def __init__(self, config: BotConfig) -> None:
        self._config = config
        self._application: Application | None = None
        self._shutdown_requested = False

    def _build_application(self) -> Application:
        """Construye la Application con manejo de errores."""
        logger.info("Construyendo Application de Telegram...")

        application = (
            Application.builder()
            .token(self._config.telegram_token)
            .build()
        )

        application.add_error_handler(self._handle_error)

        logger.info("Application construida correctamente")
        return application

    def _register_handlers(self, application: Application) -> None:
        """Registra todos los handlers en la aplicación."""
        application.add_handler(CommandHandler("start", handle_start))
        application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
        )
        logger.info("Handlers registrados correctamente")

    async def _handle_error(self, update: object, context: object) -> None:
        """Handler global de errores de Telegram."""
        logger.error("Error en handler de Telegram: %s", context, exc_info=True)

    def _setup_signal_handlers(self) -> None:
        """
        Configura handlers de señales SOLO si estamos en el main thread.

        En un hilo secundario (ej: Render), signal.signal() lanza ValueError.
        """
        if threading.current_thread() is not threading.main_thread():
            logger.info(
                "Omitiendo signal handlers (thread=%s, no es main thread)",
                threading.current_thread().name,
            )
            return

        def _signal_handler(signum, frame):
            logger.info("Señal %d recibida, iniciando apagado seguro...", signum)
            self._shutdown_requested = True

        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)
        logger.info("Signal handlers configurados")

    def run(self) -> None:
        """
        Construye la aplicación, registra handlers e inicia polling.

        Seguro para ejecutar en main thread o en un hilo secundario.
        """
        logger.info(
            "=== TelegramBot.run() iniciado (thread=%s, main=%s) ===",
            threading.current_thread().name,
            threading.current_thread() is threading.main_thread(),
        )

        self._setup_signal_handlers()

        logger.info("Construyendo Application...")
        self._application = self._build_application()

        logger.info("Registrando handlers...")
        self._register_handlers(self._application)

        logger.info(
            "Iniciando polling (env=%s, debug=%s)...",
            self._config.app_env,
            self._config.app_debug,
        )

        try:
            self._application.run_polling(
                drop_pending_updates=True,
                allowed_updates=["message", "callback_query"],
            )
            logger.info("run_polling() finalizó normalmente")
        except Exception as e:
            logger.error(
                "Error en run_polling: %s", str(e), exc_info=True,
            )
            # NO usar sys.exit() aquí — en un thread eso mata el thread
            # silenciosamente sin终止ar la app principal.
        finally:
            logger.info("TelegramBot.run() completado")
