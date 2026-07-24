"""
Configuración centralizada de la aplicación.

Uso:
    from app.config import BotConfig
    config = BotConfig.from_env()
"""

from app.config.settings import BotConfig

__all__ = ["BotConfig"]
