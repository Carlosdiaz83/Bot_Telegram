"""
CLI para ingestar documentos en la base de conocimiento SERVIRED.

Uso:
    python -m app.services.document_ingester <carpeta>

Ejemplo:
    python -m app.services.document_ingester servired_knowledge/

Procesa archivos .md, .txt, .pdf, .xlsx de la carpeta indicada
y los guarda en ServiredKnowledgeDB.
"""

from __future__ import annotations

import sys
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def main() -> int:
    if len(sys.argv) < 2:
        print("Uso: python -m app.services.document_ingester <carpeta>")
        print()
        print("Ejemplo:")
        print("  python -m app.services.document_ingester servired_knowledge/")
        return 1

    carpeta = sys.argv[1]

    import os
    from app.database.database import get_engine, get_session_factory
    from app.services.knowledge_engine import KnowledgeEngine
    from app.services.document_ingester import DocumentIngester

    logger.info("Conectando a la base de datos...")
    database_url = os.environ.get("DATABASE_URL")
    engine = get_engine(database_url)
    SessionLocal = get_session_factory(engine)
    db = SessionLocal()

    try:
        engine = KnowledgeEngine(db)
        ingester = DocumentIngester(engine)

        logger.info("Carpeta a procesar: %s", carpeta)
        stats = ingester.ingestir_carpeta(carpeta)

        print()
        print("=" * 50)
        print(f"  Documentos procesados: {stats['archivos_ok']}")
        print(f"  Errores:               {stats['archivos_err']}")
        print(f"  IDs creados:           {stats['ids']}")
        print("=" * 50)

        total = engine._repo.activos()
        print(f"  Total registros en DB: {len(total)}")
        return 0 if stats["archivos_err"] == 0 else 1

    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
