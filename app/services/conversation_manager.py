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
)

logger = logging.getLogger(__name__)


class ConversationManager:
    """
    Orquestador del flujo de conversación comercial.

    Coordina todos los servicios para manejar la interacción
    del usuario desde el primer mensaje hasta el cierre.
    """

    def __init__(self) -> None:
        self.session_manager = SessionManager()
        self.qualifier = LeadQualifierService()

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
        mensaje_lower = mensaje.lower().strip()

        logger.debug(
            "Procesando mensaje de %s en etapa %s: %s",
            telegram_id,
            session.etapa.value,
            mensaje[:50],
        )

        # ── Saludo inicial ──
        if session.etapa == EtapaConversacion.NUEVO:
            return self._handle_nuevo(session, mensaje)

        # ── Descubrimiento de necesidad ──
        if session.etapa == EtapaConversacion.DESCUBRIENDO_NECESIDAD:
            return self._handle_descubrimiento(session, mensaje)

        # ── Calificación ──
        if session.etapa == EtapaConversacion.CALIFICANDO:
            return self._handle_calificacion(session, mensaje)

        # ── Generación de valor ──
        if session.etapa == EtapaConversacion.PRESENTANDO_VALOR:
            return self._handle_valor(session, mensaje)

        # ── Manejo de objeciones ──
        if session.etapa == EtapaConversacion.MANEJANDO_OBJECIONES:
            return self._handle_objeciones(session, mensaje)

        # ── Intento de cierre ──
        if session.etapa == EtapaConversacion.INTENTANDO_CIERRE:
            return self._handle_cierre(session, mensaje)

        # ── Calificado / Derivado ──
        return (
            f"Gracias {lead.nombre or ''} por tu consulta. "
            "Un asesor se comunicará pronto con vos. 😊"
        )

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
            session.avanzar_etapa(EtapaConversacion.DESCUBRIENDO_NECESIDAD)
            return (
                f"¡Hola {nombre}! Soy Sofía 😊, asistente de Servired. "
                "Te voy a ayudar a encontrar la opción más conveniente para vos. "
                f"Decime {nombre}, ¿la cobertura sería para vos o tu familia?"
            )

        # Si no extrajo nombre, pedirlo
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

        # Usar LeadQualifier para extraer datos
        resultado = self.qualifier.process_message(lead, mensaje)
        session.mensajes_en_etapa += 1

        # Detectar objeciones durante calificación
        objecion = analizar_mensaje(mensaje, lead)
        if objecion.es_objecion:
            session.avanzar_etapa(EtapaConversacion.MANEJANDO_OBJECIONES)
            return objecion.respuesta or ""

        # Si tiene suficiente información para generar valor
        if self._lead_listo_para_valor(lead):
            session.avanzar_etapa(EtapaConversacion.PRESENTANDO_VALOR)
            return generar_argumento(lead)

        # Si hay siguiente pregunta, continuar calificando
        if resultado.proxima_pregunta:
            return self._generar_siguiente_pregunta(lead, resultado.proxima_pregunta)

        # Si no hay más preguntas pero falta algo, reforzar
        if session.mensajes_en_etapa > 6:
            session.avanzar_etapa(EtapaConversacion.PRESENTANDO_VALOR)
            return generar_argumento(lead)

        return self._generar_siguiente_pregunta(lead, resultado.proxima_pregunta or "nombre")

    def _handle_valor(self, session: UserSession, mensaje: str) -> str:
        """Maneja la etapa de generación de valor."""
        lead = session.lead

        # Detectar objeciones
        objecion = analizar_mensaje(mensaje, lead)
        if objecion.es_objecion:
            session.avanzar_etapa(EtapaConversacion.MANEJANDO_OBJECIONES)
            return objecion.respuesta or ""

        # Detectar interés en avanzar
        if any(p in mensaje.lower() for p in [
            "sí", "si", "dale", "avanzamos", "ok", "quiero",
        ]):
            session.avanzar_etapa(EtapaConversacion.INTENTANDO_CIERRE)
            cierre = intentar_cierre(lead)
            session.intento_de_cierre = True
            return cierre.respuesta

        # Continuar presentando valor
        session.mensajes_en_etapa += 1
        if session.mensajes_en_etapa >= 3:
            session.avanzar_etapa(EtapaConversacion.INTENTANDO_CIERRE)
            cierre = intentar_cierre(lead)
            session.intento_de_cierre = True
            return cierre.respuesta

        return (
            "¿Te gustaría que te cuente más detalles o preferís que avancemos?"
        )

    def _handle_objeciones(self, session: UserSession, mensaje: str) -> str:
        """Maneja la etapa de objeciones."""
        lead = session.lead

        # Volver a analizar por si la objeción persiste
        objecion = analizar_mensaje(mensaje, lead)

        if objecion.es_objecion:
            session.mensajes_en_etapa += 1
            if session.mensajes_en_etapa >= 3:
                # Muchas objeciones → derivar a asesor
                session.avanzar_etapa(EtapaConversacion.CALIFICADO)
                return (
                    f"{lead.nombre or 'Hola'}, entiendo que tenés algunas dudas. "
                    "Un asesor especializado puede darte una atención más personalizada. "
                    "¿Te parece si coordinamos una llamada?"
                )
            return objecion.respuesta or ""

        # Si la objeción fue resuelta, volver al cierre
        session.avanzar_etapa(EtapaConversacion.INTENTANDO_CIERRE)
        cierre = intentar_cierre(lead)
        session.intento_de_cierre = True
        return cierre.respuesta

    def _handle_cierre(self, session: UserSession, mensaje: str) -> str:
        """Maneja la etapa de cierre."""
        lead = session.lead
        resultado = interpretar_respuesta_cierre(mensaje)
        session.resultado_cierre = resultado

        if resultado == ResultadoCierre.ACEPTO:
            session.avanzar_etapa(EtapaConversacion.CALIFICADO)
            return (
                f"¡Excelente {lead.nombre or ''}! Me alegra que hayas decidido avanzar. "
                "Un asesor se comunicará con vos para completar el proceso. "
                "¡Bienvenido a Servired! 😊"
            )

        if resultado == ResultadoCierre.RECHAZO:
            session.avanzar_etapa(EtapaConversacion.CALIFICADO)
            return (
                f"¡No hay problema {lead.nombre or ''}! "
                "Si en el futuro necesitás algo, acá estoy. "
                "¡Éxitos! 😊"
            )

        # PENDIENTE → intentar de nuevo o derivar
        session.mensajes_en_etapa += 1
        if session.mensajes_en_etapa >= 2:
            session.avanzar_etapa(EtapaConversacion.CALIFICADO)
            return (
                f"{lead.nombre or 'Hola'}, entiendo que necesitás tiempo. "
                "Un asesor puede contactarte cuando estés listo. "
                "¿Dejamos un contacto?"
            )

        return (
            "¡Tranquilo! No es nada complicado. "
            "¿Hay algo que te gustaría aclarar antes de avanzar?"
        )

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
