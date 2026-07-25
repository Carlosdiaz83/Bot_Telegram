"""
Orquestador del flujo de conversación comercial.

Coordina sesión, LeadQualifier, sales_strategy, objection_handler
y closing_strategy para manejar la conversación completa.

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

        # DB — opcional, si no se pasa URL no persiste
        self._db_enabled = database_url is not None
        if self._db_enabled:
            engine = get_engine(database_url)
            crear_tablas(engine)
            self._db_factory = get_session_factory(engine)
        else:
            self._db_factory = None

    def procesar_mensaje(self, telegram_id: int, mensaje: str) -> str:
        """
        Procesa un mensaje del usuario y devuelve la respuesta de Sofía.

        Args:
            telegram_id: ID del usuario en Telegram.
            mensaje: Texto del mensaje.

        Returns:
            Respuesta de Sofía.
        """
        session = self.session_manager.get_or_create(telegram_id)
        lead = session.lead

        # DB: cargar lead persistido si existe
        if self._db_enabled:
            self._cargar_lead_desde_db(telegram_id, session)

        mensaje_lower = mensaje.lower().strip()

        logger.debug(
            "Procesando mensaje de %s en etapa %s: %s",
            telegram_id,
            session.etapa.value,
            mensaje[:50],
        )

        respuesta = ""

        # ── Saludo inicial ──
        if session.etapa == EtapaConversacion.NUEVO:
            respuesta = self._handle_nuevo(session, mensaje)

        # ── Descubrimiento de necesidad ──
        elif session.etapa == EtapaConversacion.DESCUBRIENDO_NECESIDAD:
            respuesta = self._wrap_ia(
                self._handle_descubrimiento(session, mensaje),
                session, mensaje,
            )

        # ── Calificación ──
        elif session.etapa == EtapaConversacion.CALIFICANDO:
            respuesta = self._wrap_ia(
                self._handle_calificacion(session, mensaje),
                session, mensaje,
            )

        # ── Generación de valor ──
        elif session.etapa == EtapaConversacion.PRESENTANDO_VALOR:
            respuesta = self._wrap_ia(
                self._handle_valor(session, mensaje),
                session, mensaje,
            )

        # ── Manejo de objeciones ──
        elif session.etapa == EtapaConversacion.MANEJANDO_OBJECIONES:
            respuesta = self._wrap_ia(
                self._handle_objeciones(session, mensaje),
                session, mensaje,
            )

        # ── Intento de cierre ──
        elif session.etapa == EtapaConversacion.INTENTANDO_CIERRE:
            respuesta = self._wrap_ia(
                self._handle_cierre(session, mensaje),
                session, mensaje,
            )

        else:
            respuesta = (
                f"Gracias {lead.nombre or ''} por tu consulta. "
                "Un asesor se comunicará pronto con vos. 😊"
            )

        # Calcular score y temperatura
        lead.score, lead.temperatura_lead = self.scoring.calcular_y_clasificar(lead)

        # DB: guardar lead y mensaje
        if self._db_enabled:
            self._guardar_lead_en_db(telegram_id, lead, session)
            self._guardar_mensaje_en_db(telegram_id, mensaje, respuesta, session)

        return respuesta

    # ─────────────────────────────────────────
    # Handlers por etapa
    # ─────────────────────────────────────────

    def _handle_nuevo(self, session: UserSession, mensaje: str) -> str:
        """Maneja el primer mensaje del usuario."""
        lead = session.lead

        # Detectar nombre del primer mensaje
        from app.services.lead_qualifier import _extraer_nombre
        nombre = _extraer_nombre(mensaje)
        if nombre:
            lead.nombre = nombre
            lead.estado_comercial = EstadoComercial.CONTACTADO
            session.avanzar_etapa(EtapaConversacion.DESCUBRIENDO_NECESIDAD)
            return (
                f"¡Hola {nombre}! Soy Sofía 😊, asistente de Servired. "
                "Te voy a ayudar a encontrar la opción más conveniente para vos. "
                f"Decime {nombre}, ¿la cobertura sería para vos o tu familia?"
            )

        # Si no extrajo nombre, pedirlo
        lead.estado_comercial = EstadoComercial.CONTACTADO
        session.avanzar_etapa(EtapaConversacion.DESCUBRIENDO_NECESIDAD)
        return (
            "¡Hola! Soy Sofía 😊, asistente de Servired. "
            "Te voy a ayudar a encontrar la opción más conveniente para vos. "
            "¿Cómo te llamás?"
        )

    def _handle_descubrimiento(self, session: UserSession, mensaje: str) -> str:
        """Maneja la etapa de descubrimiento de necesidad."""
        lead = session.lead
        mensaje_lower = mensaje.lower()

        # Si todavía no tiene nombre, pedirlo
        if lead.nombre is None:
            from app.services.lead_qualifier import _extraer_nombre
            nombre = _extraer_nombre(mensaje)
            if nombre:
                lead.nombre = nombre
            else:
                return "¿Cómo te llamás?"

        # Detectar grupo familiar
        from app.services.lead_qualifier import _detectar_grupo_familiar
        gf = _detectar_grupo_familiar(mensaje)
        if gf:
            lead.actualizar_grupo_familiar(
                conyuge=gf["conyuge"],
                hijos=gf["hijos"],
                cantidad_hijos=gf["cantidad_hijos"],
            )

        # Detectar si menciona cobertura actual
        from app.services.lead_qualifier import _detectar_tipo_afiliacion
        tipo = _detectar_tipo_afiliacion(mensaje)
        if tipo:
            lead.tipo_afiliacion = tipo

        # Avanzar a calificación
        session.avanzar_etapa(EtapaConversacion.CALIFICANDO)

        return (
            f"¡Genial {lead.nombre}! "
            + generar_pregunta_situacion_actual()
        )

    def _handle_calificacion(self, session: UserSession, mensaje: str) -> str:
        """Maneja la etapa de calificación."""
        lead = session.lead
        lead.estado_comercial = EstadoComercial.CALIFICANDO

        # Usar LeadQualifier para extraer datos
        resultado = self.qualifier.process_message(lead, mensaje)
        session.mensajes_en_etapa += 1

        # Detectar objeciones durante calificación
        objecion = analizar_mensaje(mensaje, lead)
        if objecion.es_objecion:
            lead.estado_comercial = EstadoComercial.OBJECION
            session.avanzar_etapa(EtapaConversacion.MANEJANDO_OBJECIONES)
            return objecion.respuesta or ""

        # Si tiene suficiente información para generar valor
        if self._lead_listo_para_valor(lead):
            lead.estado_comercial = EstadoComercial.INTERESADO
            session.avanzar_etapa(EtapaConversacion.PRESENTANDO_VALOR)
            return generar_argumento(lead)

        # Si hay siguiente pregunta, continuar calificando
        if resultado.proxima_pregunta:
            return self._generar_siguiente_pregunta(lead, resultado.proxima_pregunta)

        # Si no hay más preguntas pero falta algo, reforzar
        if session.mensajes_en_etapa > 6:
            lead.estado_comercial = EstadoComercial.INTERESADO
            session.avanzar_etapa(EtapaConversacion.PRESENTANDO_VALOR)
            return generar_argumento(lead)

        return self._generar_siguiente_pregunta(lead, resultado.proxima_pregunta or "nombre")

    def _handle_valor(self, session: UserSession, mensaje: str) -> str:
        """Maneja la etapa de generación de valor."""
        lead = session.lead
        lead.estado_comercial = EstadoComercial.INTERESADO

        # Detectar objeciones
        objecion = analizar_mensaje(mensaje, lead)
        if objecion.es_objecion:
            lead.estado_comercial = EstadoComercial.OBJECION
            session.avanzar_etapa(EtapaConversacion.MANEJANDO_OBJECIONES)
            return objecion.respuesta or ""

        # Detectar interés en avanzar
        if any(p in mensaje.lower() for p in [
            "sí", "si", "dale", "avanzamos", "ok", "quiero",
        ]):
            lead.estado_comercial = EstadoComercial.INTENTANDO_CIERRE
            session.avanzar_etapa(EtapaConversacion.INTENTANDO_CIERRE)
            cierre = intentar_cierre(lead)
            session.intento_de_cierre = True
            return cierre.respuesta

        # Continuar presentando valor desde knowledge
        session.mensajes_en_etapa += 1
        if session.mensajes_en_etapa >= 3:
            lead.estado_comercial = EstadoComercial.INTENTANDO_CIERRE
            session.avanzar_etapa(EtapaConversacion.INTENTANDO_CIERRE)
            cierre = intentar_cierre(lead)
            session.intento_de_cierre = True
            return cierre.respuesta

        # Usar knowledge para dar más detalle
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

        # Volver a analizar por si la objeción persiste
        objecion = analizar_mensaje(mensaje, lead)

        if objecion.es_objecion:
            session.mensajes_en_etapa += 1
            if session.mensajes_en_etapa >= 3:
                # Muchas objeciones → derivar a asesor
                lead.estado_comercial = EstadoComercial.SEGUIMIENTO
                session.avanzar_etapa(EtapaConversacion.CALIFICADO)
                return (
                    f"{lead.nombre or 'Hola'}, entiendo que tenés algunas dudas. "
                    "Un asesor especializado puede darte una atención más personalizada. "
                    "¿Te parece si coordinamos una llamada?"
                )
            # Usar knowledge para respuestas más completas
            respuesta_knowledge = self.knowledge.obtener_respuesta_objecion(mensaje)
            if respuesta_knowledge:
                return f"{objecion.respuesta} {respuesta_knowledge}"
            return objecion.respuesta or ""

        # Si la objeción fue resuelta, volver al cierre
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

        # PENDIENTE → usar recuperación de indecisos
        session.mensajes_en_etapa += 1
        if session.mensajes_en_etapa >= 2:
            lead.estado_comercial = EstadoComercial.SEGUIMIENTO
            session.avanzar_etapa(EtapaConversacion.CALIFICADO)
            return (
                f"{lead.nombre or 'Hola'}, entiendo que necesitás tiempo. "
                "Un asesor puede contactarte cuando estés listo. "
                "¿Dejamos un contacto?"
            )

        # Intentar recuperar indeciso
        return recuperar_indeciso(lead)

    # ─────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────

    def _lead_listo_para_valor(self, lead: Lead) -> bool:
        """Determina si el lead tiene suficiente información para generar valor."""
        return (
            lead.nombre is not None
            and lead.tipo_afiliacion is not None
            and (lead.grupo_familiar.conyuge or lead.grupo_familiar.hijos or lead.cantidad_integrantes >= 1)
        )

    def _generar_siguiente_pregunta(self, lead: Lead, proxima_pregunta: str) -> str:
        """Genera el texto de la siguiente pregunta."""
        nombre = lead.nombre or ""

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
    # IA helpers
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
        """Obtiene la información de knowledge relevante para la etapa."""
        if etapa == EtapaConversacion.PRESENTANDO_VALOR:
            if lead.prioridad_cliente == PrioridadCliente.ECONOMICO:
                return self.knowledge.obtener_argumento_perfil("económico")
            if lead.grupo_familiar.conyuge or lead.grupo_familiar.hijos:
                return self.knowledge.obtener_argumento_perfil("familias")
            if lead.tipo_afiliacion == TipoAfiliacion.MONOTRIBUTO:
                return self.knowledge.obtener_argumento_perfil("monotributistas")
            return self.knowledge.obtener_argumento_perfil("particulares")

        if etapa == EtapaConversacion.MANEJANDO_OBJECIONES:
            mensaje_lower = mensaje.lower()
            if any(p in mensaje_lower for p in ["caro", "cuesta", "precio", "dinero"]):
                return self.knowledge.obtener_respuesta_objecion("caro")
            if any(p in mensaje_lower for p in ["pensar", "después", "mañana"]):
                return self.knowledge.obtener_respuesta_objecion("pensar")
            if any(p in mensaje_lower for p in ["seguro", "duda", "no sé"]):
                return self.knowledge.obtener_respuesta_objecion("seguro")
            if any(p in mensaje_lower for p in ["tiempo", "ocupado"]):
                return self.knowledge.obtener_respuesta_objecion("tiempo")
            return self.knowledge.obtener_objeciones()

        if etapa == EtapaConversacion.INTENTANDO_CIERRE:
            return self.knowledge.obtener_cierres()

        return self.knowledge.obtener_beneficios()

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
        return self.ai.generar_respuesta(
            lead=lead,
            etapa=etapa,
            knowledge=knowledge,
            mensaje_cliente=mensaje,
            respuesta_fallback=respuesta_logica,
        )

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
                            session.etapa = EtapaConversacion(lead_db.etapa_conversacion)
                        except ValueError:
                            pass
                    logger.debug("Lead cargado desde DB: telegram_id=%s", telegram_id)
            finally:
                db.close()
        except Exception as e:
            logger.warning("Error cargando lead desde DB: %s", e)

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
            finally:
                db.close()
        except Exception as e:
            logger.warning("Error guardando lead en DB: %s", e)

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
            finally:
                db.close()
        except Exception as e:
            logger.warning("Error guardando mensaje en DB: %s", e)
