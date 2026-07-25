"""
Sofía Comercial AI — Entry Point
=================================
Punto de entrada de la aplicación.
Carga la configuración, configura logging e inicia el bot de Telegram.

Uso:
    python -m app.main
"""

from __future__ import annotations

import sys

from app.config.settings import BotConfig
from app.telegram.bot import TelegramBot
from app.utils.logging_config import setup_logging


def main() -> None:
    """Punto de entrada principal."""
    # 1. Cargar configuración desde .env
    try:
        config = BotConfig.from_env()
    except ValueError as e:
        print(f"Error de configuración: {e}", file=sys.stderr)
        sys.exit(1)

    # 2. Configurar logging
    is_production = config.app_env == "production"
    setup_logging(
        level=config.log_level,
        log_to_file=config.app_debug or is_production,
        structured=is_production,
    )

    # 3. Iniciar bot
    bot = TelegramBot(config)
    bot.run()


if __name__ == "__main__":
    main()
