"""
Commercial AI Orchestrator — Sprint 21.5.

Orquestador comercial con razonamiento de ventas Y memoria persistente.

NO calcula. NO accede a Excel. NO consulta precios directamente.
Su función es razonar, decidir qué acción tomar, validar la respuesta
Y mantener la memoria comercial viva durante toda la conversación.

Flujo:
    ConversationManager → Orchestrator.analizar() → OrchestrationResult
    ConversationManager usa el resultado para ejecutar la acción correspondiente.

Sprint 21:
    - Acciones reducidas a5: PEDIR_DATO, COTIZAR, ARGUMENTAR, MANEJAR_OBJECION, CERRAR
    - Autocrítica antes de enviar respuesta
    - Mejor detección de objeciones y cierre

Sprint 21.5:
    - CommercialMemory integrada
    - PromptBuilder recibe contexto de memoria
    - Datos confirmados nunca se vuelven a pedir
    - Objetivo y próximo objetivo persisten
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from app.models.lead import Lead, TipoAfiliacion
from app.services.session_manager import EtapaConversacion

logger = logging.getLogger(__name__)


ACCIONES_VALIDAS = frozenset({
    "PEDIR_DATO", "COTIZAR", "ARGUMENTAR", "MANEJAR_OBJECION", "CERRAR",
})


@dataclass
class OrchestrationResult:
    """
    Resultado estructurado del razonamiento del Orchestrator.

    Attributes:
        intencion: Qué quiso decir realmente el cliente.
        datos_detectados: Datos nuevos extraídos del mensaje.
        datos_faltantes: Datos que faltan para cotizar.
        accion: Acción comercial a ejecutar.
        argumento: Enfoque específico a usar.
        tono: Tono de la respuesta.
        respuesta: Respuesta natural generada por la IA.
    """
    intencion: str = ""
    datos_detectados: dict[str, Any] = field(default_factory=dict)
    datos_faltantes: list[str] = field(default_factory=list)
    accion: str = "PEDIR_DATO"
    argumento: str = ""
    tono: str = "friendly"
    respuesta: str = ""


class CommercialAIOrchestrator:
    """
    Orquestador comercial con razonamiento de ventas.

    Analiza cada mensaje del cliente y decide:
        - Qué quiso decir realmente
        - Qué datos ya tenemos y cuáles faltan
        - Cuál es la siguiente acción comercial
        - Cómo responder de forma natural

    Valida la respuesta con autocrítica antes de devolverla.

    No genera precios ni calcula nada.
    Solo razona, decide y valida.
    """

    # ── Patrones de intención ──
    _PATRONES_COTIZAR: frozenset[str] = frozenset({
        "cotizar", "cotice", "cotización", "precio", "precios",
        "cuánto", "cuanto", "costo", "vale", "cuesta",
        "querés saber", "contame", "decime",
        "cuánto cuesta", "cuánto sale",
        "quiero información", "info", "información",
        "osde", "nóbis", "nobis", "swiss", "medimax",
        "aumentó", "subió",
    })

    _PATRONES_OBJECION: frozenset[str] = frozenset({
        "caro", "barato", "costoso", "muy alto", "no llego",
        "no puedo pagar", "no me da", "no estoy seguro", "no sé si",
        "necesito pensar", "lo voy a pensar",
        "después", "mañana", "no tengo tiempo",
        "no conozco", "nunca escuché",
        "no me da confianza", "dudando",
        "no estoy convencido", "no sé",
        "tengo que pensarlo", "lo pienso",
        "pago mucho", "estoy pagando mucho", "muy caro",
        "necesito algo más barato", "algo más barato",
        "me gustaría algo más económico",
    })

    _PATRONES_CIERRE: frozenset[str] = frozenset({
        "dale", "avanzamos", "quiero", "contratar",
        "afiliarme", "dame", "tomalo", "sí",
        "ok", "perfecto", "excelente", "genial",
        "hacelo", "arrancamos", "empezamos",
        "estoy listo", "estoy dentro", "metele",
        "sí quiero", "dale avance", "sigamos",
    })

    def __init__(
        self,
        ai_service: Any = None,
        knowledge_engine: Any = None,
        knowledge_service: Any = None,
    ) -> None:
        """
        Inicializa el Orchestrator.

        Args:
            ai_service: AIService para generar respuestas con LLM.
            knowledge_engine: KnowledgeEngine (DB) para contexto.
            knowledge_service: KnowledgeService (archivos) como fallback.
        """
        self._ai = ai_service
        self._knowledge_engine = knowledge_engine
        self._knowledge = knowledge_service

        # Importar servicios de forma lazy
        from app.services.commercial_prompt_builder import CommercialPromptBuilder
        from app.services.commercial_memory import get_memory
        self._prompt_builder = CommercialPromptBuilder()
        self._memory = get_memory()

        logger.info(
            "[ORCHESTRATOR] Inicializado — ai=%s, knowledge_db=%s, memory=enabled",
            "enabled" if ai_service and ai_service.disponible else "disabled",
            "enabled" if knowledge_engine else "disabled",
        )

    def analizar(
        self,
        lead: Lead,
        historial: list[dict[str, str]],
        mensaje: str,
        etapa: EtapaConversacion,
        datos_faltantes: list[str] | None = None,
    ) -> OrchestrationResult:
        """
        Analiza el mensaje del cliente y devuelve razonamiento estructurado.

        Este es el punto de entrada principal. La IA analiza:
        1. Qué quiso decir realmente el cliente
        2. Qué datos ya tenemos (desde memoria)
        3. Qué falta
        4. Cuál es la siguiente acción comercial
        5. Cómo responder
        6. Valida la respuesta con autocrítica

        Args:
            lead: Lead con todos los datos del cliente.
            historial: Lista de {"role": "user"/"assistant", "content": "..."}.
            mensaje: Último mensaje del cliente.
            etapa: Etapa actual de la conversación.
            datos_faltantes: Lista pre-computada de datos faltantes.

        Returns:
            OrchestrationResult con razonamiento estructurado.
        """
        # ── Obtener o crear contexto de memoria ──
        context = self._memory.get_or_create(lead.lead_id)
        self._memory.actualizar(
            lead=lead, mensaje=mensaje, accion="",
            datos_faltantes=datos_faltantes,
        )
        context = self._memory.get_or_create(lead.lead_id)

        # Usar faltantes de memoria si no se proveen
        if datos_faltantes is None:
            datos_faltantes = context.datos_faltantes

        # Obtener knowledge context
        knowledge = self._obtener_knowledge(lead, etapa, mensaje)

        # Intentar razonamiento con IA
        resultado_ai = self._razonar_con_ia(
            lead, historial, mensaje, etapa, knowledge,
            datos_faltantes, context,
        )
        if resultado_ai is not None:
            self._memory.actualizar(
                lead=lead, mensaje=mensaje,
                accion=resultado_ai.accion,
                datos_detectados=resultado_ai.datos_detectados,
                datos_faltantes=resultado_ai.datos_faltantes,
                respuesta=resultado_ai.respuesta,
            )
            return resultado_ai

        # Fallback: razonamiento basado en reglas
        resultado_reglas = self._razonar_con_reglas(
            lead, mensaje, etapa, datos_faltantes, context
        )

        # Autocrítica del resultado de reglas
        resultado_reglas = self._autocritica(
            resultado_reglas, lead, historial, mensaje, etapa, context
        )

        # Actualizar memoria
        self._memory.actualizar(
            lead=lead, mensaje=mensaje,
            accion=resultado_reglas.accion,
            datos_detectados=resultado_reglas.datos_detectados,
            datos_faltantes=resultado_reglas.datos_faltantes,
            respuesta=resultado_reglas.respuesta,
        )

        return resultado_reglas

    def _razonar_con_ia(
        self,
        lead: Lead,
        historial: list[dict[str, str]],
        mensaje: str,
        etapa: EtapaConversacion,
        knowledge: str,
        datos_faltantes: list[str] | None,
        context: Any = None,
    ) -> OrchestrationResult | None:
        """Intenta razonar usando el LLM. Retorna None si falla."""
        if not self._ai or not self._ai.disponible:
            return None

        try:
            prompt = self._prompt_builder.build(
                lead=lead,
                historial=historial,
                mensaje=mensaje,
                etapa=etapa,
                knowledge=knowledge,
                datos_faltantes=datos_faltantes,
                context=context,
            )

            resultado_llm = self._ai._client.generar_respuesta(
                mensajes=prompt,
                temperatura=0.3,
                max_tokens=500,
            )

            if resultado_llm.exito and resultado_llm.texto:
                resultado = self._parsear_respuesta(resultado_llm.texto)

                # Autocrítica del resultado de IA
                resultado = self._autocritica(
                    resultado, lead, historial, mensaje, etapa, context
                )

                logger.info(
                    "[ORCHESTRATOR] IA razonó — accion=%s, intencion=%s, "
                    "datos_nuevos=%d, faltantes=%d",
                    resultado.accion, resultado.intencion[:40],
                    len(resultado.datos_detectados),
                    len(resultado.datos_faltantes),
                )
                return resultado

        except Exception as e:
            logger.warning("[ORCHESTRATOR] Error en IA: %s", e, exc_info=True)

        return None

    def _parsear_respuesta(self, texto: str) -> OrchestrationResult:
        """
        Parsea la respuesta JSON del LLM.

        Si el JSON no es válido, intenta extraer campos manualmente.
        Si todo falla, devuelve un resultado básico con el texto.
        """
        try:
            # Buscar JSON en la respuesta
            start = texto.find("{")
            end = texto.rfind("}") + 1

            if start >= 0 and end > start:
                json_str = texto[start:end]
                data = json.loads(json_str)

                accion = data.get("accion", "PEDIR_DATO").upper()
                if accion not in ACCIONES_VALIDAS:
                    accion = "PEDIR_DATO"

                return OrchestrationResult(
                    intencion=data.get("intencion", ""),
                    datos_detectados=data.get("datos_detectados", {}),
                    datos_faltantes=data.get("datos_faltantes", []),
                    accion=accion,
                    argumento=data.get("argumento", ""),
                    tono=data.get("tono", "friendly"),
                    respuesta=data.get("respuesta", texto[:300]),
                )

        except (json.JSONDecodeError, AttributeError, TypeError) as e:
            logger.debug("[ORCHESTRATOR] JSON parse failed: %s", e)

        # Fallback: usar el texto completo como respuesta
        return OrchestrationResult(
            intencion="no_parseable",
            accion="PEDIR_DATO",
            respuesta=texto[:300],
        )

    def _razonar_con_reglas(
        self,
        lead: Lead,
        mensaje: str,
        etapa: EtapaConversacion,
        datos_faltantes: list[str] | None = None,
        context: Any = None,
    ) -> OrchestrationResult:
        """
        Razonamiento basado en reglas (fallback cuando no hay IA).

        Implementa la lógica comercial sin LLM.
        """
        mensaje_lower = mensaje.lower().strip()

        # ── Detectar objeciones (prioridad sobre todo) ──
        if any(kw in mensaje_lower for kw in self._PATRONES_OBJECION):
            return OrchestrationResult(
                intencion="objecion_detectada",
                accion="MANEJAR_OBJECION",
                tono="empathetic",
                respuesta=(
                    "Entiendo tu preocupación. Déjame explicarte "
                    "por qué nuestros planes son una buena opción para vos."
                ),
            )

        # ── Detectar cierre (prioridad sobre pedir datos) ──
        if any(kw in mensaje_lower for kw in self._PATRONES_CIERRE):
            if etapa in (
                EtapaConversacion.PRESENTANDO_VALOR,
                EtapaConversacion.INTENTANDO_CIERRE,
                EtapaConversacion.MANEJANDO_OBJECIONES,
            ):
                return OrchestrationResult(
                    intencion="interes_en_cierre",
                    accion="CERRAR",
                    tono="professional",
                    respuesta=(
                        "¡Excelente! Un asesor se comunicará con vos "
                        "para completar el proceso. ¡Bienvenido a Servired!"
                    ),
                )

        # ── Detectar intención de cotizar ──
        if any(kw in mensaje_lower for kw in self._PATRONES_COTIZAR):
            # Si tiene datos faltantes, pedir
            if datos_faltantes:
                return OrchestrationResult(
                    intencion="quiere_cotizar_datos_faltantes",
                    datos_faltantes=datos_faltantes,
                    accion="PEDIR_DATO",
                    tono="professional",
                    respuesta=self._generar_pregunta(datos_faltantes[0]),
                )
            # Si tiene tipo de afiliación, cotizar
            if lead.tipo_afiliacion:
                return OrchestrationResult(
                    intencion="quiere_cotizar",
                    accion="COTIZAR",
                    tono="professional",
                    respuesta="Con tus datos, te preparo la cotización.",
                )

        # ── Pedir datos faltantes ──
        if datos_faltantes:
            return OrchestrationResult(
                intencion="datos_incompletos",
                datos_faltantes=datos_faltantes,
                accion="PEDIR_DATO",
                tono="friendly",
                respuesta=self._generar_pregunta(datos_faltantes[0]),
            )

        # ── Datos completos → cotizar ──
        if not datos_faltantes and lead.tipo_afiliacion:
            return OrchestrationResult(
                intencion="datos_completos",
                accion="COTIZAR",
                tono="professional",
                respuesta="Con tus datos, te preparo la cotización.",
            )

        # ── Default: pedir dato relevante ──
        return OrchestrationResult(
            intencion="avanzar_calificacion",
            accion="PEDIR_DATO",
            tono="friendly",
            respuesta=self._generar_pregunta_default(lead),
        )

    def _generar_pregunta(self, dato: str) -> str:
        """Genera una pregunta natural para el dato faltante."""
        preguntas = {
            "localidad": "¿De qué localidad sos?",
            "edad": "¿Cuántos años tenés?",
            "categoría de monotributo": "¿En qué categoría de monotributo estás?",
            "recibo de sueldo": "¿Tenés el recibo de sueldo a mano?",
            "conceptos de obra social del recibo": (
                "¿Me pasás los conceptos de obra social del recibo? "
                "Por ejemplo: $15.000, $8.000"
            ),
            "nombre": "¿Cómo te llamás?",
            "tipo afiliación": (
                "¿Cómo es tu situación laboral? "
                "(relación de dependencia, monotributo o particular)"
            ),
            "grupo familiar": (
                "¿La cobertura sería solo para vos o incluye a tu familia?"
            ),
        }
        return preguntas.get(dato, f"Necesito saber: {dato}")

    def _generar_pregunta_default(self, lead: Lead) -> str:
        """Genera una pregunta por defecto según el estado del lead."""
        if not lead.nombre:
            return "¿Cómo te llamás?"
        if not lead.tipo_afiliacion:
            return (
                "¿Cómo es tu situación laboral? "
                "(relación de dependencia, monotributo o particular)"
            )
        if not lead.edad:
            return "¿Cuántos años tenés?"
        if not lead.localidad:
            return "¿De qué localidad sos?"
        return "Contame un poco más sobre lo que necesitás."

    def _autocritica(
        self,
        resultado: OrchestrationResult,
        lead: Lead,
        historial: list[dict[str, str]],
        mensaje: str,
        etapa: EtapaConversacion,
        context: Any = None,
    ) -> OrchestrationResult:
        """
        Valida la respuesta con autocrítica.

        6 puntos de validación:
        1. ¿Estoy repitiendo algo que ya dije?
        2. ¿Estoy saludando de nuevo?
        3. ¿Estoy preguntando algo que ya sé?
        4. ¿Me estoy desviando del tema?
        5. ¿Estoy inventando información?
        6. ¿Esta respuesta acerca al cliente a la afiliación?

        Si falla alguna validación, intenta corregir.
        """
        if not resultado.respuesta:
            return resultado

        respuesta_lower = resultado.respuesta.lower()

        # 1. ¿Repite saludo?
        if resultado.accion not in ("PEDIR_DATO", "COTIZAR", "ARGUMENTAR",
                                     "MANEJAR_OBJECION", "CERRAR"):
            # Acción inválida → corregir
            if datos_faltantes := resultado.datos_faltantes:
                resultado.accion = "PEDIR_DATO"
                resultado.respuesta = self._generar_pregunta(datos_faltantes[0])
            elif lead.tipo_afiliacion:
                resultado.accion = "COTIZAR"
                resultado.respuesta = "Con tus datos, te preparo la cotización."
            else:
                resultado.accion = "PEDIR_DATO"
                resultado.respuesta = self._generar_pregunta_default(lead)

        # 2. ¿Ya saludó?
        if etapa != EtapaConversacion.NUEVO:
            saludos = ["¡hola", "hola!", "buenos días", "buenas tardes",
                       "qué tal"]
            for saludo in saludos:
                if saludo in respuesta_lower:
                    # Reemplazar saludo por acción comercial
                    if lead.tipo_afiliacion:
                        resultado.accion = "PEDIR_DATO"
                        resultado.respuesta = self._generar_pregunta(
                            resultado.datos_faltantes[0]
                            if resultado.datos_faltantes
                            else "nombre"
                        )
                    elif lead.nombre:
                        resultado.accion = "PEDIR_DATO"
                        resultado.respuesta = (
                            "¿Cómo es tu situación laboral? "
                            "(relación de dependencia, monotributo o particular)"
                        )
                    break

        # 3. ¿Pregunta algo que ya sabe?
        if lead.nombre and "¿cómo te llamás" in respuesta_lower:
            resultado.respuesta = resultado.respuesta.replace(
                "¿Cómo te llamás?", "¿En qué te puedo ayudar?"
            )

        if lead.edad and "¿cuántos años tenés" in respuesta_lower:
            resultado.respuesta = resultado.respuesta.replace(
                "¿Cuántos años tenés?", "¿De qué localidad sos?"
            )

        if lead.localidad and "¿de qué localidad sos" in respuesta_lower:
            resultado.respuesta = resultado.respuesta.replace(
                "¿De qué localidad sos?", "¿Tenés el recibo de sueldo a mano?"
            )

        # 4. ¿Se desvía del tema?
        if etapa in (
            EtapaConversacion.PRESENTANDO_VALOR,
            EtapaConversacion.INTENTANDO_CIERRE,
            EtapaConversacion.MANEJANDO_OBJECIONES,
        ):
            desviaciones = ["contame sobre vos", "cuéntame de ti",
                            "¿qué hacés?", "¿a qué te dedicás?"]
            for desv in desviaciones:
                if desv in respuesta_lower:
                    resultado.accion = "ARGUMENTAR"
                    resultado.respuesta = (
                        "Vamos a enfocarnos en tu cotización. "
                        "¿Qué necesitás saber para avanzar?"
                    )
                    break

        # 5. ¿Inventa información?
        inventos = ["promoción especial", "oferta limitada", "solo hoy",
                    "precio especial", "descuento exclusivo"]
        for invento in inventos:
            if invento in respuesta_lower:
                resultado.respuesta = (
                    "Con tus datos, te preparo la cotización "
                    "y ves exactamente cuánto pagarías."
                )
                resultado.accion = "COTIZAR" if lead.tipo_afiliacion else "PEDIR_DATO"
                break

        # 6. ¿Acerca al cierre?
        if etapa == EtapaConversacion.PRESENTANDO_VALOR:
            preguntas_desviadas = ["¿te interesa?", "¿querés saber más?",
                                   "¿algo más?", "¿otra cosa?"]
            for preg in preguntas_desviadas:
                if preg in respuesta_lower:
                    resultado.accion = "CERRAR"
                    resultado.respuesta = (
                        "¿Querés que avance con el proceso de afiliación?"
                    )
                    break

        # 7. No preguntar datos confirmados (memoria)
        if context is not None:
            resultado = self._no_preguntar_confirmados(resultado, context)

        return resultado

    def _no_preguntar_confirmados(
        self, resultado: OrchestrationResult, context: Any
    ) -> OrchestrationResult:
        """
        Si la IA pregunta un dato que la memoria ya confirmó, reemplaza.

        Args:
            resultado: Resultado a validar.
            context: CommercialConversationContext con datos confirmados.

        Returns:
            Resultado corregido.
        """
        if not context.datos_confirmados:
            return resultado

        respuesta_lower = resultado.respuesta.lower()

        # Mapa de preguntas → campo confirmado
        _preguntas_a_campo = {
            "¿cómo te llamás": "nombre",
            "¿cuántos años tenés": "edad",
            "¿de qué localidad sos": "localidad",
            "situación laboral": "tipo_afiliacion",
            "relación de dependencia": "tipo_afiliacion",
            "monotributo o particular": "tipo_afiliacion",
            "¿en qué categoría": "categoria_monotributo",
            "recibo de sueldo": "recibo",
            "conceptos de obra social": "conceptos_obra_social",
            "grupo familiar": "grupo_familiar",
            "solo para vos": "grupo_familiar",
        }

        for pregunta, campo in _preguntas_a_campo.items():
            if pregunta in respuesta_lower and context.ya_tiene(campo):
                # Dato confirmado — no preguntar de nuevo
                # Reemplazar por el siguiente paso
                if context.datos_faltantes:
                    siguiente = context.datos_faltantes[0]
                    resultado.respuesta = self._generar_pregunta(siguiente)
                elif context.tipo_afiliacion:
                    resultado.accion = "COTIZAR"
                    resultado.respuesta = "Con tus datos, te preparo la cotización."
                break

        return resultado

    def _obtener_knowledge(
        self, lead: Lead, etapa: EtapaConversacion, mensaje: str
    ) -> str:
        """Obtiene contexto del Knowledge Engine."""
        partes: list[str] = []

        # Priority 1: KnowledgeEngine (DB)
        if self._knowledge_engine is not None:
            try:
                ctx = self._knowledge_engine.contexto_para_lead(
                    lead, etapa.value, mensaje
                )
                if ctx:
                    partes.append(ctx)
            except Exception as e:
                logger.debug("[ORCHESTRATOR] Error knowledge_engine: %s", e)

        # Priority 2: KnowledgeService (archivos)
        if self._knowledge is not None:
            try:
                ctx = self._knowledge.contexto_para_lead(
                    lead, etapa.value, mensaje
                )
                if ctx:
                    partes.append(ctx)
            except Exception as e:
                logger.debug("[ORCHESTRATOR] Error knowledge_service: %s", e)

        return "\n\n".join(partes)[:2000]
