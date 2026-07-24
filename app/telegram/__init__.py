"""
Módulo Telegram — Conexión con la API de Telegram.

Uso:
    from app.telegram import TelegramBot
    from app.config import BotConfig

    config = BotConfig.from_env()
    bot = TelegramBot(config)
    bot.run()
"""

from app.telegram.bot import TelegramBot

__all__ = ["TelegramBot"]
