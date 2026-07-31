"""
Configuración de base de datos con SQLAlchemy.

Diseñado para SQLite en desarrollo y PostgreSQL en producción (Render).

Uso:
    from app.database.database import get_engine, crear_tablas
    engine = get_engine("sqlite:///./health_advisor.db")
    crear_tablas(engine)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

logger = logging.getLogger(__name__)

_engine: Optional[Engine] = None
_SessionLocal: Optional[sessionmaker] = None


def _is_postgres(url: str) -> bool:
    """Detecta si la URL es de PostgreSQL."""
    return url.startswith("postgresql") or url.startswith("postgres")


def get_engine(database_url: Optional[str] = None) -> Engine:
    """
    Retorna o crea el engine de base de datos.

    Si ya existe un engine global y no se provee URL, devuelve el existente.
    Si se provee una URL distinta a la del engine actual, usa la nueva URL
    (crea el engine correspondiente y lo deja como global).

    Args:
        database_url: URL de conexión. Si no se provee, usa SQLite local.

    Returns:
        Engine de SQLAlchemy.
    """
    global _engine

    if _engine is not None and database_url is None:
        return _engine

    if database_url is None:
        db_path = Path(__file__).parent.parent.parent / "health_advisor.db"
        database_url = f"sqlite:///{db_path}"

    if _engine is not None and _engine.url == database_url:
        return _engine

    # Configuración específica para PostgreSQL
    kwargs: dict = {
        "echo": False,
        "pool_pre_ping": True,
    }

    if _is_postgres(database_url):
        kwargs["pool_size"] = 5
        kwargs["max_overflow"] = 10
        kwargs["pool_timeout"] = 30
        kwargs["pool_recycle"] = 1800

    _engine = create_engine(database_url, **kwargs)

    safe_url = database_url.split("@")[-1] if "@" in database_url else database_url
    logger.info("Engine de DB creado: %s", safe_url)
    return _engine


def get_session_factory(engine: Optional[Engine] = None) -> sessionmaker:
    """
    Crea una sessionmaker para el engine dado.

    Args:
        engine: Engine de SQLAlchemy. Si no se provee, usa get_engine().

    Returns:
        sessionmaker configurado.
    """
    global _SessionLocal

    if _SessionLocal is not None and engine is None:
        return _SessionLocal

    if engine is None:
        engine = get_engine()

    _SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    return _SessionLocal


def get_db() -> Session:
    """
    Dependencia para obtener una sesión de DB.

    Yields:
        Sesión de SQLAlchemy.
    """
    factory = get_session_factory()
    db = factory()
    try:
        yield db
    finally:
        db.close()


def crear_tablas(engine: Optional[Engine] = None) -> None:
    """
    Crea todas las tablas definidas en los modelos ORM.

    Args:
        engine: Engine de SQLAlchemy. Si no se provee, usa get_engine().
    """
    from app.database.models import Base

    if engine is None:
        engine = get_engine()

    Base.metadata.create_all(bind=engine)
    logger.info("Tablas de DB creadas/verificadas")


def cerrar_engine() -> None:
    """Cierra el engine y limpia variables globales."""
    global _engine, _SessionLocal

    if _engine is not None:
        _engine.dispose()
        _engine = None
        _SessionLocal = None
        logger.info("Engine de DB cerrado")
