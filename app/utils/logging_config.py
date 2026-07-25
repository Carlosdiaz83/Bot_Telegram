"""
Configuración de logging para la aplicación.

Configura un formato consistente con timestamp, nivel, nombre del módulo y mensaje.
Los logs se envían a consola y opcionalmente a archivo.
Incluye soporte para producción con logs estructurados.
"""

from __future__ import annotations

import logging
import sys
import json
from datetime import datetime, timezone
from pathlib import Path


class StructuredFormatter(logging.Formatter):
    """Formatter que produce logs en formato JSON estructurado para producción."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry, ensure_ascii=False)


def setup_logging(
    level: str = "INFO",
    log_to_file: bool = False,
    log_dir: Path | None = None,
    structured: bool = False,
) -> None:
    """
    Configura el sistema de logging de la aplicación.

    Args:
        level: Nivel de logging (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        log_to_file: Si True, también escribe logs a archivo.
        log_dir: Directorio donde guardar los archivos de log.
        structured: Si True, usa formato JSON (recomendado en producción).
    """
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    if structured:
        formatter = StructuredFormatter()
    else:
        formatter = logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(numeric_level)

    handlers: list[logging.Handler] = [console_handler]

    if log_to_file:
        if log_dir is None:
            log_dir = Path(__file__).resolve().parent.parent.parent / "logs"

        log_dir.mkdir(exist_ok=True)
        log_file = log_dir / "health_advisor.log"

        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        file_handler.setLevel(numeric_level)
        handlers.append(file_handler)

    logging.basicConfig(
        level=numeric_level,
        handlers=handlers,
        force=True,
    )

    # Silenciar librerías verbosas
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)

    logger = logging.getLogger(__name__)
    logger.info("Logging configurado (nivel=%s, structured=%s)", level, structured)
