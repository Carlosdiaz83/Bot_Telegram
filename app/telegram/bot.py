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

from telegram import Update
from telegram.ext import (
    Application,
    ChatMemberHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from app.config.settings import BotConfig
from app.telegram.group_listener import GroupListener
from app.telegram.handlers import (
    handle_document,
    handle_message,
    handle_photo,
    handle_start,
)

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
        # Escucha de grupos: detecta alta/baja del bot y mensajes relevantes.
        # Debe registrarse ANTES del handler genérico para que los mensajes
        # de grupo no entren al flujo privado.
        listener = GroupListener()
        application.add_handler(
            ChatMemberHandler(
                listener.handle_my_chat_member,
                chat_member_types=ChatMemberHandler.MY_CHAT_MEMBER,
            )
        )
        application.add_handler(
            MessageHandler(
                filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND,
                listener.handle_group_message,
            )
        )

        application.add_handler(CommandHandler("start", handle_start))
        application.add_handler(
            MessageHandler(
                filters.Document.ALL & ~filters.COMMAND, handle_document
            )
        )
        application.add_handler(
            MessageHandler(filters.PHOTO, handle_photo)
        )
        application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
        )
        logger.info("Handlers registrados correctamente")

    async def _handle_error(self, update: object, context: object) -> None:
        """Handler global de errores de Telegram."""
        logger.error("Error en handler de Telegram", exc_info=context.error)

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

    @staticmethod
    def _is_main_thread() -> bool:
        """Verifica si el thread actual es el main thread."""
        return threading.current_thread() is threading.main_thread()

    def run(self) -> None:
        """
        Construye la aplicación, registra handlers e inicia polling.

        Seguro para ejecutar en main thread o en un hilo secundario.
        """
        is_main = self._is_main_thread()

        logger.info(
            "=== TelegramBot.run() iniciado (thread=%s, main=%s) ===",
            threading.current_thread().name,
            is_main,
        )

        # 1. Nuestros propios signal handlers (solo en main thread)
        self._setup_signal_handlers()

        # 2. Limpiar conexión previa (evita Conflict error por instancia duplicada)
        logger.info("[TELEGRAM] Limpiando conexión previa (deleteWebhook)...")
        try:
            import urllib.request as ureq
            import json
            url = f"https://api.telegram.org/bot{self._config.telegram_token}/deleteWebhook?drop_pending_updates=true"
            with ureq.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read())
                logger.info("[TELEGRAM] deleteWebhook: %s", data.get("description", "ok"))
        except Exception as e:
            logger.warning("[TELEGRAM] deleteWebhook falló (no crítico): %s", e)

        # Limpiar sesión de polling previa (completa cualquier long-poll pendiente)
        logger.info("[TELEGRAM] Limpiando sesión polling previa (getUpdates)...")
        try:
            url = f"https://api.telegram.org/bot{self._config.telegram_token}/getUpdates?offset=-1&timeout=1"
            with ureq.urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read())
                logger.info("[TELEGRAM] getUpdates: %d updates", len(data.get("result", [])))
        except Exception as e:
            logger.warning("[TELEGRAM] getUpdates falló (no crítico): %s", e)

        # 3. Construir Application
        logger.info("Construyendo Application...")
        self._application = self._build_application()

        # 4. Registrar handlers
        logger.info("Registrando handlers...")
        self._register_handlers(self._application)

        # 5. Configurar stop_signals para run_polling()
        # IMPORTANTE: En Linux (Render), run_polling() intenta registrar
        # signal handlers via loop.add_signal_handler(). Si estamos en un
        # thread secundario, esto lanza ValueError.
        # Solución: pasar stop_signals=None para desactivar esa función.
        if is_main:
            stop_signals = None  # Usar defaults de la librería
        else:
            stop_signals = None  # Desactivar signal handlers de la librería
            logger.info(
                "[TELEGRAM] Signal handlers de run_polling desactivados "
                "(thread secundario)"
            )

        logger.info(
            "Iniciando polling (env=%s, debug=%s, stop_signals=%s)...",
            self._config.app_env,
            self._config.app_debug,
            "defaults" if is_main else "disabled",
        )

        try:
            self._application.run_polling(
                drop_pending_updates=True,
                allowed_updates=["message", "callback_query", "my_chat_member"],
                stop_signals=stop_signals,
            )
            logger.info("run_polling() finalizó normalmente")
        except Exception as e:
            logger.error(
                "Error en run_polling: %s", str(e), exc_info=True,
            )
        finally:
            logger.info("TelegramBot.run() completado")

    async def start_webhook(self) -> None:
        """
        Inicializa la aplicación y registra el webhook en Telegram.

        Debe ejecutarse dentro del event loop de FastAPI (lifespan).
        Tras esto, los updates llegan por HTTP POST al endpoint /webhook.
        """
        self._application = self._build_application()
        self._register_handlers(self._application)
        await self._application.initialize()

        if self._config.webhook_base_url:
            webhook_url = (
                f"{self._config.webhook_base_url}/webhook/{self._config.telegram_token}"
            )
            await self._application.bot.set_webhook(
                url=webhook_url,
                allowed_updates=["message", "callback_query", "my_chat_member"],
            )
            logger.info("[TELEGRAM] Webhook registrado: %s", webhook_url)
        else:
            logger.info("[TELEGRAM] Sin webhook_base_url; esperando updates manualmente")

    async def process_update(self, update: Update) -> None:
        """Procesa un update recibido por webhook."""
        if self._application is None:
            raise RuntimeError("TelegramBot no inicializado para webhook")
        await self._application.process_update(update)

    async def process_update_payload(self, payload: dict) -> None:
        """Decodifica un payload JSON de Telegram y lo procesa."""
        if self._application is None:
            raise RuntimeError("TelegramBot no inicializado para webhook")
        update = Update.de_json(payload, self._application.bot)
        await self.process_update(update)

    async def stop_webhook(self) -> None:
        """Cierra la aplicación (shutdown) al apagar el servidor."""
        if self._application is not None:
            await self._application.shutdown()
            self._application = None
            logger.info("[TELEGRAM] Webhook application cerrada")
