"""
Migraciones manuales para el esquema de base de datos.

SQLAlchemy create_all() solo crea tablas nuevas, nunca agrega columnas
a tablas existentes. Este módulo ejecuta ALTER TABLEs necesarios para
mantener el esquema al día.

Uso:
    python -m app.database.migrations
    # o
    from app.database.migrations import ejecutar_migraciones
    ejecutar_migraciones(engine)
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import Engine, inspect, text

logger = logging.getLogger(__name__)


def _columna_existe(engine: Engine, tabla: str, columna: str) -> bool:
    """Verifica si una columna existe en una tabla."""
    inspector = inspect(engine)
    try:
        columnas = [c["name"] for c in inspector.get_columns(tabla)]
        return columna in columnas
    except Exception:
        return False


def _agregar_columna_si_falta(engine: Engine, tabla: str, columna: str, tipo_sql: str) -> bool:
    """
    Agrega una columna si no existe. Retorna True si se agregó.

    Args:
        engine: Engine SQLAlchemy.
        tabla: Nombre de la tabla.
        columna: Nombre de la columna.
        tipo_sql: Tipo SQL (ej: "VARCHAR(5)", "INTEGER", "BOOLEAN DEFAULT FALSE").
    """
    if _columna_existe(engine, tabla, columna):
        logger.debug("Columna %s.%s ya existe — omitiendo", tabla, columna)
        return False

    sql = f"ALTER TABLE {tabla} ADD COLUMN {columna} {tipo_sql}"
    logger.info("[MIGRATION] Ejecutando: %s", sql)

    with engine.connect() as conn:
        conn.execute(text(sql))
        conn.commit()

    logger.info("[MIGRATION] Columna %s.%s agregada exitosamente", tabla, columna)
    return True


def ejecutar_migraciones(engine: Optional[Engine] = None) -> None:
    """
    Ejecuta todas las migraciones pendientes del esquema.

    Seguro de ejecutar múltiples veces (idempotente).

    Args:
        engine: Engine SQLAlchemy. Si no se provee, usa get_engine().
    """
    if engine is None:
        from app.database.database import get_engine
        engine = get_engine()

    logger.info("[MIGRATION] Verificando migraciones pendientes...")

    migraciones_aplicadas = 0

    # --- Migraciones conocidas ---
    if _agregar_columna_si_falta(engine, "leads", "categoria_monotributo", "VARCHAR(5)"):
        migraciones_aplicadas += 1

    if migraciones_aplicadas > 0:
        logger.info("[MIGRATION] %d migración(es) aplicada(s)", migraciones_aplicadas)
    else:
        logger.info("[MIGRATION] Esquema al día — nada que migrar")


if __name__ == "__main__":
    import os
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    try:
        from app.database.database import get_engine, crear_tablas
        database_url = os.environ.get("DATABASE_URL")
        engine = get_engine(database_url)
        # Importante: crear tablas ANTES de migrar. En una DB nueva
        # (primer deploy en Render) las tablas no existen y el ALTER falla.
        crear_tablas(engine)
        ejecutar_migraciones(engine)
        print("Migraciones completadas.")
    except Exception as e:
        print(f"Error en migración: {e}", file=sys.stderr)
        sys.exit(1)
