"""
Prompts del sistema para la asistente comercial Sofía.

Define la personalidad, reglas y formato de contexto
que se envía al LLM en cada interacción.

Uso:
    from app.ai.prompts import construir_prompt_sistema, construir_contexto
    system = construir_prompt_sistema()
    contexto = construir_contexto(lead, etapa, knowledge)
"""

from __future__ import annotations

from typing import Optional

from app.models.lead import Lead
from app.services.session_manager import EtapaConversacion


SYSTEM_PROMPT = """Sos Sofía, asistente comercial de Servired, una obra social/prepaga argentina.

Tu objetivo es ayudar al cliente a encontrar la solución adecuada y acompañarlo hacia la contratación.

## Personalidad
- Amable y profesional
- Cercana pero respetuosa
- Orientada a ventas, nunca agresiva
- Empática con las necesidades del cliente
- Siempre buscás avanzar comercialmente

## Reglas estrictas
- NUNCA inventar beneficios, precios o planes que no estén en la información provista
- NUNCA prometer algo que no puedas respaldar
- Usar SOLO la información de conocimiento provista en el contexto
- Si falta información, preguntá al cliente
- Siempre intentá avanzar hacia el siguiente paso comercial
- Respondé en español argentino (voseo)
- Sé concisa: máximo 3-4 oraciones por respuesta
- No uses emojis excesivamente (máximo 1 por mensaje)

## Formato de respuesta
Respondé SOLO con el texto que le dirías al cliente. No incluyas explicaciones, XML ni formato técnico.
"""


def construir_prompt_sistema() -> str:
    """Retorna el prompt del sistema con la personalidad de Sofía."""
    return SYSTEM_PROMPT


def construir_contexto(
    lead: Optional[Lead],
    etapa: EtapaConversacion,
    knowledge: str = "",
    mensaje_cliente: str = "",
) -> list[dict[str, str]]:
    """
    Construye la lista de mensajes (system + context) para el LLM.

    Args:
        lead: Lead actual con datos del cliente.
        etapa: Etapa de la conversación.
        knowledge: Información relevante de KnowledgeService.
        mensaje_cliente: Último mensaje del cliente.

    Returns:
        Lista de mensajes en formato OpenAI.
    """
    system = construir_prompt_sistema()

    # Construir contexto del cliente
    partes_contexto = []

    if lead:
        if lead.nombre:
            partes_contexto.append(f"Nombre del cliente: {lead.nombre}")
        if lead.edad:
            partes_contexto.append(f"Edad: {lead.edad} años")
        if lead.localidad:
            partes_contexto.append(f"Localidad: {lead.localidad}")
        if lead.tipo_afiliacion:
            partes_contexto.append(f"Situación actual: {lead.tipo_afiliacion.value}")
        if lead.grupo_familiar.conyuge or lead.grupo_familiar.hijos:
            partes = []
            if lead.grupo_familiar.conyuge:
                partes.append("cónyuge")
            if lead.grupo_familiar.hijos:
                partes.append(f"{lead.cantidad_hijos} hijos")
            partes_contexto.append(f"Grupo familiar: {', '.join(partes)}")
        if lead.prioridad_cliente:
            partes_contexto.append(f"Prioridad: {lead.prioridad_cliente.value}")
        if lead.necesidad_principal:
            partes_contexto.append(f"Necesidad: {lead.necesidad_principal.value}")

    # Etapa de la conversación
    mapa_etapas = {
        EtapaConversacion.NUEVO: "inicio",
        EtapaConversacion.DESCUBRIENDO_NECESIDAD: "descubrimiento de necesidad",
        EtapaConversacion.CALIFICANDO: "calificación",
        EtapaConversacion.PRESENTANDO_VALOR: "presentación de valor",
        EtapaConversacion.MANEJANDO_OBJECIONES: "manejo de objeciones",
        EtapaConversacion.INTENTANDO_CIERRE: "intentando cierre",
        EtapaConversacion.CALIFICADO: "conversación finalizada",
        EtapaConversacion.DERIVADO: "derivado a asesor",
    }
    etapa_texto = mapa_etapas.get(etapa, etapa.value)
    partes_contexto.append(f"Etapa de conversación: {etapa_texto}")

    # Knowledge
    if knowledge:
        partes_contexto.append(f"\nInformación relevante:\n{knowledge}")

    # Armar mensajes
    contexto_str = "\n".join(partes_contexto)

    mensajes = [
        {"role": "system", "content": system},
        {"role": "system", "content": f"Contexto de la conversación:\n{contexto_str}"},
    ]

    if mensaje_cliente:
        mensajes.append({"role": "user", "content": mensaje_cliente})

    return mensajes
