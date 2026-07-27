"""
Commercial AI Orchestrator — Sprint 20.

Orquestador comercial que razona antes de responder.

NO calcula. NO accede a Excel. NO consulta precios directamente.
Su única función es razonar y decidir qué acción tomar.

Flujo:
    ConversationManager → Orchestrator.analizar() → OrchestrationResult
    ConversationManager usa el resultado para ejecutar la acción correspondiente.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from app.models.lead import Lead
from app.services.session_manager import EtapaConversacion

logger = logging.getLogger(__name__)


ACCIONES_VALIDAS = frozenset({
    "PEDIR_DATO", "CALCULAR", "ARGUMENTAR", "MANEJAR_OBJECION",
    "CERRAR", "SALUDAR", "INFORMAR", "DERIVAR",
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
    accion: str = "INFORMAR"
    argumento: str = ""
    tono: str = "friendly"
    respuesta: str = ""


class CommercialAIOrchestrator:
    """
    Orquestador comercial con razonamiento IA.

    Analiza cada mensaje del cliente y decide:
        - Qué quiso decir realmente
        - Qué datos ya tenemos y cuáles faltan
        - Cuál es la siguiente acción comercial
        - Cómo responder de forma natural

    No genera precios ni calcula nada.
    Solo razona y decide qué servicio invocar.
    """

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

        # Importar prompt builder de forma lazy
        from app.services.commercial_prompt_builder import CommercialPromptBuilder
        self._prompt_builder = CommercialPromptBuilder()

        logger.info(
            "[ORCHESTRATOR] Inicializado — ai=%s, knowledge_db=%s",
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
        2. Qué datos ya tenemos
        3. Qué falta
        4. Cuál es la siguiente acción comercial
        5. Cómo responder

        Args:
            lead: Lead con todos los datos del cliente.
            historial: Lista de {"role": "user"/"assistant", "content": "..."}.
            mensaje: Último mensaje del cliente.
            etapa: Etapa actual de la conversación.
            datos_faltantes: Lista pre-computada de datos faltantes.

        Returns:
            OrchestrationResult con razonamiento estructurado.
        """
        # Obtener knowledge context
        knowledge = self._obtener_knowledge(lead, etapa, mensaje)

        # Intentar razonamiento con IA
        resultado_ai = self._razonar_con_ia(
            lead, historial, mensaje, etapa, knowledge, datos_faltantes
        )
        if resultado_ai is not None:
            return resultado_ai

        # Fallback: razonamiento basado en reglas
        return self._razonar_con_reglas(lead, mensaje, etapa, datos_faltantes)

    def _razonar_con_ia(
        self,
        lead: Lead,
        historial: list[dict[str, str]],
        mensaje: str,
        etapa: EtapaConversacion,
        knowledge: str,
        datos_faltantes: list[str] | None,
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
            )

            resultado_llm = self._ai._client.generar_respuesta(
                mensajes=prompt,
                temperatura=0.3,
                max_tokens=500,
            )

            if resultado_llm.exito and resultado_llm.texto:
                resultado = self._parsear_respuesta(resultado_llm.texto)
                logger.info(
                    "[ORCHESTRATOR] IA razonó — accion=%s, intencion=%s, "
                    "datos_nuevos=%d, faltantes=%d",
                    resultado.accion, resultado.intencion[:40],
                    len(resultado.datos_detectados),
                    len(resultado.datos_faltantes),
                )
                return resultado

        except Exception as e:
            logger.warning("[ORCHESTRATOR] Error en IA: %s", e)

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

                accion = data.get("accion", "INFORMAR").upper()
                if accion not in ACCIONES_VALIDAS:
                    accion = "INFORMAR"

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
            accion="INFORMAR",
            respuesta=texto[:300],
        )

    def _razonar_con_reglas(
        self,
        lead: Lead,
        mensaje: str,
        etapa: EtapaConversacion,
        datos_faltantes: list[str] | None = None,
    ) -> OrchestrationResult:
        """
        Razonamiento basado en reglas (fallback cuando no hay IA).

        Implementa la lógica comercial sin LLM.
        """
        mensaje_lower = mensaje.lower()

        # ── NUEVO: Primer contacto ──
        if etapa == EtapaConversacion.NUEVO:
            if lead.nombre:
                return OrchestrationResult(
                    intencion="nuevo_contacto_con_nombre",
                    accion="SALUDAR",
                    tono="friendly",
                    respuesta=(
                        f"¡Hola {lead.nombre}! Soy Sofía, asesora de Servired. "
                        "¿En qué te puedo ayudar?"
                    ),
                )
            return OrchestrationResult(
                intencion="nuevo_contacto",
                accion="SALUDAR",
                tono="friendly",
                respuesta=(
                    "¡Hola! Soy Sofía, asesora de Servired. "
                    "¿Cómo te llamás?"
                ),
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

        # ── Detectar objeciones ──
        objecion_keywords = [
            "caro", "costoso", "no llego", "muy alto", "no puedo pagar",
            "no estoy seguro", "no sé si", "necesito pensar", "lo voy a pensar",
            "después", "mañana", "no tengo tiempo", "ocupado",
            "no conozco", "nunca escuché", "no me da confianza",
        ]
        if any(kw in mensaje_lower for kw in objecion_keywords):
            return OrchestrationResult(
                intencion="objecion_detectada",
                accion="MANEJAR_OBJECION",
                tono="empathetic",
                respuesta=(
                    "Entiendo tu preocupación. Déjame explicarte "
                    "por qué nuestros planes son una buena opción para vos."
                ),
            )

        # ── Detectar cierre ──
        cierre_keywords = [
            "dale", "avanzamos", "quiero", "sí", "si", "ok",
            "perfecto", "excelente", "contratar", "afiliarme",
        ]
        if any(kw in mensaje_lower for kw in cierre_keywords):
            return OrchestrationResult(
                intencion="interes_en_cierre",
                accion="CERRAR",
                tono="professional",
                respuesta=(
                    "¡Excelente! Un asesor se comunicará con vos "
                    "para completar el proceso. ¡Bienvenido a Servired!"
                ),
            )

        # ── Datos completos → calcular ──
        if not datos_faltantes and lead.tipo_afiliacion:
            return OrchestrationResult(
                intencion="datos_completos",
                accion="CALCULAR",
                tono="professional",
                respuesta="Con tus datos, te preparo la cotización.",
            )

        # ── Default: informar ──
        return OrchestrationResult(
            intencion="consulta_general",
            accion="INFORMAR",
            tono="friendly",
            respuesta=(
                "Contame un poco más sobre lo que necesitás "
                "y te ayudo a encontrar la mejor opción."
            ),
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
