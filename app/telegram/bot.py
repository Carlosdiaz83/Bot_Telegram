"""
Clase principal del bot de Telegram.

Encapsula la configuración, registro de handlers y ciclo de vida
de la aplicación de python-telegram-bot.
"""

from __future__ import annotations

import logging

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
        - Iniciar polling.

    Uso:
        config = BotConfig.from_env()
        bot = TelegramBot(config)
        bot.run()
    """

    def __init__(self, config: BotConfig) -> None:
        """
        Inicializa el bot con la configuración provista.

        Args:
            config: Configuración inmutable del bot.
        """
        self._config = config
        self._application: Application | None = None

    def _build_application(self) -> Application:
        """Construye la Application de python-telegram-bot."""
        logger.info("Construyendo Application de Telegram...")
        application = Application.builder().token(self._config.telegram_token).build()
        return application

    def _register_handlers(self, application: Application) -> None:
        """Registra todos los handlers en la aplicación."""
        # Comando /start — reinicia sesión
        application.add_handler(CommandHandler("start", handle_start))

        # Mensajes de texto — flujo comercial
        application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
        )
        logger.info("Handlers registrados correctamente")

    def run(self) -> None:
        """
        Construye la aplicación, registra handlers e inicia polling.

        Este método bloquea la ejecución hasta que el bot se detenga.
        """
        self._application = self._build_application()
        self._register_handlers(self._application)

        logger.info("Iniciando polling de Telegram...")
        self._application.run_polling(
            drop_pending_updates=True,
        )
