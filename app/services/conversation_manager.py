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
from typing import Any, Optional

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
from app.services.lead_qualifier import LeadQualifierService, clasificar_intencion
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
from app.services.servired_calculator import ServiredCalculator
from app.services.cartilla_service import CartillaService
from app.services.respuesta_bot import RespuestaBot
from app.ai.service import AIService
from app.database.database import get_engine, get_session_factory, crear_tablas
from app.database.repository import ConversationRepository, LeadRepository

logger = logging.getLogger(__name__)


def _normalizar_localidad(localidad: Optional[str]) -> str:
    """Normaliza la localidad: minúsculas y sin acentos.

    Ej: "Córdoba" -> "cordoba", "Villa María" -> "villa maria".
    """
    if not localidad:
        return ""
    acentos = {
        "á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u",
        "Á": "a", "É": "e", "Í": "i", "Ó": "o", "Ú": "u", "Ü": "u",
    }
    texto = localidad.lower()
    return "".join(acentos.get(c, c) for c in texto)


class ConversationManager:
    """
    Orquestador del flujo de conversación comercial.

    Coordina todos los servicios para manejar la interacción
    del usuario desde el primer mensaje hasta el cierre.
    """

    # Etapas del modo vendedor (cotizaciones para clientes).
    _ETAPAS_VENDEDOR = frozenset({
        EtapaConversacion.VENDEDOR_BIENVENIDA,
        EtapaConversacion.VENDEDOR_TIPO,
        EtapaConversacion.VENDEDOR_DATOS,
        EtapaConversacion.VENDEDOR_COTIZANDO,
    })

    # Frases que activan el modo vendedor.
    _VENDEDOR_FRASES = (
        "soy vendedor", "soy un vendedor", "soy vendedora", "soy una vendedora",
        "vendedor de servired", "vendedora de servired",
        "soy asesor de ventas", "soy asesora de ventas",
        "vendo planes", "vendo planes de servired",
        "me dedico a vender", "trabajo vendiendo",
    )

    # Frases que cierran el modo vendedor.
    _VENDEDOR_SALIR = (
        "salir del modo vendedor", "salir del modo",
        "no soy vendedor", "dejar de ser vendedor",
        "no quiero ser vendedor",
    )

    # Descripciones cortas por plan (fallback si no hay cartilla).
    _DESCRIPCIONES_PLANES = {
        "medimax": "Cobertura completa con consultas, estudios y odontología",
        "medimax gold": "Cobertura premium con mayores prestaciones y mejores descuentos",
        "medimax co": "Plan económico con las prestaciones esenciales al mejor precio",
        "gold": "Tope de gama con la máxima cobertura y sin coseguros",
    }

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
            db_session = self._db_factory()
            self._knowledge_engine = KnowledgeEngine(db_session)
            from app.database.repository import AportesMonotributoRepository, PriceRepository
            self._calculator = ServiredCalculator(
                db_session,
                price_repository=PriceRepository(db_session),
                aportes_monotributo_repository=AportesMonotributoRepository(db_session),
            )
            logger.info("[DATABASE] ConversationManager con DB habilitada + KnowledgeEngine + Calculator")
        else:
            self._db_factory = None
            self._knowledge_engine = None
            self._calculator = None
            logger.info("[DATABASE] ConversationManager sin DB (solo memoria)")

        # Commercial AI Orchestrator — Sprint 20
        from app.services.commercial_ai_orchestrator import CommercialAIOrchestrator
        self._orchestrator = CommercialAIOrchestrator(
            ai_service=ai_service,
            knowledge_engine=self._knowledge_engine if self._db_enabled else None,
            knowledge_service=self.knowledge,
        )

        # Commercial Director — Sprint 22
        from app.services.commercial_director import CommercialDirector
        self._director = CommercialDirector()

        # PrestacionesService — responde preguntas específicas sobre
        # beneficios/cartillas/prestaciones con datos reales (DB → web oficial).
        from app.services.web_knowledge_service import WebKnowledgeService
        from app.services.prestaciones_service import PrestacionesService
        self._web_knowledge = WebKnowledgeService()
        self._prestaciones = PrestacionesService(
            knowledge_engine=self._knowledge_engine if self._db_enabled else None,
            knowledge_service=self.knowledge,
            web_service=self._web_knowledge,
        )
        logger.info("[CONVERSATION] PrestacionesService inicializado")

        # CartillaService — resuelve el PDF de cartilla de plan/categoría
        # para adjuntarlo como respaldo tras dar la información.
        self._cartilla = CartillaService()
        logger.info("[CONVERSATION] CartillaService inicializado")

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

        lead_existente = False
        if self._db_enabled:
            lead_existente = self._cargar_lead_desde_db(telegram_id, session)

        estado_anterior = session.etapa.value

        lead = session.lead
        es_usuario_returning = self._es_usuario_returning(session)

        logger.info(
            "[CONVERSATION] telegram_id=%s, lead_existente=%s, "
            "nombre_actual=%s, etapa_actual=%s",
            telegram_id, lead_existente,
            lead.nombre, session.etapa.value,
        )

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

        estado_nuevo = session.etapa.value

        logger.info(
            "[FLOW] user=%s, mensaje='%s', handler=%s, "
            "etapa_antes=%s, etapa_despues=%s, intent=%s, "
            "returning=%s, respuesta_generada=%s",
            telegram_id, mensaje[:80], session._handler_ejecutado,
            estado_anterior, estado_nuevo,
            session.lead.interes_detectado.value if session.lead.interes_detectado else None,
            es_usuario_returning, respuesta[:80],
        )

        lead.score, lead.temperatura_lead = self.scoring.calcular_y_clasificar(lead)

        if self._db_enabled:
            self._guardar_lead_en_db(telegram_id, lead, session)
            self._guardar_mensaje_en_db(telegram_id, mensaje, respuesta, session)

        logger.info(
            "[SALES] user=%s, etapa=%s, estado=%s, score=%d, temp=%s",
            telegram_id, session.etapa.value,
            lead.estado_comercial.value, lead.score, lead.temperatura_lead,
        )

        # Adjuntos de la respuesta (cartillas PDF como respaldo)
        adjuntos = list(getattr(session, "adjuntos_pendientes", None) or [])
        session.adjuntos_pendientes = []
        if isinstance(respuesta, RespuestaBot):
            adjuntos = list(respuesta.archivos_adjuntos) + adjuntos
            respuesta = str(respuesta)
        adjuntos = list(dict.fromkeys(adjuntos))

        return RespuestaBot(respuesta, archivos_adjuntos=adjuntos)

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
        """
        Enruta el mensaje: Orchestrator extrae datos, handler ejecuta lógica.

        Flujo:
            1. NUEVO → handler tradicional (saludo + nombre)
            2. Etapas con handler → orchestrator analiza + handler ejecuta
            3. Etapas sin handler → orchestrator responde (CALIFICADO, DERIVADO)
        """
        etapa = session.etapa

        # ── Preguntas sobre prestaciones (TODA la conversación) ──
        # Si el cliente pregunta por un beneficio/cartilla/prestación específica,
        # respondemos con datos reales (DB → markdown → web oficial) y retomamos
        # el objetivo comercial.
        respuesta_prestacion = self._responder_pregunta_prestacion(session, mensaje)
        if respuesta_prestacion is not None:
            session._handler_ejecutado = "prestaciones"
            return respuesta_prestacion

        # ── Saludo (humanizado) en etapas avanzadas ──
        # Si el cliente saluda en medio de la conversación, respondemos acorde
        # y retomamos el objetivo comercial sin cambiar la etapa.
        if etapa != EtapaConversacion.NUEVO and self._es_saludo_puro(mensaje):
            session._handler_ejecutado = "_handle_saludo"
            return self._responder_saludo(session)

        # ── Modo vendedor: el usuario cotiza para sus clientes ──
        # Si ya está en modo vendedor (o la etapa vendedor se rehidrató desde
        # DB), toda la conversación se enruta a los handlers de vendedor.
        if session.es_vendedor or etapa in self._ETAPAS_VENDEDOR:
            session.es_vendedor = True
            session._handler_ejecutado = "vendedor"
            return self._handle_vendedor_etapa(session, mensaje)

        # Si el usuario declara ser vendedor, activar el modo vendedor.
        if self._es_mensaje_vendedor(mensaje):
            session.es_vendedor = True
            session._handler_ejecutado = "_handle_vendedor_bienvenida"
            return self._handle_vendedor_bienvenida(session, mensaje)

        # ── NUEVO: handler tradicional (saludo + extracción nombre) ──
        if etapa == EtapaConversacion.NUEVO:
            if es_returning:
                session._handler_ejecutado = "_handle_returning"
                return self._handle_returning(session, mensaje)
            session._handler_ejecutado = "_handle_nuevo"
            return self._handle_nuevo(session, mensaje)

        # ── Orchestrator: pre-procesamiento (extraer datos + log) ──
        historial = self._obtener_historial(session)
        faltantes = self._datos_faltantes_para_cotizar(session.lead)

        resultado = self._orchestrator.analizar(
            lead=session.lead,
            historial=historial,
            mensaje=mensaje,
            etapa=etapa,
            datos_faltantes=faltantes,
        )

        logger.info(
            "[ORCHESTRATOR] user=%s, etapa=%s → accion=%s, intencion=%s",
            session.telegram_id, etapa.value,
            resultado.accion, resultado.intencion[:50],
        )

        # Actualizar lead con datos detectados por el orchestrator
        if resultado.datos_detectados:
            self._actualizar_lead_con_datos(session.lead, resultado.datos_detectados)

        # ── Handler tradicional para la etapa actual ──
        if etapa == EtapaConversacion.DESCUBRIENDO_NECESIDAD:
            session._handler_ejecutado = "_handle_descubrimiento"
            return self._wrap_ia(
                self._handle_descubrimiento(session, mensaje),
                session, mensaje, interpretacion=resultado,
            )

        if etapa == EtapaConversacion.CALIFICANDO:
            session._handler_ejecutado = "_handle_calificacion"
            return self._wrap_ia(
                self._handle_calificacion(session, mensaje),
                session, mensaje, interpretacion=resultado,
            )

        if etapa == EtapaConversacion.ESPERANDO_DATOS:
            session._handler_ejecutado = "_handle_esperando_datos"
            return self._wrap_ia(
                self._handle_esperando_datos(session, mensaje),
                session, mensaje, interpretacion=resultado,
            )

        if etapa == EtapaConversacion.COTIZANDO:
            session._handler_ejecutado = "_handle_cotizando"
            return self._wrap_ia(
                self._handle_cotizando(session, mensaje),
                session, mensaje, interpretacion=resultado,
            )

        if etapa == EtapaConversacion.PRESENTANDO_VALOR:
            session._handler_ejecutado = "_handle_valor"
            return self._wrap_ia(
                self._handle_valor(session, mensaje),
                session, mensaje, interpretacion=resultado,
            )

        if etapa == EtapaConversacion.MANEJANDO_OBJECIONES:
            session._handler_ejecutado = "_handle_objeciones"
            return self._wrap_ia(
                self._handle_objeciones(session, mensaje),
                session, mensaje, interpretacion=resultado,
            )

        if etapa == EtapaConversacion.INTENTANDO_CIERRE:
            session._handler_ejecutado = "_handle_cierre"
            return self._wrap_ia(
                self._handle_cierre(session, mensaje),
                session, mensaje, interpretacion=resultado,
            )

        # ── Etapas sin handler (CALIFICADO, DERIVADO) → redirect según datos ──
        logger.info(
            "[DIRECTOR] user=%s, etapa=%s → sin handler, redirigiendo según datos",
            session.telegram_id, session.etapa.value,
        )
        session._handler_ejecutado = "orchestrator_fallback"
        faltantes = self._datos_faltantes_para_cotizar(session.lead)
        if session.lead.tipo_afiliacion and not faltantes:
            session.avanzar_etapa(EtapaConversacion.COTIZANDO)
            return self._handle_cotizando(session, mensaje)
        if session.lead.tipo_afiliacion:
            session.avanzar_etapa(EtapaConversacion.ESPERANDO_DATOS)
            return self._handle_esperando_datos(session, mensaje)
        if session.lead.nombre:
            session.avanzar_etapa(EtapaConversacion.CALIFICANDO)
            return self._handle_calificacion(session, mensaje)
        session.avanzar_etapa(EtapaConversacion.NUEVO)
        return self._handle_nuevo(session, mensaje)

    # ─────────────────────────────────────────
    # Helpers del Orchestrator
    # ─────────────────────────────────────────

    def _obtener_historial(self, session: UserSession) -> list[dict[str, str]]:
        """Obtiene el historial de conversación desde la DB."""
        if not self._db_enabled:
            return []

        try:
            db = self._db_factory()
            try:
                conv_repo = ConversationRepository(db)
                mensajes = conv_repo.historial_lead(
                    session.lead.lead_id, limite=12
                )
                historial: list[dict[str, str]] = []
                for msg in mensajes:
                    historial.append({"role": "user", "content": msg.mensaje_usuario})
                    historial.append({"role": "assistant", "content": msg.respuesta_sofia})
                return historial
            finally:
                db.close()
        except Exception as e:
            logger.debug("[ORCHESTRATOR] Error obteniendo historial: %s", e)
            return []

    def _actualizar_lead_con_datos(
        self, lead: Lead, datos: dict
    ) -> None:
        """Actualiza el Lead con los datos detectados por el Orchestrator."""
        if "nombre" in datos and datos["nombre"] and not lead.nombre:
            lead.nombre = datos["nombre"]

        if "localidad" in datos and datos["localidad"] and not lead.localidad:
            lead.localidad = datos["localidad"]

        if "edad" in datos and datos["edad"] and lead.edad is None:
            try:
                lead.edad = int(datos["edad"])
            except (ValueError, TypeError):
                pass

        if "tipo_afiliacion" in datos and datos["tipo_afiliacion"]:
            try:
                lead.tipo_afiliacion = TipoAfiliacion(datos["tipo_afiliacion"])
            except ValueError:
                pass

        if "categoria_monotributo" in datos and datos["categoria_monotributo"]:
            lead.categoria_monotributo = str(datos["categoria_monotributo"]).upper()

        if "tiene_recibo_sueldo" in datos:
            lead.tiene_recibo_sueldo = bool(datos["tiene_recibo_sueldo"])

        if "grupo_familiar" in datos and isinstance(datos["grupo_familiar"], dict):
            gf = datos["grupo_familiar"]
            if gf.get("conyuge") or gf.get("hijos"):
                lead.actualizar_grupo_familiar(
                    conyuge=gf.get("conyuge", False),
                    hijos=gf.get("hijos", False),
                    cantidad_hijos=gf.get("cantidad_hijos", 0),
                )

    def _accion_objecion(
        self, session: UserSession, resultado: Any, mensaje: str
    ) -> str:
        """Ejecuta la acción MANEJAR_OBJECION detectada por el Orchestrator."""
        lead = session.lead
        lead.estado_comercial = EstadoComercial.OBJECION
        session.avanzar_etapa(EtapaConversacion.MANEJANDO_OBJECIONES)
        session.mensajes_en_etapa += 1

        texto_lower = mensaje.lower()
        if any(p in texto_lower for p in [
            "asesor", "hablar con alguien", "persona", "llamada",
        ]):
            return self._accion_derivar(session, resultado)

        return resultado.respuesta

    def _accion_cerrar(
        self, session: UserSession, resultado: Any
    ) -> str:
        """Ejecuta la acción CERRAR detectada por el Orchestrator."""
        lead = session.lead
        lead.estado_comercial = EstadoComercial.INTENTANDO_CIERRE
        session.avanzar_etapa(EtapaConversacion.INTENTANDO_CIERRE)
        session.mensajes_en_etapa += 1
        return resultado.respuesta

    def _accion_derivar(
        self, session: UserSession, resultado: Any
    ) -> str:
        """Ejecuta la acción DERIVAR: transfiere a asesor humano."""
        lead = session.lead
        lead.estado_comercial = EstadoComercial.DERIVADO
        session.avanzar_etapa(EtapaConversacion.DERIVADO)
        return (
            f"¡Perfecto {lead.nombre or ''}! Un asesor se comunicará con vos pronto. "
            "¿Dejame tu número de teléfono y coordinamos una llamada?"
        )

    # ─────────────────────────────────────────
    # Handlers por etapa
    # ─────────────────────────────────────────

    def _handle_nuevo(self, session: UserSession, mensaje: str) -> str:
        """Primer mensaje: saluda, pide nombre, detecta intención comercial."""
        lead = session.lead
        lead.estado_comercial = EstadoComercial.CONTACTADO

        from app.services.lead_qualifier import _extraer_nombre
        nombre = _extraer_nombre(mensaje)

        intencion = clasificar_intencion(mensaje)
        tiene_intencion_comercial = intencion != InteresDetectado.INFORMACION_GENERAL

        if nombre:
            lead.nombre = nombre
            lead.interes_detectado = intencion

            if tiene_intencion_comercial:
                logger.info(
                    "[SALES] Intención comercial detectada en NUEVO — user=%s, "
                    "intención=%s, saltando a CALIFICANDO",
                    session.telegram_id, intencion.value,
                )
                lead.estado_comercial = EstadoComercial.CALIFICANDO
                session.avanzar_etapa(EtapaConversacion.CALIFICANDO)
                return (
                    f"¡Hola {nombre}! Soy Sofía 😊, asesora de Servired. "
                    f"Vi que buscaste {intencion.value.replace('_', ' ')}. "
                    "Para prepararte la mejor propuesta, necesito saber: "
                    "¿cuántos somos en familia y cómo es tu situación laboral "
                    "(relación de dependencia, monotributo o particular)?"
                )

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

        if tiene_intencion_comercial:
            lead.interes_detectado = intencion
            lead.estado_comercial = EstadoComercial.CALIFICANDO
            session.avanzar_etapa(EtapaConversacion.CALIFICANDO)
            return (
                "¡Hola! Soy Sofía 😊, asesora de Servired. "
                f"Vi que buscaste {intencion.value.replace('_', ' ')}. "
                "Para prepararte la mejor propuesta, necesito saber: "
                "¿cuántos somos en familia, cómo es tu situación laboral "
                "(relación de dependencia, monotributo o particular) y "
                "cómo te llamás?"
            )

        # Sin nombre y sin intención comercial → quedarse en NUEVO y pedir nombre
        logger.debug("[LEAD] Esperando nombre de user=%s", session.telegram_id)
        return (
            "¡Hola! 😊 Qué lindo que te acerques. Soy Sofía, asesora de Servired. "
            "Voy a ayudarte a encontrar la opción más conveniente para vos. "
            "Contame, ¿Cómo te llamás?"
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
        # Modo vendedor (o etapa vendedor rehidratada desde DB).
        if session.es_vendedor or session.etapa in self._ETAPAS_VENDEDOR:
            session.es_vendedor = True
            session._handler_ejecutado = "vendedor"
            return self._handle_vendedor_etapa(session, mensaje)

        etapa = session.etapa

        # Obtener interpretación del Orchestrator para el Director
        historial = self._obtener_historial(session)
        faltantes = self._datos_faltantes_para_cotizar(session.lead)
        resultado = self._orchestrator.analizar(
            lead=session.lead, historial=historial,
            mensaje=mensaje, etapa=etapa, datos_faltantes=faltantes,
        )
        if resultado.datos_detectados:
            self._actualizar_lead_con_datos(session.lead, resultado.datos_detectados)

        if etapa == EtapaConversacion.DESCUBRIENDO_NECESIDAD:
            return self._wrap_ia(
                self._handle_descubrimiento(session, mensaje),
                session, mensaje, interpretacion=resultado,
            )

        if etapa == EtapaConversacion.CALIFICANDO:
            return self._wrap_ia(
                self._handle_calificacion(session, mensaje),
                session, mensaje, interpretacion=resultado,
            )

        if etapa == EtapaConversacion.ESPERANDO_DATOS:
            return self._wrap_ia(
                self._handle_esperando_datos(session, mensaje),
                session, mensaje, interpretacion=resultado,
            )

        if etapa == EtapaConversacion.COTIZANDO:
            return self._wrap_ia(
                self._handle_cotizando(session, mensaje),
                session, mensaje, interpretacion=resultado,
            )

        if etapa == EtapaConversacion.PRESENTANDO_VALOR:
            return self._wrap_ia(
                self._handle_valor(session, mensaje),
                session, mensaje, interpretacion=resultado,
            )

        if etapa == EtapaConversacion.MANEJANDO_OBJECIONES:
            return self._wrap_ia(
                self._handle_objeciones(session, mensaje),
                session, mensaje, interpretacion=resultado,
            )

        if etapa == EtapaConversacion.INTENTANDO_CIERRE:
            return self._wrap_ia(
                self._handle_cierre(session, mensaje),
                session, mensaje, interpretacion=resultado,
            )

        # ── Etapas sin handler (CALIFICADO, DERIVADO) → redirect según datos ──
        logger.info(
            "[DIRECTOR] user=%s, etapa=%s → sin handler (directo), "
            "redirigiendo según datos",
            session.telegram_id, session.etapa.value,
        )
        faltantes = self._datos_faltantes_para_cotizar(session.lead)
        if session.lead.tipo_afiliacion and not faltantes:
            session.avanzar_etapa(EtapaConversacion.COTIZANDO)
            return self._handle_cotizando(session, mensaje)
        if session.lead.tipo_afiliacion:
            session.avanzar_etapa(EtapaConversacion.ESPERANDO_DATOS)
            return self._handle_esperando_datos(session, mensaje)
        if session.lead.nombre:
            session.avanzar_etapa(EtapaConversacion.CALIFICANDO)
            return self._handle_calificacion(session, mensaje)
        session.avanzar_etapa(EtapaConversacion.NUEVO)
        return self._handle_nuevo(session, mensaje)

    def _handle_descubrimiento(self, session: UserSession, mensaje: str) -> str:
        """Maneja la etapa de descubrimiento de necesidad — sin intención comercial."""
        lead = session.lead

        if lead.nombre is None:
            from app.services.lead_qualifier import _extraer_nombre
            nombre = _extraer_nombre(mensaje)
            if nombre:
                lead.nombre = nombre
            else:
                return "¿Cómo te llamás?"

        from app.services.lead_qualifier import (
            _detectar_grupo_familiar,
            _detectar_tipo_afiliacion,
        )
        gf = _detectar_grupo_familiar(mensaje)
        if gf:
            lead.actualizar_grupo_familiar(
                conyuge=gf["conyuge"],
                hijos=gf["hijos"],
                cantidad_hijos=gf["cantidad_hijos"],
            )

        tipo = _detectar_tipo_afiliacion(mensaje)
        if tipo:
            lead.tipo_afiliacion = tipo

        tiene_intencion = (
            lead.interes_detectado is not None
            and lead.interes_detectado != InteresDetectado.INFORMACION_GENERAL
        )

        if tiene_intencion and (gf or tipo):
            session.avanzar_etapa(EtapaConversacion.CALIFICANDO)
            faltantes = []
            if lead.tipo_afiliacion is None:
                faltantes.append(
                    "cómo es tu situación laboral (relación de dependencia, "
                    "monotributo o particular)"
                )
            if not lead.grupo_familiar.conyuge and not lead.grupo_familiar.hijos:
                faltantes.append("si la cobertura sería solo para vos o incluye familia")

            if faltantes:
                return (
                    f"¡Genial {lead.nombre}! "
                    f"Necesito saber: {', '.join(faltantes)}. "
                    "Así te preparo la mejor propuesta."
                )

        # Si detectó tipo_afiliacion → saltar a ESPERANDO_DATOS
        if tipo:
            session.avanzar_etapa(EtapaConversacion.ESPERANDO_DATOS)
            return self._handle_esperando_datos(session, mensaje)

        session.avanzar_etapa(EtapaConversacion.CALIFICANDO)

        return (
            f"¡Genial {lead.nombre}! "
            + generar_pregunta_situacion_actual()
        )

    def _handle_calificacion(self, session: UserSession, mensaje: str) -> str:
        """Maneja la etapa de calificación — recolecta tipo afiliación y grupo familiar."""
        lead = session.lead
        lead.estado_comercial = EstadoComercial.CALIFICANDO

        resultado = self.qualifier.process_message(lead, mensaje)
        session.mensajes_en_etapa += 1

        objecion = analizar_mensaje(mensaje, lead)
        if objecion.es_objecion:
            lead.estado_comercial = EstadoComercial.OBJECION
            session.avanzar_etapa(EtapaConversacion.MANEJANDO_OBJECIONES)
            return objecion.respuesta or ""

        # Si ya tiene tipo_afiliacion → ESPERANDO_DATOS para completar datos restantes
        if lead.tipo_afiliacion is not None:
            logger.info(
                "[SALES] Tipo afiliación detectado en CALIFICANDO — user=%s, "
                "tipo=%s, pasando a ESPERANDO_DATOS",
                session.telegram_id, lead.tipo_afiliacion.value,
            )
            session.avanzar_etapa(EtapaConversacion.ESPERANDO_DATOS)
            return self._handle_esperando_datos(session, mensaje)

        if resultado.proxima_pregunta:
            return self._generar_siguiente_pregunta(lead, resultado.proxima_pregunta)

        return self._generar_siguiente_pregunta(
            lead, resultado.proxima_pregunta or "tipo_afiliacion"
        )

    def _handle_valor(self, session: UserSession, mensaje: str) -> str:
        """Maneja la etapa de generación de valor — presenta propuesta y busca cierre."""
        lead = session.lead
        lead.estado_comercial = EstadoComercial.INTERESADO

        objecion = analizar_mensaje(mensaje, lead)
        if objecion.es_objecion:
            lead.estado_comercial = EstadoComercial.OBJECION
            session.avanzar_etapa(EtapaConversacion.MANEJANDO_OBJECIONES)
            return objecion.respuesta or ""

        # Cliente pregunta por un plan específico → cotizar y presentar ese plan
        plan_preguntado = self._detectar_plan_mencionado(mensaje)
        if plan_preguntado:
            return self._cotizar_plan_especifico(session, plan_preguntado)

        # Cliente dice "sí/dale/ok" → intentar cierre
        if any(p in mensaje.lower() for p in [
            "sí", "si", "dale", "avanzamos", "ok", "quiero",
        ]):
            lead.estado_comercial = EstadoComercial.INTENTANDO_CIERRE
            session.avanzar_etapa(EtapaConversacion.INTENTANDO_CIERRE)
            cierre = intentar_cierre(lead)
            session.intento_de_cierre = True
            return cierre.respuesta

        # Sin respuesta afirmativa → reforzar valor (sin force-advance)
        beneficios = self.knowledge.obtener_beneficios()
        if beneficios:
            return (
                "Te cuento que nuestros planes incluyen consultas, estudios, "
                "odontología y más. Si querés, avanzamos con la afiliación."
            )

        return (
            "Si querés, avanzamos con la afiliación. "
            "Necesito unos datos más para preparar tu propuesta."
        )

    def _handle_objeciones(self, session: UserSession, mensaje: str) -> str:
        """Maneja la etapa de objeciones — resuelve dudas o deriva si es necesario."""
        lead = session.lead
        lead.estado_comercial = EstadoComercial.OBJECION

        # Detectar si pide asesor explícitamente
        texto_lower = mensaje.lower()
        if any(p in texto_lower for p in [
            "asesor", "hablar con alguien", "persona", "llamada",
            "teléfono", "contacto",
        ]):
            lead.estado_comercial = EstadoComercial.DERIVADO
            session.avanzar_etapa(EtapaConversacion.DERIVADO)
            return (
                f"¡Perfecto {lead.nombre or ''}! Un asesor se comunicará con vos pronto. "
                "¿Dejame tu número de teléfono y coordinamos una llamada?"
            )

        objecion = analizar_mensaje(mensaje, lead)

        if objecion.es_objecion:
            session.mensajes_en_etapa += 1
            if session.mensajes_en_etapa >= 5:
                lead.estado_comercial = EstadoComercial.SEGUIMIENTO
                session.avanzar_etapa(EtapaConversacion.CALIFICADO)
                return (
                    f"{lead.nombre or 'Hola'}, entiendo que tenés algunas dudas. "
                    "Un asesor especializado puede darte una atención más personalizada. "
                    "Dejame tu número y coordinamos una llamada."
                )
            respuesta_knowledge = self.knowledge.obtener_respuesta_objecion(mensaje)
            if respuesta_knowledge:
                return f"{objecion.respuesta} {respuesta_knowledge}"
            return objecion.respuesta or ""

        # No es objeción → volver a intentar cierre
        lead.estado_comercial = EstadoComercial.INTENTANDO_CIERRE
        session.avanzar_etapa(EtapaConversacion.INTENTANDO_CIERRE)
        cierre = intentar_cierre(lead)
        session.intento_de_cierre = True
        return cierre.respuesta

    def _handle_cierre(self, session: UserSession, mensaje: str) -> str:
        """Maneja la etapa de cierre — interpreta respuesta del cliente."""
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
        if session.mensajes_en_etapa >= 4:
            lead.estado_comercial = EstadoComercial.SEGUIMIENTO
            session.avanzar_etapa(EtapaConversacion.CALIFICADO)
            return (
                f"{lead.nombre or 'Hola'}, entiendo que necesitás tiempo. "
                "Un asesor puede contactarte cuando estés listo. "
                "Dejame tu número y te contactamos."
            )

        return recuperar_indeciso(lead)

    # ─────────────────────────────────────────
    # Modo vendedor — cotizaciones para clientes
    # ─────────────────────────────────────────

    def _es_mensaje_vendedor(self, mensaje: str) -> bool:
        """Detecta si el usuario declara ser vendedor de SERVIRED."""
        if not mensaje:
            return False
        texto = _normalizar_localidad(mensaje).lower()
        return any(frase in texto for frase in self._VENDEDOR_FRASES)

    def _es_salir_vendedor(self, mensaje: str) -> bool:
        """Detecta si el vendedor quiere salir del modo vendedor."""
        if not mensaje:
            return False
        texto = _normalizar_localidad(mensaje).lower()
        return any(frase in texto for frase in self._VENDEDOR_SALIR)

    def _handle_vendedor_etapa(self, session: UserSession, mensaje: str) -> str:
        """Enruta el mensaje dentro del modo vendedor según la etapa."""
        if self._es_salir_vendedor(mensaje):
            return self._salir_modo_vendedor(session)

        etapa = session.etapa
        if etapa == EtapaConversacion.VENDEDOR_BIENVENIDA:
            return self._handle_vendedor_bienvenida(session, mensaje)
        if etapa == EtapaConversacion.VENDEDOR_TIPO:
            return self._handle_vendedor_tipo(session, mensaje)
        if etapa == EtapaConversacion.VENDEDOR_DATOS:
            return self._handle_vendedor_datos(session, mensaje)
        if etapa == EtapaConversacion.VENDEDOR_COTIZANDO:
            return self._handle_vendedor_cotizando_loop(session, mensaje)

        # Rehidratar una sesión vendedor sin etapa vendedor válida.
        session.avanzar_etapa(EtapaConversacion.VENDEDOR_TIPO)
        return self._handle_vendedor_tipo(session, mensaje)

    def _handle_vendedor_bienvenida(self, session: UserSession, mensaje: str) -> str:
        """Activa el modo vendedor: presenta la asistencia de cotización."""
        lead = session.lead
        lead.estado_comercial = EstadoComercial.CALIFICANDO
        session.avanzar_etapa(EtapaConversacion.VENDEDOR_TIPO)
        return (
            "¡Hola! Soy Sofía 😊. ¡Perfecto que sos vendedor de Servired! "
            "Te ayudo a armar las cotizaciones de tus clientes. "
            "Decime: ¿la persona a cotizar es con recibo de sueldo, "
            "monotributo o directo? ¿O solo tenés una consulta?"
        )

    def _detectar_tipo_cotizacion(self, mensaje: str) -> TipoAfiliacion | None:
        """Detecta el tipo de afiliación de la persona a cotizar."""
        if not mensaje:
            return None
        texto = _normalizar_localidad(mensaje).lower()

        if any(p in texto for p in ["monotributo", "monotributista"]):
            return TipoAfiliacion.MONOTRIBUTO
        if any(p in texto for p in [
            "recibo", "relacion de dependencia", "dependencia",
            "empleado", "en blanco", "con aportes", "obra social",
        ]):
            return TipoAfiliacion.RELACION_DEPENDENCIA
        if any(p in texto for p in [
            "directo", "particular", "autonomo", "independiente",
            "sin recibo", "sin monotributo",
        ]):
            return TipoAfiliacion.PARTICULAR
        return None

    def _handle_vendedor_tipo(self, session: UserSession, mensaje: str) -> str:
        """Recolecta el tipo de afiliación de la persona a cotizar (o deriva a consulta)."""
        lead = session.lead

        tipo = self._detectar_tipo_cotizacion(mensaje)
        if tipo is not None:
            lead.tipo_afiliacion = tipo

            # Capturar datos extra que puedan venir en el mismo mensaje.
            from app.services.lead_qualifier import (
                _detectar_grupo_familiar,
                _extraer_edad,
                _extraer_localidad,
            )
            if lead.edad is None:
                lead.edad = _extraer_edad(mensaje)
            if lead.localidad is None:
                lead.localidad = _extraer_localidad(mensaje)
            gf = _detectar_grupo_familiar(mensaje)
            if gf:
                lead.actualizar_grupo_familiar(
                    conyuge=gf["conyuge"],
                    hijos=gf["hijos"],
                    cantidad_hijos=gf["cantidad_hijos"],
                )

            session.avanzar_etapa(EtapaConversacion.VENDEDOR_DATOS)
            return (
                "¡Genial! Necesito los datos de la persona a cotizar: "
                "¿cómo se llama?"
            )

        if any(p in mensaje.lower() for p in [
            "consulta", "pregunta", "duda", "información", "info",
            "otra consulta", "quería saber",
        ]):
            return "¡Claro! Decime tu consulta y te ayudo 😊"

        return (
            "Perfecto, necesito saber si la persona a cotizar es con recibo "
            "de sueldo, monotributo o directo. ¿O solo tenés una consulta?"
        )

    def _handle_vendedor_datos(self, session: UserSession, mensaje: str) -> str:
        """Recolecta los datos de la persona a cotizar y arma la cotización."""
        import re

        lead = session.lead

        # Nombre de la persona a cotizar.
        if lead.nombre is None:
            from app.services.lead_qualifier import _extraer_nombre
            nombre_msg = re.sub(
                r"^(?:el|la)\s+(?:cliente|persona)\s+se\s+llama\s+",
                "", mensaje, flags=re.IGNORECASE,
            )
            nombre_msg = re.sub(
                r"^se\s+llama\s+", "", nombre_msg, flags=re.IGNORECASE,
            )
            nombre = _extraer_nombre(nombre_msg) or _extraer_nombre(mensaje)
            if not nombre:
                texto_limpio = mensaje.strip()
                if (
                    texto_limpio
                    and " " not in texto_limpio
                    and texto_limpio.isalpha()
                    and len(texto_limpio) >= 3
                    and texto_limpio.lower() not in {"no", "si", "consulta", "ayuda", "monotributo", "recibo", "directo", "particular"}
                ):
                    nombre = texto_limpio.capitalize()
            # Último recurso: primera palabra con mayúscula inicial (estamos
            # en el paso del nombre, así que el candidato es casi seguro el nombre).
            if not nombre:
                match = re.search(
                    r"\b([A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,})\b", mensaje
                )
                if match:
                    candidato = match.group(1)
                    if candidato.lower() not in {
                        "córdoba", "cordoba", "rosario", "salta", "mendoza",
                        "chaco", "santa", "fe", "tucuman", "tucumán",
                    }:
                        nombre = candidato
            if not nombre:
                return "¿Cómo se llama la persona a cotizar?"
            lead.nombre = nombre

        # Datos restantes: edad, localidad, grupo familiar, categoría/recibo.
        from app.services.lead_qualifier import (
            _detectar_grupo_familiar,
            _extraer_edad,
            _extraer_localidad,
        )
        if lead.localidad is None:
            lead.localidad = _extraer_localidad(mensaje)
        if lead.edad is None:
            lead.edad = _extraer_edad(mensaje)
        if not lead.grupo_familiar.conyuge and not lead.grupo_familiar.hijos:
            gf = _detectar_grupo_familiar(mensaje)
            if gf:
                lead.actualizar_grupo_familiar(
                    conyuge=gf["conyuge"],
                    hijos=gf["hijos"],
                    cantidad_hijos=gf["cantidad_hijos"],
                )

        if (
            lead.tipo_afiliacion == TipoAfiliacion.MONOTRIBUTO
            and lead.categoria_monotributo is None
        ):
            match = re.search(r"categor[íi]a\s+([A-Ha-h])", mensaje, re.IGNORECASE)
            if match:
                lead.categoria_monotributo = match.group(1).upper()

        if lead.tipo_afiliacion == TipoAfiliacion.RELACION_DEPENDENCIA:
            if self._detectar_recibo_sueldo(mensaje):
                lead.tiene_recibo_sueldo = True
                if not lead.conceptos_obra_social:
                    conceptos = self._extraer_conceptos_obra_social(mensaje)
                    if conceptos:
                        lead.conceptos_obra_social = conceptos

        faltantes = self._datos_faltantes_para_cotizar(lead, vendedor=True)
        if not faltantes:
            session.avanzar_etapa(EtapaConversacion.VENDEDOR_COTIZANDO)
            return self._handle_vendedor_cotizando(session, mensaje)

        session.mensajes_en_etapa += 1
        return f"¿{faltantes[0].capitalize()}?"

    def _handle_vendedor_cotizando(self, session: UserSession, mensaje: str) -> str:
        """Arma la cotización de los planes para el cliente del vendedor."""
        lead = session.lead

        zona = "cordoba"
        if "cordoba" not in _normalizar_localidad(lead.localidad):
            zona = "interior"

        planes = ["medimax", "medimax gold", "medimax co"]

        session.avanzar_etapa(EtapaConversacion.VENDEDOR_COTIZANDO)

        if self._calculator is None:
            texto = (
                f"¡Listo! Acá tenés los planes para "
                f"*{lead.nombre or 'tu cliente'}*:\n\n"
            )
            for plan in planes:
                texto += f"📋 *{plan.title()}*\n"
                bullets = self._bullets_plan(plan, 4)
                if bullets:
                    for b in bullets:
                        texto += f"   ✓ {b}\n"
                else:
                    texto += f"   {self._DESCRIPCIONES_PLANES.get(plan, '')}\n"
                texto += "\n"
            texto += "¿Querés que cotice otro cliente o tenés alguna otra consulta?"
            session.adjuntos_pendientes = self._adjuntos_planes(planes)
            return texto

        resultados = []
        for plan in planes:
            resultado = self._calculator.cotizar(
                lead=lead,
                zona=zona,
                nombre_plan=plan,
                conceptos_obra_social=lead.conceptos_obra_social or None,
            )
            if resultado and resultado.valor_plan_total > 0:
                resultados.append(resultado)

        if not resultados:
            return (
                "Por el momento no tengo precios disponibles para armar la "
                "cotización de tu cliente. Comunicate con nosotros al "
                "0800-xxx-xxxx y te ayudamos."
            )

        texto = (
            f"¡Listo! Acá tenés la cotización para "
            f"*{lead.nombre or 'tu cliente'}*:\n\n"
        )
        for r in resultados:
            texto += f"📋 *Plan {r.plan.title()}*\n"
            texto += f"   💰 *${r.valor_a_pagar:,.2f}/mes*\n"
            bullets = self._bullets_plan(r.plan, 4)
            if bullets:
                for b in bullets:
                    texto += f"   ✓ {b}\n"
            else:
                texto += f"   {self._DESCRIPCIONES_PLANES.get(r.plan, '')}\n"
            if r.plan_joven_disponible:
                texto += "   🎉 Plan Joven disponible\n"
            texto += "\n"

        texto += "¿Querés que cotice otro cliente o tenés alguna otra consulta?"

        # Cartillas oficiales de los planes como respaldo (tras la info).
        session.adjuntos_pendientes = self._adjuntos_planes([r.plan for r in resultados])

        logger.info(
            "[CONVERSATION] Cotización vendedor generada — user=%s, cliente=%s, planes=%d",
            session.telegram_id, lead.nombre, len(resultados),
        )

        return texto

    def _handle_vendedor_cotizando_loop(self, session: UserSession, mensaje: str) -> str:
        """Interpreta la respuesta tras la cotización (otro cliente o salir)."""
        texto = _normalizar_localidad(mensaje).lower()

        if any(p in texto for p in ["otro", "otra cotizacion", "otro cliente"]):
            return self._reiniciar_cotizacion_vendedor(session)

        if any(p in texto for p in ["si", "dale", "claro", "vamos", "bueno", "genial"]) and not any(
            p in texto for p in ["no", "gracias"]
        ):
            return self._reiniciar_cotizacion_vendedor(session)

        if any(p in texto for p in [
            "no", "gracias", "nada", "termin", "eso es todo", "chau",
            "hasta luego", "adios",
        ]):
            return self._salir_modo_vendedor(session)

        return "¿Querés que cotice otro cliente o tenés alguna otra consulta?"

    def _reiniciar_cotizacion_vendedor(self, session: UserSession) -> str:
        """Prepara una nueva cotización de otro cliente sin salir del modo."""
        session.lead = Lead(lead_id=session.lead.lead_id)
        session.avanzar_etapa(EtapaConversacion.VENDEDOR_TIPO)
        return (
            "¡Genial! Decime: ¿la persona a cotizar es con recibo de "
            "sueldo, monotributo o directo? ¿O solo tenés una consulta?"
        )

    def _salir_modo_vendedor(self, session: UserSession) -> str:
        """Cierra el modo vendedor y vuelve al flujo de cliente."""
        session.es_vendedor = False
        session.lead = Lead(lead_id=session.lead.lead_id)
        session.avanzar_etapa(EtapaConversacion.NUEVO)
        return (
            "¡Listo! Salí del modo vendedor 😊. Cuando quieras cotizar otro "
            "cliente, escribime 'soy vendedor'."
        )

    # ─────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────

    def _datos_faltantes_para_cotizar(
        self, lead: Lead, vendedor: bool = False
    ) -> list[str]:
        """Lista los datos que faltan para poder cotizar.

        Args:
            lead: Lead con los datos ya recolectados.
            vendedor: Si es True, la pregunta se redacta para una persona
                distinta del usuario (ej: "¿cuántos años tiene la persona
                a cotizar?" en lugar de "¿cuántos años tenés?").
        """
        faltantes: list[str] = []

        if lead.localidad is None:
            faltantes.append(
                "de qué localidad es la persona a cotizar" if vendedor
                else "de qué localidad sos"
            )

        if lead.edad is None:
            faltantes.append(
                "cuántos años tiene la persona a cotizar" if vendedor
                else "cuántos años tenés"
            )

        if lead.tipo_afiliacion == TipoAfiliacion.MONOTRIBUTO:
            if lead.categoria_monotributo is None:
                faltantes.append(
                    "en qué categoría de monotributo está" if vendedor
                    else "en qué categoría de monotributo estás"
                )

        if lead.tipo_afiliacion == TipoAfiliacion.RELACION_DEPENDENCIA:
            if not lead.tiene_recibo_sueldo:
                faltantes.append(
                    "si tiene el recibo de sueldo a mano" if vendedor
                    else "si tenés el recibo de sueldo a mano"
                )
            elif not lead.conceptos_obra_social:
                faltantes.append(
                    "los conceptos de obra social del recibo "
                    "(ej: $15.000, $8.000)"
                )

        return faltantes

    def _handle_esperando_datos(self, session: UserSession, mensaje: str) -> str:
        """Recolecta datos restantes para cotizar: localidad, edad/categoría/recibo."""
        lead = session.lead
        lead.estado_comercial = EstadoComercial.CALIFICANDO

        # Extraer datos del mensaje
        from app.services.lead_qualifier import (
            _detectar_grupo_familiar,
            _extraer_edad,
            _extraer_localidad,
        )

        if lead.localidad is None:
            localidad = _extraer_localidad(mensaje)
            if localidad:
                lead.localidad = localidad

        if lead.edad is None:
            edad = _extraer_edad(mensaje)
            if edad:
                lead.edad = edad

        # Detectar grupo familiar si aún no está completo
        if not lead.grupo_familiar.conyuge and not lead.grupo_familiar.hijos:
            gf = _detectar_grupo_familiar(mensaje)
            if gf:
                lead.actualizar_grupo_familiar(
                    conyuge=gf["conyuge"],
                    hijos=gf["hijos"],
                    cantidad_hijos=gf["cantidad_hijos"],
                )

        # Detectar categoría de monotributo si aplica
        if lead.tipo_afiliacion == TipoAfiliacion.MONOTRIBUTO and lead.categoria_monotributo is None:
            import re
            match = re.search(r"categor[íi]a\s+([A-Ha-h])", mensaje, re.IGNORECASE)
            if match:
                lead.categoria_monotributo = match.group(1).upper()

        # Detectar recibo de sueldo si aplica
        if lead.tipo_afiliacion == TipoAfiliacion.RELACION_DEPENDENCIA:
            if self._detectar_recibo_sueldo(mensaje):
                lead.tiene_recibo_sueldo = True
                # Extraer conceptos solo cuando el mensaje menciona recibo
                if not lead.conceptos_obra_social:
                    conceptos = self._extraer_conceptos_obra_social(mensaje)
                    if conceptos:
                        lead.conceptos_obra_social = conceptos

        # Verificar si falta algo
        faltantes = self._datos_faltantes_para_cotizar(lead)

        if not faltantes:
            # Tiene todo → cotizar
            session.avanzar_etapa(EtapaConversacion.COTIZANDO)
            return self._handle_cotizando(session, mensaje)

        # UNA sola pregunta por mensaje — nunca combinar
        session.mensajes_en_etapa += 1
        return f"¿{faltantes[0].capitalize()}?"

    def _handle_cotizando(self, session: UserSession, mensaje: str) -> str:
        """Genera la cotización y presenta los planes con beneficios reales."""
        lead = session.lead
        lead.estado_comercial = EstadoComercial.INTERESADO

        zona = "cordoba"
        if "cordoba" not in _normalizar_localidad(lead.localidad):
            zona = "interior"

        descripciones = {
            "medimax": "Cobertura completa con consultas, estudios y odontología",
            "medimax gold": "Cobertura premium con mayores prestaciones y mejores descuentos",
            "medimax co": "Plan económico con las prestaciones esenciales al mejor precio",
        }

        if self._calculator is None:
            session.avanzar_etapa(EtapaConversacion.PRESENTANDO_VALOR)
            nombre = lead.nombre or ""
            texto = f"¡Perfecto {nombre}! Tenemos 3 planes para vos:\n\n"
            for plan in ["medimax", "medimax gold", "medimax co"]:
                texto += f"📋 *{plan.title()}*\n"
                bullets = self._bullets_plan(plan, 4)
                if bullets:
                    for b in bullets:
                        texto += f"   ✓ {b}\n"
                else:
                    texto += f"   {descripciones.get(plan, '')}\n"
                texto += "\n"
            texto += (
                "¿Querés que te cuente más detalles de algún plan "
                "o te parece bien alguno para avanzar?"
            )
            session.adjuntos_pendientes = self._adjuntos_planes(
                ["medimax", "medimax gold", "medimax co"]
            )
            return texto

        planes = ["medimax", "medimax gold", "medimax co"]
        resultados = []
        for plan in planes:
            resultado = self._calculator.cotizar(
                lead=lead,
                zona=zona,
                nombre_plan=plan,
                conceptos_obra_social=lead.conceptos_obra_social or None,
            )
            if resultado and resultado.valor_plan_total > 0:
                resultados.append(resultado)

        session.avanzar_etapa(EtapaConversacion.PRESENTANDO_VALOR)

        from app.services.commercial_memory import get_memory
        memory = get_memory()
        context = memory.get_or_create(lead.lead_id)
        context.cotizacion_realizada = True

        if not resultados:
            nombre = lead.nombre or ""
            return (
                f"{nombre}, por el momento no tengo precios disponibles. "
                "Comunicate con nosotros al 0800-xxx-xxxx y te asesoramos."
            )

        texto = "*Estos son los planes disponibles para vos:*\n\n"
        for r in resultados:
            texto += f"📋 *Plan {r.plan.title()}*\n"
            texto += f"   💰 *${r.valor_a_pagar:,.2f}/mes*\n"
            bullets = self._bullets_plan(r.plan, 5)
            if bullets:
                for b in bullets:
                    texto += f"   ✓ {b}\n"
            else:
                texto += f"   {descripciones.get(r.plan, '')}\n"
            if r.plan_joven_disponible:
                texto += "   🎉 Plan Joven disponible\n"
            texto += "\n"

        texto += (
            "¿Querés que te cuente más detalles de algún plan "
            "o te parece bien alguno para avanzar?"
        )

        # Cartillas oficiales de los planes como respaldo (tras la info).
        session.adjuntos_pendientes = self._adjuntos_planes([r.plan for r in resultados])

        logger.info(
            "[CONVERSATION] Cotización generada — user=%s, planes=%d",
            session.telegram_id, len(resultados),
        )

        return texto

    def _bullets_plan(self, plan: str, limite: int = 6) -> list[str]:
        """
        Extrae los beneficios principales (bullets) de un plan desde la
        cartilla oficial. Retorna hasta `limite` ítems.
        """
        detalle = self._detalle_plan(plan)
        bullets: list[str] = []
        for linea in detalle.splitlines():
            s = linea.strip()
            if s.startswith("-"):
                limpia = s.lstrip("- ").strip()
                if limpia:
                    bullets.append(limpia)
            if len(bullets) >= limite:
                break
        return bullets

    def _adjuntos_planes(self, planes: list[str]) -> list[str]:
        """PDFs de cartilla de los planes dados (solo rutas existentes)."""
        cartilla = getattr(self, "_cartilla", None)
        if cartilla is None:
            return []
        pdfs: list[str] = []
        for plan in planes:
            pdfs.extend(cartilla.plan_pdfs(plan))
        return list(dict.fromkeys(pdfs))

    def _detectar_plan_mencionado(self, mensaje: str) -> str | None:
        """
        Detecta qué plan de SERVIRED menciona el mensaje del cliente.

        Retorna el nombre normalizado del plan (clave de DB), o None si
        no menciona ningún plan específico.

        Orden de detección importante: "medimax gold" DEBE evaluarse
        antes que "gold", porque "medimax gold" contiene "gold".
        """
        import re

        texto = mensaje.lower()
        texto = re.sub(r"medimax\s+gold", "MEDIMAX_GOLD", texto)
        texto = re.sub(r"medimax\s+co", "MEDIMAX_CO", texto)

        if "MEDIMAX_GOLD" in texto:
            return "medimax_gold"
        if "MEDIMAX_CO" in texto:
            return "medimax_co"
        if "gold" in texto or "tope de gama" in texto:
            return "gold"
        if "medimax" in texto:
            return "medimax"
        return None

    def _cotizar_plan_especifico(self, session: UserSession, plan: str) -> str:
        """
        Cotiza y presenta un único plan que el cliente preguntó.

        Se usa cuando el cliente pregunta por un plan en particular
        (ej: "¿hay también un plan gold?") durante PRESENTANDO_VALOR.
        """
        lead = session.lead

        zona = "cordoba"
        if "cordoba" not in _normalizar_localidad(lead.localidad):
            zona = "interior"

        descripciones = {
            "medimax": "Cobertura completa con consultas, estudios y odontología",
            "medimax_gold": "Cobertura premium con mayores prestaciones y mejores descuentos",
            "medimax_co": "Plan económico con las prestaciones esenciales al mejor precio",
            "gold": "Tope de gama con la máxima cobertura y sin coseguros",
        }

        nombre_mostrar = {
            "medimax": "Medimax",
            "medimax_gold": "Medimax Gold",
            "medimax_co": "Medimax Co",
            "gold": "Gold",
        }.get(plan, plan.replace("_", " ").title())

        if self._calculator is None:
            texto = f"*Plan {nombre_mostrar}*\n"
            bullets = self._bullets_plan(plan, 8)
            if bullets:
                for b in bullets:
                    texto += f"   ✓ {b}\n"
            else:
                texto += f"   {descripciones.get(plan, '')}\n"
            texto += (
                "\n¿Querés que avancemos con este plan "
                "o necesitás que te cuente más detalles?"
            )
            session.adjuntos_pendientes = self._adjuntos_plan(plan)
            return texto

        resultado = self._calculator.cotizar(
            lead=lead,
            zona=zona,
            nombre_plan=plan,
            conceptos_obra_social=lead.conceptos_obra_social or None,
        )

        if not resultado or resultado.valor_plan_total <= 0:
            nombre = lead.nombre or ""
            return (
                f"{nombre}, por el momento no tengo el precio del plan "
                f"{nombre_mostrar} disponible. "
                "Comunicate con nosotros al 0800-xxx-xxxx y te asesoramos."
            )

        texto = f"*Plan {nombre_mostrar}*\n"
        bullets = self._bullets_plan(plan, 8)
        if bullets:
            for b in bullets:
                texto += f"   ✓ {b}\n"
        else:
            texto += f"   {descripciones.get(plan, '')}\n"
        texto += f"   💰 *${resultado.valor_a_pagar:,.2f}/mes*\n"
        if resultado.plan_joven_disponible:
            texto += "   🎉 Plan Joven disponible\n"
        texto += (
            "\n¿Querés que avancemos con la afiliación de este plan "
            "o necesitás más detalles?"
        )

        # Cartilla oficial del plan como respaldo (tras la info).
        session.adjuntos_pendientes = self._adjuntos_plan(plan)

        logger.info(
            "[CONVERSATION] Plan específico cotizado — user=%s, plan=%s",
            session.telegram_id, plan,
        )

        return texto

    def _detectar_recibo_sueldo(self, mensaje: str) -> bool:
        """Detecta si el mensaje menciona recibo de sueldo."""
        keywords = [
            "recibo de sueldo", "recibo", "sueldo", "boleta de pago",
            "conceptos obra social", "aportes obra social",
            "descuentos de obra social", "tengo recibo",
        ]
        mensaje_lower = mensaje.lower()
        return any(kw in mensaje_lower for kw in keywords)

    def _extraer_conceptos_obra_social(self, mensaje: str) -> list[float]:
        """
        Extrae montos de conceptos de obra social de un mensaje.

        Busca patrones como:
            - "$15.000" o "$15000"
            - "15000" o "15.000"
            - "obrasocial 15000"
        """
        import re
        montos: list[float] = []

        # Buscar montos con formato "$XX.XXX" o "$XXXXX"
        patron_dolar = re.findall(r'\$?([\d.,]+)', mensaje)
        for monto_str in patron_dolar:
            monto_limpio = monto_str.replace(".", "").replace(",", ".")
            try:
                monto = float(monto_limpio)
                if monto > 0:
                    montos.append(monto)
            except ValueError:
                continue

        # Si no encontró con $, buscar números sueltos que parezcan montos
        if not montos:
            patron_numeros = re.findall(r'(\d{3,})', mensaje)
            for num_str in patron_numeros:
                try:
                    num = float(num_str)
                    if num >= 100:
                        montos.append(num)
                except ValueError:
                    continue

        logger.debug(
            "[CONVERSATION] Conceptos obra social extraídos: %s",
            montos,
        )
        return montos

    def _generar_siguiente_pregunta(self, lead: Lead, proxima_pregunta: str) -> str:
        """Genera el texto de la siguiente pregunta. Siempre UNA sola pregunta."""
        preguntas = {
            "nombre": "¿Cómo te llamás?",
            "tipo_afiliacion": generar_pregunta_situacion_actual(),
            "grupo_familiar": generar_pregunta_grupo_familiar(),
            "localidad": "¿De qué localidad sos?",
            "edad": "¿Cuántos años tenés?",
        }

        return preguntas.get(proxima_pregunta, "¿Podés contarme un poco más?")

    # ─────────────────────────────────────────
    # IA helpers — AIService decide tono, empatía, persuasión
    # ─────────────────────────────────────────

    def _wrap_ia(
        self, respuesta: str, session: UserSession, mensaje: str,
        interpretacion: Any = None,
    ) -> str:
        """Envuelve una respuesta lógica con generación IA si está disponible."""
        return self._mejorar_respuesta_con_ia(
            lead=session.lead,
            etapa=session.etapa,
            mensaje=mensaje,
            respuesta_logica=respuesta,
            session=session,
            interpretacion=interpretacion,
        )

    # ─────────────────────────────────────────
    # Prestaciones — preguntas específicas en toda la conversación
    # ─────────────────────────────────────────

    def _responder_pregunta_prestacion(
        self, session: UserSession, mensaje: str
    ) -> str | None:
        """
        Responde preguntas específicas sobre beneficios/cartillas/prestaciones.

        Fuentes permitidas (en orden): DB → markdown oficial → web serviredsalud.
        Si no hay pregunta de prestaciones o dato disponible, retorna None
        para que la conversación continúe con el flujo normal.
        """
        try:
            resultado = self._prestaciones.responder(mensaje)
        except Exception as exc:
            logger.warning("[PRESTACIONES] Error analizando: %s", exc)
            return None

        if not resultado:
            return None

        respuesta, categoria = resultado
        retorno = self._retorno_objetivo(session)
        texto = f"{respuesta}\n\n{retorno}"

        # Cartilla oficial correspondiente como respaldo (tras la info).
        cartilla = getattr(self, "_cartilla", None)
        if cartilla is not None:
            session.adjuntos_pendientes = cartilla.categoria_pdfs(categoria, mensaje)

        logger.info(
            "[PRESTACIONES] user=%s, categoria=%s, respuesta=%d chars",
            session.telegram_id, categoria, len(texto),
        )
        return texto

    def _retorno_objetivo(self, session: UserSession) -> str:
        """Retoma el objetivo comercial según la etapa actual."""
        # Modo vendedor: retomar el loop de cotizaciones para clientes.
        if getattr(session, "es_vendedor", False):
            return "¿Querés que cotice otro cliente o tenés alguna otra consulta?"

        lead = session.lead
        nombre = lead.nombre or ""
        etapa = session.etapa

        if etapa in (
            EtapaConversacion.CALIFICANDO,
            EtapaConversacion.ESPERANDO_DATOS,
        ):
            if lead.tipo_afiliacion is None:
                return (
                    "¿Avanzamos con la propuesta? Decime cómo es tu situación "
                    "laboral (relación de dependencia, monotributo o particular) "
                    "y te armo la cotización."
                )
            faltantes = self._datos_faltantes_para_cotizar(lead)
            if faltantes:
                return (
                    f"Decime {faltantes[0]} y te armo la cotización "
                    "con estos beneficios."
                )

        if etapa in (
            EtapaConversacion.PRESENTANDO_VALOR,
            EtapaConversacion.COTIZANDO,
            EtapaConversacion.MANEJANDO_OBJECIONES,
            EtapaConversacion.INTENTANDO_CIERRE,
        ):
            return (
                "¿Te pareció bien la propuesta que te mostré? "
                "Si querés, avanzamos con la afiliación."
            )

        # NUEVO / DESCUBRIENDO_NECESIDAD
        if nombre:
            return (
                f"¿Avanzamos {nombre}? Decime cómo es tu situación laboral "
                "(relación de dependencia, monotributo o particular) "
                "y te armo la propuesta."
            )
        return (
            "¿Avanzamos? Decime cómo es tu situación laboral "
            "(relación de dependencia, monotributo o particular) "
            "y te armo la propuesta."
        )

    # ─────────────────────────────────────────
    # Saludos — humanización sin perder el objetivo comercial
    # ─────────────────────────────────────────

    _SALUDOS_PUROS = {
        "hola", "hola sofia", "buenas", "buenos dias", "buen dia",
        "buenas tardes", "buenas noches", "hola buenas", "hello", "hi", "hey",
        "hola de nuevo", "hola nuevamente", "hola otra vez", "buenas de nuevo",
        "hola como estas", "como estas", "como andas", "que tal", "holi",
    }

    def _es_saludo_puro(self, mensaje: str) -> bool:
        """Detecta si el mensaje es un saludo simple (sin otro contenido)."""
        import re

        if not mensaje:
            return False
        texto = _normalizar_localidad(mensaje).lower()
        texto = re.sub(r"[^a-z0-9 ]", " ", texto)
        texto = " ".join(texto.split())
        return texto in self._SALUDOS_PUROS

    def _responder_saludo(self, session: UserSession) -> str:
        """
        Responde un saludo de un usuario que ya está en la conversación.

        Humaniza (no suena a máquina) y retoma el objetivo comercial
        según la etapa actual, sin cambiar la etapa.
        """
        lead = session.lead
        nombre = lead.nombre or ""
        saludo = f"¡Hola {nombre}!" if nombre else "¡Hola!"
        retorno = self._retorno_objetivo(session)
        return f"{saludo} 😊 {retorno}"

    # ─────────────────────────────────────────
    # Detalle de planes — información real de las cartillas
    # ─────────────────────────────────────────

    def _detalle_plan(self, plan: str) -> str:
        """
        Devuelve los beneficios reales de un plan desde las cartillas
        oficiales (DB → markdown). Vacío si no hay sección disponible.
        """
        prestaciones = getattr(self, "_prestaciones", None)
        if prestaciones is None:
            return ""
        try:
            return prestaciones.detalle_plan(plan) or ""
        except Exception as exc:
            logger.warning("[CARTILLA] Error obteniendo detalle del plan %s: %s", plan, exc)
            return ""

    def _adjuntos_plan(self, plan: str) -> list[str]:
        """PDFs de cartilla para adjuntar tras detallar un plan."""
        cartilla = getattr(self, "_cartilla", None)
        if cartilla is None:
            return []
        return cartilla.plan_pdfs(plan)

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
        session: Any = None,
        interpretacion: Any = None,
    ) -> str:
        """Usa la IA para mejorar la respuesta lógica con lenguaje natural."""
        if self.ai is None or not self.ai.disponible:
            return respuesta_logica

        # ── Sincronizar estado en memoria ANTES de que el Director decida ──
        # El CM ya avanzó la etapa. Reflejar en memoria para que el Director
        # vea el estado real y decida estrategia (nunca COTIZAR de nuevo).
        from app.services.commercial_memory import get_memory
        memory = get_memory()
        context = memory.get_or_create(lead.lead_id)
        cotizacion_prev = context.cotizacion_realizada
        if session and session.etapa == EtapaConversacion.PRESENTANDO_VALOR:
            context.cotizacion_realizada = True

        # ── Director decide el objetivo estratégico ──
        objetivo = self._director.decidir(lead, context, interpretacion)

        logger.debug(
            "[DIRECTOR] user=%s, objetivo=%s, dato=%s, razon=%s",
            session.telegram_id if session else "?",
            objetivo.accion, objetivo.dato_requerido or "-",
            objetivo.razon[:60],
        )

        # TODAS las acciones del Director devuelven la respuesta del handler
        # directamente. El LLM NUNCA mejora respuestas comerciales porque:
        #   - El identity prompt incluye "Perfecto, voy a calcular cuánto pagarías"
        #     (commercial_prompt_builder.py:168) → la LLM repite esa frase
        #   - El Orchestrator llama al LLM ANTES que el Director → memory se
        #     corrompe si el LLM devuelve `accion=COTIZAR`
        #   - Las sesiones corruptas (cotizacion_realizada=True sin planes)
        #     caían al LLM y generaban "Voy a calcular..."
        #
        # Excepciones controladas (ejecutan handler específico):
        #   COTIZAR → _handle_cotizando() genera los 3 planes reales
        #   PRESENTAR_VALOR → si respuesta_logica no tiene planes, forzar recálculo

        if objetivo.accion == "COTIZAR":
            context.cotizacion_realizada = True
            session.avanzar_etapa(EtapaConversacion.COTIZANDO)
            return self._handle_cotizando(session, mensaje)

        if objetivo.accion == "PRESENTAR_VALOR":
            # Solo forzar recálculo si el handler NO avanzó la etapa
            # (ej: _handle_valor() pudo haber avanzado a MANEJANDO_OBJECIONES)
            from app.services.commercial_prompt_builder import has_real_plans
            if session.etapa == EtapaConversacion.PRESENTANDO_VALOR:
                if not has_real_plans(respuesta_logica):
                    session.avanzar_etapa(EtapaConversacion.COTIZANDO)
                    return self._handle_cotizando(session, mensaje)

        return respuesta_logica

        # ── PromptBuilder con objetivo obligatorio ──
        try:
            from app.services.commercial_prompt_builder import CommercialPromptBuilder
            builder = CommercialPromptBuilder()
            knowledge = self._obtener_knowledge_para_etapa(lead, etapa, mensaje)
            historial = self._obtener_historial(session) if session else []

            prompt = builder.build(
                lead=lead,
                historial=historial,
                mensaje=mensaje,
                etapa=etapa,
                knowledge=knowledge,
                datos_faltantes=objetivo.todos_faltantes,
                context=context,
                objetivo=objetivo,
            )

            resultado_llm = self.ai._client.generar_respuesta(
                mensajes=prompt,
                temperatura=0.3,
                max_tokens=500,
            )

            if resultado_llm.exito and resultado_llm.texto:
                logger.debug(
                    "[AI+DIRECTOR] Respuesta generada (%d chars) — objetivo=%s",
                    len(resultado_llm.texto), objetivo.accion,
                )
                return resultado_llm.texto

        except Exception as e:
            logger.warning("[AI+DIRECTOR] Error: %s", e, exc_info=True)

        # ── Fallback: respuesta lógica del handler ──
        return respuesta_logica

    # ─────────────────────────────────────────
    # DB helpers
    # ─────────────────────────────────────────

    def _cargar_lead_desde_db(self, telegram_id: int, session: UserSession) -> bool:
        """Carga el lead persistido desde la DB si existe. Retorna True si encontró lead."""
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
                            etapa_db = EtapaConversacion(
                                lead_db.etapa_conversacion
                            )
                            logger.warning(
                                "[FLOW] DB_LOAD — user=%s, etapa_db='%s', "
                                "nombre='%s', estado='%s', "
                                "SOBREESCRIBE session.etapa anterior='%s'",
                                telegram_id, lead_db.etapa_conversacion,
                                lead_domain.nombre,
                                lead_domain.estado_comercial.value,
                                session.etapa.value,
                            )
                            session.etapa = etapa_db
                            if session.etapa in self._ETAPAS_VENDEDOR:
                                session.es_vendedor = True
                        except ValueError:
                            logger.error(
                                "[FLOW] DB_LOAD — user=%s, etapa_db='%s' "
                                "NO ES VALIDA en EtapaConversacion",
                                telegram_id, lead_db.etapa_conversacion,
                            )
                    logger.info(
                        "[DATABASE] Lead cargado — id=%s, nombre=%s, etapa=%s, estado=%s",
                        telegram_id, lead_domain.nombre,
                        session.etapa.value,
                        lead_domain.estado_comercial.value,
                    )
                    return True
                return False
            finally:
                db.close()
        except Exception as e:
            logger.warning("[DATABASE] Error cargando lead: %s", e)
            return False

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
