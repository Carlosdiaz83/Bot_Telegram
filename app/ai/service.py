"""
Servicio de IA para Sofía.

Orquesta la generación de respuestas naturales usando el LLM,
integrando contexto comercial, knowledge y personalidad.

Uso:
    from app.ai.service import AIService
    ai = AIService(api_key="...", provider="groq")
    respuesta = ai.generar_respuesta(lead, etapa, knowledge, mensaje)
"""

from __future__ import annotations

import logging
from typing import Optional

from app.ai.client import LLMClient, LLMResponse
from app.ai.prompts import construir_contexto
from app.models.lead import Lead
from app.services.session_manager import EtapaConversacion

logger = logging.getLogger(__name__)


class AIService:
    """
    Servicio que genera respuestas naturales para Sofía.

    Recibe el contexto comercial (Lead, etapa, knowledge)
    y retorna una respuesta generada por el LLM.
    """

    def __init__(
        self,
        api_key: str = "",
        provider: str = "groq",
        model: str = "llama-3.3-70b-versatile",
    ) -> None:
        self._client = LLMClient(api_key=api_key, provider=provider, model=model)
        self._disponible = bool(api_key)

    @property
    def disponible(self) -> bool:
        """Indica si el servicio está disponible (API key configurada)."""
        return self._disponible

    def generar_respuesta(
        self,
        lead: Optional[Lead],
        etapa: EtapaConversacion,
        knowledge: str,
        mensaje_cliente: str,
        respuesta_fallback: str = "",
    ) -> str:
        """
        Genera una respuesta natural basada en el contexto.

        Args:
            lead: Lead actual del cliente.
            etapa: Etapa de la conversación.
            knowledge: Información relevante de KnowledgeService.
            mensaje_cliente: Último mensaje del cliente.
            respuesta_fallback: Respuesta por si falla la IA.

        Returns:
            Respuesta generada por el LLM o el fallback.
        """
        if not self._disponible:
            logger.debug("IA no disponible, usando fallback")
            return respuesta_fallback

        mensajes = construir_contexto(
            lead=lead,
            etapa=etapa,
            knowledge=knowledge,
            mensaje_cliente=mensaje_cliente,
        )

        resultado: LLMResponse = self._client.generar_respuesta(
            mensajes=mensajes,
            temperatura=0.7,
            max_tokens=300,
        )

        if resultado.exito and resultado.texto:
            logger.debug(
                "IA generó respuesta (%d tokens): %s...",
                resultado.tokens_usados,
                resultado.texto[:50],
            )
            return resultado.texto

        logger.warning("IA falló: %s. Usando fallback", resultado.error)
        return respuesta_fallback
