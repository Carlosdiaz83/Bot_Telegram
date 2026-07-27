"""
Orquestador del flujo de conversación comercial.

Coordina sesión, LeadQualifier, sales_strategy, objection_handler
y closing_strategy para manejar la conversación completa.

Responsabilidades:
    - Decidir etapa, preguntas, datos faltantes, avance comercial.
    - Delegar tono, empatía, redacción y persuasión a AIService.
    - Persistir estado en DB para sobrevivir reinicios.

Uso:
    from app.services.conversation_manager import ConversationManager
    manager = ConversationManager()
    respuesta = manager.procesar_mensaje(telegram_id=123, mensaje="Hola")
"""

from __future__ import annotations

import logging
from typing import Optional

from app.models.lead import (
    EstadoComercial,
    InteresDetectado,
    Lead,
    NecesidadPrincipal,
    PrioridadCliente,
    TipoAfiliacion,
)
from app.services.session_manager import (
    EtapaConversacion,
    ResultadoCierre,
    SessionManager,
    UserSession,
)
from app.services.lead_qualifier import LeadQualifierService
from app.services.sales_strategy import (
    generar_argumento,
    generar_presentacion_inicial,
    generar_pregunta_grupo_familiar,
    generar_pregunta_prioridad,
    generar_pregunta_situacion_actual,
)
from app.services.objection_handler import (
    TipoObjecion,
    analizar_mensaje,
)
from app.services.closing_strategy import (
    intentar_cierre,
    interpretar_respuesta_cierre,
    recuperar_indeciso,
)
from app.services.knowledge_service import KnowledgeService
from app.services.knowledge_engine import KnowledgeEngine
from app.services.lead_scoring import LeadScoringService
from app.ai.service import AIService
from app.database.database import get_engine, get_session_factory, crear_tablas
from app.database.repository import ConversationRepository, LeadRepository

logger = logging.getLogger(__name__)


class ConversationManager:
    """
    Orquestador del flujo de conversación comercial.

    Coordina todos los servicios para manejar la interacción
    del usuario desde el primer mensaje hasta el cierre.
    """

    def __init__(
        self,
        ai_service: Optional[AIService] = None,
        database_url: Optional[str] = None,
    ) -> None:
        self.session_manager = SessionManager()
        self.qualifier = LeadQualifierService()
        self.knowledge = KnowledgeService()
        self.scoring = LeadScoringService()
        self.ai = ai_service

        self._db_enabled = database_url is not None
        if self._db_enabled:
            engine = get_engine(database_url)
            crear_tablas(engine)
            self._db_factory = get_session_factory(engine)
            # KnowledgeEngine usa la DB para retrieval de conocimiento
            self._knowledge_engine = KnowledgeEngine(self._db_factory())
            logger.info("[DATABASE] ConversationManager con DB habilitada + KnowledgeEngine")
        else:
            self._db_factory = None
            self._knowledge_engine = None
            logger.info("[DATABASE] ConversationManager sin DB (solo memoria)")

    def procesar_mensaje(self, telegram_id: int, mensaje: str) -> str:
        """
        Procesa un mensaje del usuario y devuelve la respuesta de Sofía.

        Flujo:
            1. Obtener sesión (memoria o crear nueva).
            2. Cargar lead desde DB si existe (sobreescribe sesión).
            3. Detectar usuario returning (etapa ya avanzada).
            4. Enrutar a handler según etapa.
            5. Calcular score, persistir, loguear.
        """
        session = self.session_manager.get_or_create(telegram_id)

        if self._db_enabled:
            self._cargar_lead_desde_db(telegram_id, session)

        lead = session.lead
        es_usuario_returning = self._es_usuario_returning(session)

        if es_usuario_returning:
            logger.info(
                "[LEAD] Lead returning detectado — id=%s, nombre=%s, etapa=%s",
                telegram_id, lead.nombre, session.etapa.value,
            )

        logger.debug(
            "[CONVERSATION] Procesando — user=%s, etapa=%s, mensajes_en_etapa=%d: %s",
            telegram_id, session.etapa.value, session.mensajes_en_etapa,
            mensaje[:60],
        )

        respuesta = self._enrutar_mensaje(session, mensaje, es_usuario_returning)

        lead.score, lead.temperatura_lead = self.scoring.calcular_y_clasificar(lead)

        if self._db_enabled:
            self._guardar_lead_en_db(telegram_id, lead, session)
            self._guardar_mensaje_en_db(telegram_id, mensaje, respuesta, session)

        logger.info(
            "[SALES] user=%s, etapa=%s, estado=%s, score=%d, temp=%s",
            telegram_id, session.etapa.value,
            lead.estado_comercial.value, lead.score, lead.temperatura_lead,
        )

        return respuesta

    # ─────────────────────────────────────────
    # Enrutamiento
    # ─────────────────────────────────────────

    def _es_usuario_returning(self, session: UserSession) -> bool:
        """Detecta si el usuario ya tenía una conversación activa."""
        return (
            session.etapa != EtapaConversacion.NUEVO
            and session.lead.nombre is not None
        )

    def _enrutar_mensaje(
        self, session: UserSession, mensaje: str, es_returning: bool
    ) -> str:
        """Enruta el mensaje al handler según la etapa actual."""
        etapa = session.etapa

        if etapa == EtapaConversacion.NUEVO:
            if es_returning:
                return self._handle_returning(session, mensaje)
            return self._handle_nuevo(session, mensaje)

        if etapa == EtapaConversacion.DESCUBRIENDO_NECESIDAD:
            return self._wrap_ia(
                self._handle_descubrimiento(session, mensaje),
                session, mensaje,
            )

        if etapa == EtapaConversacion.CALIFICANDO:
            return self._wrap_ia(
                self._handle_calificacion(session, mensaje),
                session, mensaje,
            )

        if etapa == EtapaConversacion.PRESENTANDO_VALOR:
            return self._wrap_ia(
                self._handle_valor(session, mensaje),
                session, mensaje,
            )

        if etapa == EtapaConversacion.MANEJANDO_OBJECIONES:
            return self._wrap_ia(
                self._handle_objeciones(session, mensaje),
                session, mensaje,
            )

        if etapa == EtapaConversacion.INTENTANDO_CIERRE:
            return self._wrap_ia(
                self._handle_cierre(session, mensaje),
                session, mensaje,
            )

        # Etapas finales (CALIFICADO, DERIVADO)
        nombre = session.lead.nombre or ""
        return (
            f"Gracias {nombre} por tu consulta. "
            "Un asesor se comunicará pronto con vos. 😊"
        )

    # ─────────────────────────────────────────
    # Handlers por etapa
    # ─────────────────────────────────────────

    def _handle_nuevo(self, session: UserSession, mensaje: str) -> str:
        """Primer mensaje: saluda y pide nombre. NO avanza de etapa hasta tener nombre."""
        lead = session.lead
        lead.estado_comercial = EstadoComercial.CONTACTADO

        from app.services.lead_qualifier import _extraer_nombre
        nombre = _extraer_nombre(mensaje)

        if nombre:
            lead.nombre = nombre
            session.avanzar_etapa(EtapaConversacion.DESCUBRIENDO_NECESIDAD)
            logger.info(
                "[LEAD] Lead nuevo — id=%s, nombre=%s",
                session.telegram_id, nombre,
            )
            return (
                f"¡Hola {nombre}! Soy Sofía 😊, asesora de Servired. "
                "Te voy a ayudar a encontrar la opción más conveniente para vos. "
                f"Decime {nombre}, ¿la cobertura sería para vos o tu familia?"
            )

        # Sin nombre → quedarse en NUEVO y pedir nombre
        logger.debug("[LEAD] Esperando nombre de user=%s", session.telegram_id)
        return (
            "¡Hola! Soy Sofía 😊, asesora de Servired. "
            "Te voy a ayudar a encontrar la opción más conveniente para vos. "
            "¿Cómo te llamás?"
        )

    def _handle_returning(self, session: UserSession, mensaje: str) -> str:
        """Maneja usuario que vuelve después de un reinicio."""
        lead = session.lead
        nombre = lead.nombre

        logger.info(
            "[LEAD] Retomando conversación — user=%s, nombre=%s, etapa=%s",
            session.telegram_id, nombre, session.etapa.value,
        )

        # Re-enrutar a la etapa correspondiente (sin el saludo inicial)
        return self._enrutar_mensaje_directo(session, mensaje)

    def _enrutar_mensaje_directo(self, session: UserSession, mensaje: str) -> str:
        """Enruta directamente a la etapa sin detectar returning."""
        etapa = session.etapa

        if etapa == EtapaConversacion.DESCUBRIENDO_NECESIDAD:
            return self._wrap_ia(
                self._handle_descubrimiento(session, mensaje),
                session, mensaje,
            )

        if etapa == EtapaConversacion.CALIFICANDO:
            return self._wrap_ia(
                self._handle_calificacion(session, mensaje),
                session, mensaje,
            )

        if etapa == EtapaConversacion.PRESENTANDO_VALOR:
            return self._wrap_ia(
                self._handle_valor(session, mensaje),
                session, mensaje,
            )

        if etapa == EtapaConversacion.MANEJANDO_OBJECIONES:
            return self._wrap_ia(
                self._handle_objeciones(session, mensaje),
                session, mensaje,
            )

        if etapa == EtapaConversacion.INTENTANDO_CIERRE:
            return self._wrap_ia(
                self._handle_cierre(session, mensaje),
                session, mensaje,
            )

        return (
            f"{session.lead.nombre or 'Hola'}, "
            "¿en qué puedo ayudarte?"
        )

    def _handle_descubrimiento(self, session: UserSession, mensaje: str) -> str:
        """Maneja la etapa de descubrimiento de necesidad."""
        lead = session.lead

        if lead.nombre is None:
            from app.services.lead_qualifier import _extraer_nombre
            nombre = _extraer_nombre(mensaje)
            if nombre:
                lead.nombre = nombre
            else:
                return "¿Cómo te llamás?"

        from app.services.lead_qualifier import _detectar_grupo_familiar
        gf = _detectar_grupo_familiar(mensaje)
        if gf:
            lead.actualizar_grupo_familiar(
                conyuge=gf["conyuge"],
                hijos=gf["hijos"],
                cantidad_hijos=gf["cantidad_hijos"],
            )

        from app.services.lead_qualifier import _detectar_tipo_afiliacion
        tipo = _detectar_tipo_afiliacion(mensaje)
        if tipo:
            lead.tipo_afiliacion = tipo

        session.avanzar_etapa(EtapaConversacion.CALIFICANDO)

        return (
            f"¡Genial {lead.nombre}! "
            + generar_pregunta_situacion_actual()
        )

    def _handle_calificacion(self, session: UserSession, mensaje: str) -> str:
        """Maneja la etapa de calificación."""
        lead = session.lead
        lead.estado_comercial = EstadoComercial.CALIFICANDO

        resultado = self.qualifier.process_message(lead, mensaje)
        session.mensajes_en_etapa += 1

        objecion = analizar_mensaje(mensaje, lead)
        if objecion.es_objecion:
            lead.estado_comercial = EstadoComercial.OBJECION
            session.avanzar_etapa(EtapaConversacion.MANEJANDO_OBJECIONES)
            return objecion.respuesta or ""

        if self._lead_listo_para_valor(lead):
            lead.estado_comercial = EstadoComercial.INTERESADO
            session.avanzar_etapa(EtapaConversacion.PRESENTANDO_VALOR)
            return generar_argumento(lead)

        if resultado.proxima_pregunta:
            return self._generar_siguiente_pregunta(lead, resultado.proxima_pregunta)

        if session.mensajes_en_etapa > 6:
            lead.estado_comercial = EstadoComercial.INTERESADO
            session.avanzar_etapa(EtapaConversacion.PRESENTANDO_VALOR)
            return generar_argumento(lead)

        return self._generar_siguiente_pregunta(
            lead, resultado.proxima_pregunta or "nombre"
        )

    def _handle_valor(self, session: UserSession, mensaje: str) -> str:
        """Maneja la etapa de generación de valor."""
        lead = session.lead
        lead.estado_comercial = EstadoComercial.INTERESADO

        objecion = analizar_mensaje(mensaje, lead)
        if objecion.es_objecion:
            lead.estado_comercial = EstadoComercial.OBJECION
            session.avanzar_etapa(EtapaConversacion.MANEJANDO_OBJECIONES)
            return objecion.respuesta or ""

        if any(p in mensaje.lower() for p in [
            "sí", "si", "dale", "avanzamos", "ok", "quiero",
        ]):
            lead.estado_comercial = EstadoComercial.INTENTANDO_CIERRE
            session.avanzar_etapa(EtapaConversacion.INTENTANDO_CIERRE)
            cierre = intentar_cierre(lead)
            session.intento_de_cierre = True
            return cierre.respuesta

        session.mensajes_en_etapa += 1
        if session.mensajes_en_etapa >= 3:
            lead.estado_comercial = EstadoComercial.INTENTANDO_CIERRE
            session.avanzar_etapa(EtapaConversacion.INTENTANDO_CIERRE)
            cierre = intentar_cierre(lead)
            session.intento_de_cierre = True
            return cierre.respuesta

        beneficios = self.knowledge.obtener_beneficios()
        if beneficios:
            return (
                f"¿Te gustaría que te cuente más detalles sobre nuestros beneficios "
                "o preferís que avancemos?"
            )

        return (
            "¿Te gustaría que te cuente más detalles o preferís que avancemos?"
        )

    def _handle_objeciones(self, session: UserSession, mensaje: str) -> str:
        """Maneja la etapa de objeciones."""
        lead = session.lead
        lead.estado_comercial = EstadoComercial.OBJECION

        objecion = analizar_mensaje(mensaje, lead)

        if objecion.es_objecion:
            session.mensajes_en_etapa += 1
            if session.mensajes_en_etapa >= 3:
                lead.estado_comercial = EstadoComercial.SEGUIMIENTO
                session.avanzar_etapa(EtapaConversacion.CALIFICADO)
                return (
                    f"{lead.nombre or 'Hola'}, entiendo que tenés algunas dudas. "
                    "Un asesor especializado puede darte una atención más personalizada. "
                    "¿Te parece si coordinamos una llamada?"
                )
            respuesta_knowledge = self.knowledge.obtener_respuesta_objecion(mensaje)
            if respuesta_knowledge:
                return f"{objecion.respuesta} {respuesta_knowledge}"
            return objecion.respuesta or ""

        lead.estado_comercial = EstadoComercial.INTENTANDO_CIERRE
        session.avanzar_etapa(EtapaConversacion.INTENTANDO_CIERRE)
        cierre = intentar_cierre(lead)
        session.intento_de_cierre = True
        return cierre.respuesta

    def _handle_cierre(self, session: UserSession, mensaje: str) -> str:
        """Maneja la etapa de cierre."""
        lead = session.lead
        lead.estado_comercial = EstadoComercial.INTENTANDO_CIERRE
        resultado = interpretar_respuesta_cierre(mensaje)
        session.resultado_cierre = resultado

        if resultado == ResultadoCierre.ACEPTO:
            lead.estado_comercial = EstadoComercial.VENDIDO
            session.avanzar_etapa(EtapaConversacion.CALIFICADO)
            return (
                f"¡Excelente {lead.nombre or ''}! Me alegra que hayas decidido avanzar. "
                "Un asesor se comunicará con vos para completar el proceso. "
                "¡Bienvenido a Servired! 😊"
            )

        if resultado == ResultadoCierre.RECHAZO:
            lead.estado_comercial = EstadoComercial.PERDIDO
            session.avanzar_etapa(EtapaConversacion.CALIFICADO)
            return (
                f"¡No hay problema {lead.nombre or ''}! "
                "Si en el futuro necesitás algo, acá estoy. "
                "¡Éxitos! 😊"
            )

        session.mensajes_en_etapa += 1
        if session.mensajes_en_etapa >= 2:
            lead.estado_comercial = EstadoComercial.SEGUIMIENTO
            session.avanzar_etapa(EtapaConversacion.CALIFICADO)
            return (
                f"{lead.nombre or 'Hola'}, entiendo que necesitás tiempo. "
                "Un asesor puede contactarte cuando estés listo. "
                "¿Dejamos un contacto?"
            )

        return recuperar_indeciso(lead)

    # ─────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────

    def _lead_listo_para_valor(self, lead: Lead) -> bool:
        """Determina si el lead tiene suficiente información para generar valor."""
        return (
            lead.nombre is not None
            and lead.tipo_afiliacion is not None
            and (
                lead.grupo_familiar.conyuge
                or lead.grupo_familiar.hijos
                or lead.cantidad_integrantes >= 1
            )
        )

    def _generar_siguiente_pregunta(self, lead: Lead, proxima_pregunta: str) -> str:
        """Genera el texto de la siguiente pregunta."""
        preguntas = {
            "nombre": "¿Cómo te llamás?",
            "tipo_afiliacion": generar_pregunta_situacion_actual(),
            "tiene_aportes": "¿Contás con aportes actualmente?",
            "grupo_familiar": generar_pregunta_grupo_familiar(),
            "cantidad_hijos": "¿Cuántos hijos tenés?",
            "localidad": "¿De qué localidad sos?",
            "edad": "¿Cuántos años tenés?",
            "necesidad_principal": generar_pregunta_prioridad(),
            "interes_detectado": "¿Qué te gustaría saber de Servired?",
        }

        return preguntas.get(proxima_pregunta, "¿Podés contarme un poco más?")

    # ─────────────────────────────────────────
    # IA helpers — AIService decide tono, empatía, persuasión
    # ─────────────────────────────────────────

    def _wrap_ia(self, respuesta: str, session: UserSession, mensaje: str) -> str:
        """Envuelve una respuesta lógica con generación IA si está disponible."""
        return self._mejorar_respuesta_con_ia(
            lead=session.lead,
            etapa=session.etapa,
            mensaje=mensaje,
            respuesta_logica=respuesta,
        )

    def _obtener_knowledge_para_etapa(
        self, lead: Lead, etapa: EtapaConversacion, mensaje: str
    ) -> str:
        """
        Obtiene información de knowledge relevante para el Lead y etapa.

        Prioriza KnowledgeEngine (DB) cuando está disponible.
        Fallback a KnowledgeService (archivos markdown).
        """
        partes: list[str] = []

        # ── Prioridad 1: KnowledgeEngine (DB) ──
        if self._knowledge_engine is not None:
            contexto_db = self._knowledge_engine.contexto_para_lead(lead, etapa.value, mensaje)
            if contexto_db:
                partes.append(contexto_db)

        # ── Prioridad 2: KnowledgeService (archivos markdown) — fallback o complemento ──
        contexto_lead = self.knowledge.contexto_para_lead(lead, etapa.value, mensaje)
        if contexto_lead:
            partes.append(contexto_lead)

        # Conocimiento específico de etapa (complemento)
        if etapa == EtapaConversacion.PRESENTANDO_VALOR:
            if lead.prioridad_cliente == PrioridadCliente.ECONOMICO:
                perfil = self.knowledge.obtener_argumento_perfil("económico")
            elif lead.grupo_familiar.conyuge or lead.grupo_familiar.hijos:
                perfil = self.knowledge.obtener_argumento_perfil("familias")
            elif lead.tipo_afiliacion == TipoAfiliacion.MONOTRIBUTO:
                perfil = self.knowledge.obtener_argumento_perfil("monotributistas")
            else:
                perfil = self.knowledge.obtener_argumento_perfil("particulares")
            if perfil:
                partes.append(perfil)

        elif etapa == EtapaConversacion.MANEJANDO_OBJECIONES:
            objecion = self.knowledge.obtener_respuesta_objecion(mensaje)
            if objecion:
                partes.append(objecion)

        elif etapa == EtapaConversacion.INTENTANDO_CIERRE:
            cierres = self.knowledge.obtener_cierres()
            if cierres:
                partes.append(cierres[:500])

        return "\n\n".join(partes)

    def _mejorar_respuesta_con_ia(
        self,
        lead: Lead,
        etapa: EtapaConversacion,
        mensaje: str,
        respuesta_logica: str,
    ) -> str:
        """Usa la IA para mejorar la respuesta lógica con lenguaje natural."""
        if self.ai is None or not self.ai.disponible:
            return respuesta_logica

        knowledge = self._obtener_knowledge_para_etapa(lead, etapa, mensaje)

        logger.debug(
            "[AI] Generando respuesta — etapa=%s, knowledge_len=%d, msg=%s",
            etapa.value, len(knowledge), mensaje[:40],
        )

        resultado = self.ai.generar_respuesta(
            lead=lead,
            etapa=etapa,
            knowledge=knowledge,
            mensaje_cliente=mensaje,
            respuesta_fallback=respuesta_logica,
        )

        logger.debug(
            "[AI] Respuesta generada (%d chars) — fallback_used=%s",
            len(resultado), resultado == respuesta_logica,
        )

        return resultado

    # ─────────────────────────────────────────
    # DB helpers
    # ─────────────────────────────────────────

    def _cargar_lead_desde_db(self, telegram_id: int, session: UserSession) -> None:
        """Carga el lead persistido desde la DB si existe."""
        try:
            db = self._db_factory()
            try:
                lead_repo = LeadRepository(db)
                lead_db = lead_repo.buscar_por_telegram_id(telegram_id)
                if lead_db is not None:
                    lead_domain = lead_repo.db_a_lead_domain(lead_db)
                    session.lead = lead_domain
                    if lead_db.etapa_conversacion:
                        try:
                            session.etapa = EtapaConversacion(
                                lead_db.etapa_conversacion
                            )
                        except ValueError:
                            pass
                    logger.info(
                        "[DATABASE] Lead cargado — id=%s, nombre=%s, etapa=%s, estado=%s",
                        telegram_id, lead_domain.nombre,
                        session.etapa.value,
                        lead_domain.estado_comercial.value,
                    )
            finally:
                db.close()
        except Exception as e:
            logger.warning("[DATABASE] Error cargando lead: %s", e)

    def _guardar_lead_en_db(
        self, telegram_id: int, lead: Lead, session: UserSession
    ) -> None:
        """Guarda o actualiza el lead en la DB."""
        try:
            db = self._db_factory()
            try:
                lead_repo = LeadRepository(db)
                lead_db = lead_repo.buscar_por_telegram_id(telegram_id)
                if lead_db is None:
                    lead_db = lead_repo.crear_lead(telegram_id)
                lead_repo.lead_domain_a_db(lead, lead_db)
                lead_db.etapa_conversacion = session.etapa.value
                lead_repo.actualizar_lead(lead_db)
                logger.debug(
                    "[DATABASE] Lead guardado — id=%s, etapa=%s",
                    telegram_id, session.etapa.value,
                )
            finally:
                db.close()
        except Exception as e:
            logger.warning("[DATABASE] Error guardando lead: %s", e)

    def _guardar_mensaje_en_db(
        self,
        telegram_id: int,
        mensaje: str,
        respuesta: str,
        session: UserSession,
    ) -> None:
        """Guarda el intercambio de mensajes en la DB."""
        try:
            db = self._db_factory()
            try:
                lead_repo = LeadRepository(db)
                lead_db = lead_repo.buscar_por_telegram_id(telegram_id)
                if lead_db is not None:
                    conv_repo = ConversationRepository(db)
                    conv_repo.guardar_mensaje(
                        lead_id=lead_db.id,
                        mensaje_cliente=mensaje,
                        respuesta_sofia=respuesta,
                        etapa=session.etapa.value,
                    )
                    logger.debug(
                        "[DATABASE] Mensaje guardado — lead_id=%d, etapa=%s",
                        lead_db.id, session.etapa.value,
                    )
            finally:
                db.close()
        except Exception as e:
            logger.warning("[DATABASE] Error guardando mensaje: %s", e)
