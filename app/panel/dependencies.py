"""
Dependencias para el panel comercial.

Proporciona sesiones de base de datos y configuración
para las rutas del panel web.
"""

from __future__ import annotations

from typing import Generator

from sqlalchemy.orm import Session

from app.database.database import get_engine, get_session_factory, crear_tablas


_panel_db_factory = None


def init_panel_db(database_url: str) -> None:
    """
    Inicializa la conexión a la DB para el panel.

    Args:
        database_url: URL de la base de datos.
    """
    global _panel_db_factory
    engine = get_engine(database_url)
    crear_tablas(engine)
    _panel_db_factory = get_session_factory(engine)


def get_panel_db() -> Generator[Session, None, None]:
    """
    Dependency que provee una sesión de DB.

    Reutiliza el engine global (creado por el lifespan de app.server)
    en vez de crear uno propio, para no sobreescribir el engine
    PostgreSQL de producción con SQLite.

    Yields:
        Sesión de SQLAlchemy.
    """
    global _panel_db_factory
    if _panel_db_factory is None:
        _panel_db_factory = get_session_factory(get_engine())
    db = _panel_db_factory()
    try:
        yield db
    finally:
        db.close()
