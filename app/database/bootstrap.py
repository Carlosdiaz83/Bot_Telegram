"""
Bootstrap de datos iniciales.

Ejecutado en el arranque de la aplicación. Verifica que la base
de datos tenga los datos esenciales (precios, aportes, knowledge)
y los importa desde los archivos de servired_knowledge/ si faltan.

Garantiza que el bot siempre pueda cotizar aunque el preDeployCommand
de Render no se haya ejecutado.
"""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent.parent / "servired_knowledge"

PRECIOS_GLOB = "precios/*.xls*"
APORTES_GLOB = "aportes/*.xlsx*"


def _tabla_vacia(db: Session, tabla: str) -> bool:
    """Retorna True si la tabla no tiene registros."""
    from sqlalchemy import text
    from sqlalchemy.engine import Engine

    engine: Engine = db.get_bind()
    try:
        with engine.connect() as conn:
            count = conn.execute(text(f"SELECT COUNT(*) FROM {tabla}")).scalar()
        return count == 0
    except Exception as exc:
        logger.warning("[BOOTSTRAP] No se pudo contar tabla %s: %s", tabla, exc)
        return False


def _importar_precios(db: Session) -> int:
    """Importa el primer archivo de precios encontrado."""
    from app.services.price_importer import importar_precios

    archivos = sorted(KNOWLEDGE_DIR.glob(PRECIOS_GLOB))
    if not archivos:
        logger.warning("[BOOTSTRAP] No se encontraron archivos de precios en %s", KNOWLEDGE_DIR)
        return 0

    ruta = archivos[0]
    resultado = importar_precios(ruta, db)
    logger.info(
        "[BOOTSTRAP] Precios importados de %s: %s",
        ruta.name, resultado.resumen(),
    )
    return resultado.precios_totales


def _importar_aportes(db: Session) -> int:
    """Importa el primer archivo de aportes monotributo encontrado."""
    from app.services.aportes_importer import importar_aportes

    archivos = sorted(KNOWLEDGE_DIR.glob(APORTES_GLOB))
    if not archivos:
        logger.warning("[BOOTSTRAP] No se encontraron archivos de aportes en %s", KNOWLEDGE_DIR)
        return 0

    ruta = archivos[0]
    resultado = importar_aportes(ruta, db)
    logger.info(
        "[BOOTSTRAP] Aportes importados de %s: %s",
        ruta.name, resultado.resumen(),
    )
    return resultado.registros_totales


def _ingestar_knowledge(db: Session) -> int:
    """Ingesta documentos de servired_knowledge/ como knowledge."""
    from app.services.document_ingester import DocumentIngester
    from app.services.knowledge_engine import KnowledgeEngine

    if not KNOWLEDGE_DIR.is_dir():
        logger.warning("[BOOTSTRAP] Carpeta knowledge no encontrada: %s", KNOWLEDGE_DIR)
        return 0

    ingester = DocumentIngester(KnowledgeEngine(db))
    stats = ingester.ingestir_carpeta(KNOWLEDGE_DIR)
    logger.info(
        "[BOOTSTRAP] Knowledge ingestado: %d OK, %d errores",
        stats["archivos_ok"], stats["archivos_err"],
    )
    return stats["archivos_ok"]


def bootstrap_datos(db: Session) -> dict:
    """
    Verifica y completa los datos esenciales de la DB.

    Importa precios/aportes/knowledge solo si las tablas están vacías.

    Returns:
        Dict con el estado resultante: {precios, aportes, knowledge}.
    """
    from app.database.repository import AportesMonotributoRepository, PriceRepository

    estado: dict = {"precios": 0, "aportes": 0, "knowledge": 0}

    try:
        if _tabla_vacia(db, "servired_prices"):
            estado["precios"] = _importar_precios(db)
        else:
            estado["precios"] = len(PriceRepository(db).buscar_todos())
            logger.info("[BOOTSTRAP] Tabla de precios ya poblada (%d)", estado["precios"])
    except Exception as exc:
        logger.error("[BOOTSTRAP] Error importando precios: %s", exc)

    try:
        if _tabla_vacia(db, "servired_aportes_monotributo"):
            estado["aportes"] = _importar_aportes(db)
        else:
            estado["aportes"] = len(AportesMonotributoRepository(db).buscar_todos())
            logger.info("[BOOTSTRAP] Tabla de aportes ya poblada (%d)", estado["aportes"])
    except Exception as exc:
        logger.error("[BOOTSTRAP] Error importando aportes: %s", exc)

    try:
        if _tabla_vacia(db, "servired_knowledge"):
            estado["knowledge"] = _ingestar_knowledge(db)
        else:
            from app.database.repository import KnowledgeRepository
            estado["knowledge"] = len(KnowledgeRepository(db).activos())
            logger.info("[BOOTSTRAP] Knowledge ya poblado (%d)", estado["knowledge"])
    except Exception as exc:
        logger.error("[BOOTSTRAP] Error ingestando knowledge: %s", exc)

    logger.info(
        "[BOOTSTRAP] Estado final — precios=%d, aportes=%d, knowledge=%d",
        estado["precios"], estado["aportes"], estado["knowledge"],
    )
    return estado
