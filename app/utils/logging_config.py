"""
Configuración de logging para la aplicación.

Configura un formato consistente con timestamp, nivel, nombre del módulo y mensaje.
Los logs se envían a consola y opcionalmente a archivo.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path


def setup_logging(level: str = "INFO", log_to_file: bool = False, log_dir: Path | None = None) -> None:
    """
    Configura el sistema de logging de la aplicación.

    Args:
        level: Nivel de logging (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        log_to_file: Si True, también escribe logs a archivo.
        log_dir: Directorio donde guardar los archivos de log.
                 Se crea automáticamente si no existe.
    """
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    # Formato principal: timestamp | nivel | módulo | mensaje
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Handler de consola
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(numeric_level)

    handlers: list[logging.Handler] = [console_handler]

    # Handler de archivo (opcional)
    if log_to_file:
        if log_dir is None:
            log_dir = Path(__file__).resolve().parent.parent.parent / "logs"

        log_dir.mkdir(exist_ok=True)
        log_file = log_dir / "health_advisor.log"

        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        file_handler.setLevel(numeric_level)
        handlers.append(file_handler)

    # Configurar root logger
    logging.basicConfig(
        level=numeric_level,
        handlers=handlers,
        force=True,  # Sobreescribe configuración previa
    )

    # Silenciar librerías de terceros que son muy verbosas
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)

    logger = logging.getLogger(__name__)
    logger.info("Logging configurado correctamente (nivel: %s)", level)
