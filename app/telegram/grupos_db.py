"""
Persistencia de grupos de Telegram donde Sofía está presente.

Los grupos se registran automáticamente cuando el bot es agregado
(update my_chat_member) y se desactivan cuando es removido. Los ganchos
automáticos y la escucha de conversaciones se limitan a estos grupos.

La tabla `grupos_telegram` se combina con la lista estática
TELEGRAM_GROUP_CHAT_IDS definida en el entorno.

Uso:
    from app.telegram.grupos_db import (
        registrar_grupo, desactivar_grupo, listar_grupos_activos,
    )
    registrar_grupo(-1001234567890, "Vecinos de Nueva Córdoba")
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.orm import Session, sessionmaker

logger = logging.getLogger(__name__)

_factory_cache: Optional[sessionmaker] = None


def _crear_factory() -> sessionmaker:
    """Crea la session factory de la aplicación (y las tablas si faltan).

    Se memoiza para no correr `crear_tablas` (DDL) en cada consulta:
    el scheduler de ganchos consulta el estado de envío cada 30s.
    """
    global _factory_cache
    if _factory_cache is None:
        from app.database.database import crear_tablas, get_engine, get_session_factory

        engine = get_engine()
        crear_tablas(engine)
        _factory_cache = get_session_factory(engine)
    return _factory_cache


def _sesion(factory: Optional[sessionmaker]) -> Session:
    """Obtiene una sesión usando la factory provista o la de la aplicación."""
    if factory is not None:
        return factory()
    return _crear_factory()()


def registrar_grupo(
    chat_id: int, titulo: str = "", factory: Optional[sessionmaker] = None
) -> bool:
    """
    Registra (o reactiva) un grupo donde el bot es miembro.

    Args:
        chat_id: ID de Telegram del grupo.
        titulo: Nombre del grupo.
        factory: Session factory (para tests).

    Returns:
        True si se registró correctamente, False si la DB no está disponible.
    """
    try:
        from sqlalchemy import select

        from app.database.models import GrupoTelegramDB

        db = _sesion(factory)
        try:
            grupo = db.execute(
                select(GrupoTelegramDB).where(GrupoTelegramDB.chat_id == chat_id)
            ).scalar_one_or_none()

            if grupo is None:
                db.add(GrupoTelegramDB(chat_id=chat_id, titulo=titulo or None, activo=True))
            else:
                grupo.activo = True
                if titulo:
                    grupo.titulo = titulo
            db.commit()
            logger.info("[GRUPOS] Grupo registrado: chat_id=%s, titulo=%s", chat_id, titulo)
            return True
        finally:
            db.close()
    except Exception as exc:
        logger.warning("[GRUPOS] No se pudo registrar grupo %s: %s", chat_id, exc)
        return False


def desactivar_grupo(chat_id: int, factory: Optional[sessionmaker] = None) -> bool:
    """Marca un grupo como inactivo (el bot fue removido)."""
    try:
        from sqlalchemy import select

        from app.database.models import GrupoTelegramDB

        db = _sesion(factory)
        try:
            grupo = db.execute(
                select(GrupoTelegramDB).where(GrupoTelegramDB.chat_id == chat_id)
            ).scalar_one_or_none()
            if grupo is not None:
                grupo.activo = False
                db.commit()
            logger.info("[GRUPOS] Grupo desactivado: chat_id=%s", chat_id)
            return True
        finally:
            db.close()
    except Exception as exc:
        logger.warning("[GRUPOS] No se pudo desactivar grupo %s: %s", chat_id, exc)
        return False


def listar_grupos_activos(factory: Optional[sessionmaker] = None) -> list[int]:
    """
    Lista los chat_ids de los grupos activos registrados en la DB.

    Args:
        factory: Session factory (para tests).

    Returns:
        Lista de chat_ids activos.
    """
    try:
        from sqlalchemy import select

        from app.database.models import GrupoTelegramDB

        db = _sesion(factory)
        try:
            filas = db.execute(
                select(GrupoTelegramDB.chat_id).where(GrupoTelegramDB.activo.is_(True))
            ).scalars().all()
            return list(filas)
        finally:
            db.close()
    except Exception as exc:
        logger.warning("[GRUPOS] No se pudieron listar grupos: %s", exc)
        return []
