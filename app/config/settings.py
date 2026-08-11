"""
Configuración centralizada de la aplicación.

Lee las variables de entorno desde .env y las expone
a través de la dataclass BotConfig.

Patrón: Singleton por módulo (la instancia se crea al importar).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


def _parse_group_ids(valor: str) -> tuple[int, ...]:
    """Parsea una lista de chat_id de grupos separados por comas."""
    ids: list[int] = []
    for parte in valor.split(","):
        parte = parte.strip()
        if parte.lstrip("-").isdigit():
            ids.append(int(parte))
    return tuple(ids)


def _parse_horarios(valor: str) -> tuple[str, ...]:
    """Parsea horarios 'HH:MM' separados por comas, ordenados."""
    horarios: set[str] = set()
    for parte in valor.split(","):
        parte = parte.strip()
        if len(parte) == 5 and parte[2] == ":":
            horarios.add(parte)
    return tuple(sorted(horarios))


@dataclass(frozen=True)
class BotConfig:
    """
    Configuración inmutable del bot de Telegram.

    Attributes:
        telegram_token: Token del bot de Telegram (obtenido de @BotFather).
        groq_api_key: API key de Groq (para IA conversacional).
        ai_model: Modelo de LLM a utilizar.
        database_url: URL de conexión a la base de datos.
        app_env: Entorno de ejecución (development, production).
        app_debug: Si True, habilita logging detallado.
        log_level: Nivel de logging (DEBUG, INFO, WARNING, ERROR).
    """

    telegram_token: str
    groq_api_key: str = ""
    ai_model: str = "llama-3.3-70b-versatile"
    database_url: str = "sqlite:///./health_advisor.db"
    app_env: str = "development"
    app_debug: bool = False
    log_level: str = "INFO"
    telegram_webhook: bool = False
    webhook_base_url: str = ""
    # Grupos de Telegram donde el bot publica ganchos y escucha conversaciones.
    telegram_group_chat_ids: tuple[int, ...] = ()
    # Ganchos automáticos 4 veces al día en los grupos (08:30/13:00/18:30/21:30
    # hora de Córdoba). Desactivar con TELEGRAM_GROUP_HOOKS=false.
    grupo_hooks_habilitado: bool = True
    grupo_hooks_horarios: tuple[str, ...] = ("08:30", "13:00", "18:30", "21:30")
    # Mensaje de invitación "Agregame a tu grupo" 2 veces al día.
    # Desactivar con TELEGRAM_GROUP_INVITE=false.
    grupo_invite_habilitado: bool = True
    grupo_invite_horarios: tuple[str, ...] = ("12:00", "20:00")

    @classmethod
    def from_env(cls, env_path: Path | None = None) -> BotConfig:
        """
        Crea una instancia de BotConfig leyendo variables de entorno.

        Args:
            env_path: Ruta opcional al archivo .env.
                      Si no se provee, busca en el directorio raíz del proyecto.

        Returns:
            Instancia de BotConfig con los valores leídos.

        Raises:
            ValueError: Si TELEGRAM_BOT_TOKEN no está definido.
        """
        if env_path is None:
            env_path = Path(__file__).resolve().parent.parent.parent / ".env"

        load_dotenv(env_path)

        telegram_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        if not telegram_token:
            raise ValueError(
                "TELEGRAM_BOT_TOKEN no está definido. "
                "Copiá .env.example como .env y completá el token de @BotFather."
            )

        return cls(
            telegram_token=telegram_token,
            groq_api_key=os.getenv("GROQ_API_KEY", ""),
            ai_model=os.getenv("AI_MODEL", "llama-3.3-70b-versatile"),
            database_url=os.getenv("DATABASE_URL", "sqlite:///./health_advisor.db"),
            app_env=os.getenv("APP_ENV", "development"),
            app_debug=os.getenv("APP_DEBUG", "false").lower() in ("true", "1", "yes"),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
        telegram_webhook=os.getenv(
            "TELEGRAM_WEBHOOK", "false"
        ).lower() in ("true", "1", "yes"),
        webhook_base_url=os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/"),
        telegram_group_chat_ids=_parse_group_ids(os.getenv("TELEGRAM_GROUP_CHAT_IDS", "")),
        grupo_hooks_habilitado=os.getenv(
            "TELEGRAM_GROUP_HOOKS", "true"
        ).lower() in ("true", "1", "yes"),
        grupo_hooks_horarios=_parse_horarios(
            os.getenv("TELEGRAM_GROUP_HOOK_HORARIOS", "08:30,13:00,18:30,21:30")
        ),
        grupo_invite_habilitado=os.getenv(
            "TELEGRAM_GROUP_INVITE", "true"
        ).lower() in ("true", "1", "yes"),
        grupo_invite_horarios=_parse_horarios(
            os.getenv("TELEGRAM_GROUP_INVITE_HORARIOS", "12:00,20:00")
        ),
    )
