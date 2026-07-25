"""
Repositorios de persistencia para Leads, Conversaciones y Entrenamientos.

Proporciona acceso a la base de datos siguiendo el patrón Repository.
Preparado para cambiar de SQLite a PostgreSQL modificando solo la URL.

Uso:
    from app.database.repository import LeadRepository, ConversationRepository, TrainingRepository
    lead_repo = LeadRepository(db)
    lead = lead_repo.buscar_por_telegram_id(123456)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import ConversationMessageDB, LeadDB
from app.models.lead import (
    EstadoComercial,
    GrupoFamiliar,
    InteresDetectado,
    Lead,
    NecesidadPrincipal,
    PrioridadCliente,
    TipoAfiliacion,
)

logger = logging.getLogger(__name__)


class LeadRepository:
    """
    Repositorio de persistencia de Leads.

    Maneja la conversión entre el modelo de dominio Lead
    y el modelo ORM LeadDB.
    """

    def __init__(self, db: Session) -> None:
        self._db = db

    def crear_lead(self, telegram_id: int) -> LeadDB:
        """
        Crea un nuevo lead en la base de datos.

        Args:
            telegram_id: ID de Telegram del usuario.

        Returns:
            LeadDB creado.
        """
        lead_db = LeadDB(telegram_id=telegram_id)
        self._db.add(lead_db)
        self._db.commit()
        self._db.refresh(lead_db)
        logger.info("Lead creado en DB: telegram_id=%s", telegram_id)
        return lead_db

    def buscar_por_telegram_id(self, telegram_id: int) -> Optional[LeadDB]:
        """
        Busca un lead por su telegram_id.

        Args:
            telegram_id: ID de Telegram del usuario.

        Returns:
            LeadDB si existe, None si no.
        """
        stmt = select(LeadDB).where(LeadDB.telegram_id == telegram_id)
        result = self._db.execute(stmt)
        return result.scalar_one_or_none()

    def actualizar_lead(self, lead_db: LeadDB) -> LeadDB:
        """
        Actualiza un lead existente.

        Args:
            lead_db: LeadDB con los campos actualizados.

        Returns:
            LeadDB actualizado.
        """
        lead_db.actualizado = datetime.now(timezone.utc)
        self._db.commit()
        self._db.refresh(lead_db)
        logger.debug("Lead actualizado en DB: telegram_id=%s", lead_db.telegram_id)
        return lead_db

    def listar_leads(
        self,
        estado: Optional[str] = None,
        limit: int = 100,
    ) -> list[LeadDB]:
        """
        Lista leads con filtros opcionales.

        Args:
            estado: Filtrar por estado comercial.
            limit: Máximo de resultados.

        Returns:
            Lista de LeadDB.
        """
        stmt = select(LeadDB)
        if estado:
            stmt = stmt.where(LeadDB.estado_comercial == estado)
        stmt = stmt.order_by(LeadDB.creado.desc()).limit(limit)
        result = self._db.execute(stmt)
        return list(result.scalars().all())

    def lead_domain_a_db(self, lead: Lead, lead_db: LeadDB) -> LeadDB:
        """
        Sincroniza un Lead de dominio hacia un LeadDB existente.

        Args:
            lead: Lead de dominio actualizado.
            lead_db: LeadDB destino.

        Returns:
            LeadDB actualizado.
        """
        lead_db.nombre = lead.nombre
        lead_db.edad = lead.edad
        lead_db.localidad = lead.localidad
        lead_db.telefono = lead.telefono
        lead_db.estado_comercial = lead.estado_comercial.value
        lead_db.interes_detectado = lead.interes_detectado.value if lead.interes_detectado else None
        lead_db.tipo_afiliacion = lead.tipo_afiliacion.value if lead.tipo_afiliacion else None
        lead_db.tiene_aportes = lead.tiene_aportes
        lead_db.tiene_recibo_sueldo = lead.tiene_recibo_sueldo
        lead_db.conyuge = lead.grupo_familiar.conyuge
        lead_db.hijos = lead.grupo_familiar.hijos
        lead_db.cantidad_hijos = lead.cantidad_hijos
        lead_db.cantidad_integrantes = lead.cantidad_integrantes
        lead_db.necesidad_principal = lead.necesidad_principal.value if lead.necesidad_principal else None
        lead_db.prioridad_cliente = lead.prioridad_cliente.value if lead.prioridad_cliente else None
        lead_db.score = lead.score
        lead_db.temperatura_lead = lead.temperatura_lead
        return self.actualizar_lead(lead_db)

    def db_a_lead_domain(self, lead_db: LeadDB) -> Lead:
        """
        Convierte un LeadDB a un Lead de dominio.

        Args:
            lead_db: LeadDB de la base de datos.

        Returns:
            Lead de dominio.
        """
        gf = GrupoFamiliar(
            titular=True,
            conyuge=lead_db.conyuge or False,
            hijos=lead_db.hijos or False,
        )
        return Lead(
            lead_id=str(lead_db.telegram_id),
            nombre=lead_db.nombre,
            edad=lead_db.edad,
            localidad=lead_db.localidad,
            telefono=lead_db.telefono,
            estado_comercial=EstadoComercial(lead_db.estado_comercial) if lead_db.estado_comercial else EstadoComercial.NUEVO,
            interes_detectado=InteresDetectado(lead_db.interes_detectado) if lead_db.interes_detectado else None,
            tipo_afiliacion=TipoAfiliacion(lead_db.tipo_afiliacion) if lead_db.tipo_afiliacion else None,
            tiene_aportes=lead_db.tiene_aportes,
            tiene_recibo_sueldo=lead_db.tiene_recibo_sueldo,
            grupo_familiar=gf,
            cantidad_hijos=lead_db.cantidad_hijos or 0,
            cantidad_integrantes=lead_db.cantidad_integrantes or 1,
            necesidad_principal=NecesidadPrincipal(lead_db.necesidad_principal) if lead_db.necesidad_principal else None,
            prioridad_cliente=PrioridadCliente(lead_db.prioridad_cliente) if lead_db.prioridad_cliente else None,
            score=lead_db.score or 0,
            temperatura_lead=lead_db.temperatura_lead or "",
        )


class ConversationRepository:
    """
    Repositorio de persistencia de mensajes de conversación.
    """

    def __init__(self, db: Session) -> None:
        self._db = db

    def guardar_mensaje(
        self,
        lead_id: int,
        mensaje_cliente: str,
        respuesta_sofia: str,
        etapa: str,
    ) -> ConversationMessageDB:
        """
        Guarda un intercambio de mensajes.

        Args:
            lead_id: ID del LeadDB asociado.
            mensaje_cliente: Mensaje del cliente.
            respuesta_sofia: Respuesta de Sofía.
            etapa: Etapa de conversación.

        Returns:
            ConversationMessageDB creado.
        """
        msg = ConversationMessageDB(
            lead_id=lead_id,
            mensaje_cliente=mensaje_cliente,
            respuesta_sofia=respuesta_sofia,
            etapa=etapa,
        )
        self._db.add(msg)
        self._db.commit()
        self._db.refresh(msg)
        return msg

    def historial_lead(self, lead_id: int, limit: int = 50) -> list[ConversationMessageDB]:
        """
        Obtiene el historial de conversación de un lead.

        Args:
            lead_id: ID del LeadDB asociado.
            limit: Máximo de mensajes.

        Returns:
            Lista de mensajes ordenados por fecha.
        """
        stmt = (
            select(ConversationMessageDB)
            .where(ConversationMessageDB.lead_id == lead_id)
            .order_by(ConversationMessageDB.creado.asc())
            .limit(limit)
        )
        result = self._db.execute(stmt)
        return list(result.scalars().all())


class TrainingRepository:
    """
    Repositorio de persistencia de sesiones de entrenamiento.

    Maneja el guardado y consulta de resultados de entrenamiento
    para analizar la evolución comercial de Sofía.
    """

    def __init__(self, db: Session) -> None:
        self._db = db

    def guardar(self, session_data: dict) -> "TrainingSessionDB":
        """
        Guarda una sesión de entrenamiento.

        Args:
            session_data: Diccionario con los datos de la sesión.

        Returns:
            TrainingSessionDB creado.
        """
        import json
        from app.database.models import TrainingSessionDB

        session_db = TrainingSessionDB(
            perfil_cliente=session_data.get("perfil", ""),
            canal_simulacion=session_data.get("canal", "simulador"),
            score_total=session_data.get("score_total", 0),
            score_descubrimiento=session_data.get("score_descubrimiento", 0),
            score_calificacion=session_data.get("score_calificacion", 0),
            score_valor=session_data.get("score_valor", 0),
            score_objeciones=session_data.get("score_objeciones", 0),
            score_cierre=session_data.get("score_cierre", 0),
            cantidad_errores=session_data.get("cantidad_errores", 0),
            errores_detectados=json.dumps(session_data.get("errores", [])),
            recomendaciones=json.dumps(session_data.get("recomendaciones", [])),
        )
        self._db.add(session_db)
        self._db.commit()
        self._db.refresh(session_db)
        logger.info(
            "Sesión de entrenamiento guardada: perfil=%s, score=%d",
            session_db.perfil_cliente,
            session_db.score_total,
        )
        return session_db

    def historial(self, limit: int = 100) -> list:
        """
        Obtiene el historial de entrenamientos.

        Args:
            limit: Máximo de resultados.

        Returns:
            Lista de TrainingSessionDB ordenados por fecha descendente.
        """
        from app.database.models import TrainingSessionDB
        stmt = (
            select(TrainingSessionDB)
            .order_by(TrainingSessionDB.creado.desc())
            .limit(limit)
        )
        result = self._db.execute(stmt)
        return list(result.scalars().all())

    def por_perfil(self, perfil: str) -> list:
        """
        Busca entrenamientos por perfil de cliente.

        Args:
            perfil: Nombre del perfil.

        Returns:
            Lista de TrainingSessionDB del perfil.
        """
        from app.database.models import TrainingSessionDB
        stmt = (
            select(TrainingSessionDB)
            .where(TrainingSessionDB.perfil_cliente == perfil)
            .order_by(TrainingSessionDB.creado.desc())
        )
        result = self._db.execute(stmt)
        return list(result.scalars().all())

    def ultimos(self, n: int = 10) -> list:
        """
        Obtiene los últimos N entrenamientos.

        Args:
            n: Cantidad de entrenamientos.

        Returns:
            Lista de TrainingSessionDB.
        """
        from app.database.models import TrainingSessionDB
        stmt = (
            select(TrainingSessionDB)
            .order_by(TrainingSessionDB.creado.desc())
            .limit(n)
        )
        result = self._db.execute(stmt)
        return list(result.scalars().all())

    def score_promedio(self) -> float:
        """
        Calcula el score promedio de todos los entrenamientos.

        Returns:
            Score promedio.
        """
        from app.database.models import TrainingSessionDB
        stmt = select(TrainingSessionDB.score_total)
        result = self._db.execute(stmt)
        scores = list(result.scalars().all())
        if not scores:
            return 0.0
        return sum(scores) / len(scores)

    def mejor_score(self) -> int:
        """
        Obtiene el mejor score registrado.

        Returns:
            Mejor score.
        """
        from app.database.models import TrainingSessionDB
        stmt = select(TrainingSessionDB.score_total)
        result = self._db.execute(stmt)
        scores = list(result.scalars().all())
        return max(scores) if scores else 0

    def peor_score(self) -> int:
        """
        Obtiene el peor score registrado.

        Returns:
            Peor score.
        """
        from app.database.models import TrainingSessionDB
        stmt = select(TrainingSessionDB.score_total)
        result = self._db.execute(stmt)
        scores = list(result.scalars().all())
        return min(scores) if scores else 0

    def errores_frecuentes(self) -> list:
        """
        Calcula los errores más frecuentes.

        Returns:
            Lista de tuples (tipo_error, cantidad) ordenada por frecuencia.
        """
        import json
        from collections import Counter
        from app.database.models import TrainingSessionDB

        stmt = select(TrainingSessionDB.errores_detectados)
        result = self._db.execute(stmt)
        errores_raw = list(result.scalars().all())

        contador: Counter = Counter()
        for errores_json in errores_raw:
            try:
                errores = json.loads(errores_json)
                if isinstance(errores, list):
                    for error in errores:
                        if isinstance(error, dict) and "tipo" in error:
                            contador[error["tipo"]] += 1
                        elif isinstance(error, str):
                            contador[error] += 1
            except (json.JSONDecodeError, TypeError):
                pass

        return contador.most_common()
