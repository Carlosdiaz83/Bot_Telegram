"""
Prompt Builder para el Commercial AI Orchestrator — Sprint 20.

Construye un único prompt dinámico que incluye:
    - Identidad de Sofía
    - Objetivo comercial
    - Contexto del Lead
    - Historial de conversación
    - Conocimiento SERVIRED
    - Etapa actual
    - Datos faltantes
    - Reglas estrictas

El prompt le indica a la IA que devuelva un JSON estructurado
con razonamiento comercial, NO solo texto.
"""

from __future__ import annotations

import logging
from typing import Any

from app.models.lead import (
    EstadoComercial,
    GrupoFamiliar,
    InteresDetectado,
    Lead,
    NecesidadPrincipal,
    PrioridadCliente,
    TipoAfiliacion,
)
from app.services.session_manager import EtapaConversacion

logger = logging.getLogger(__name__)


class CommercialPromptBuilder:
    """
    Construye el prompt maestro para el Orchestrator.

    Genera un prompt único y dinámico que incluye toda la información
    necesaria para que la IA razona comercialmente.
    """

    def build(
        self,
        lead: Lead,
        historial: list[dict[str, str]],
        mensaje: str,
        etapa: EtapaConversacion,
        knowledge: str = "",
        datos_faltantes: list[str] | None = None,
    ) -> list[dict[str, str]]:
        """
        Construye el prompt completo para el LLM.

        Args:
            lead: Lead con todos los datos del cliente.
            historial: Lista de {"role": "user"/"assistant", "content": "..."}.
            mensaje: Último mensaje del cliente.
            etapa: Etapa actual de la conversación.
            knowledge: Contexto recuperado del Knowledge Engine.
            datos_faltantes: Lista de datos que faltan para cotizar.

        Returns:
            Lista de mensajes en formato OpenAI.
        """
        system_identity = self._build_identity_prompt()
        system_context = self._build_context_prompt(
            lead, historial, etapa, knowledge, datos_faltantes
        )

        mensajes: list[dict[str, str]] = [
            {"role": "system", "content": system_identity},
            {"role": "system", "content": system_context},
        ]

        # Agregar historial (últimos 6 intercambios máximo)
        for msg in historial[-12:]:
            mensajes.append(msg)

        # Agregar mensaje actual del cliente
        mensajes.append({"role": "user", "content": mensaje})

        return mensajes

    def _build_identity_prompt(self) -> str:
        """Construye el prompt de identidad y reglas."""
        return """Sos Sofía, asesora comercial senior de SERVIRED.

NO sos un chatbot. NO respondés preguntas por responder.
Sos una vendedora experta que siempre busca avanzar la venta.

ANALIZÁ el mensaje del cliente y devolvé UN SOLO JSON válido
con esta estructura EXACTA:

{
    "intencion": "qué quiso decir realmente el cliente",
    "datos_detectados": {"campo": "valor", "...": "..."},
    "datos_faltantes": ["campo1", "campo2"],
    "accion": "PEDIR_DATO | CALCULAR | ARGUMENTAR | MANEJAR_OBJECION | CERRAR | SALUDAR | INFORMAR | DERIVAR",
    "argumento": "enfoque específico a usar",
    "tono": "friendly | empathetic | professional | urgent",
    "respuesta": "respuesta natural en voseo argentino, máximo 4 oraciones"
}

ACCIONES DISPONIBLES:
- PEDIR_DATO: Faltan datos para cotizar. El respuesta debe pedir el dato faltante.
- CALCULAR: Tenés todos los datos. El respuesta debe decir que vas a cotizar.
- ARGUMENTAR: El cliente necesita convencimiento. Presentá beneficios.
- MANEJAR_OBJECION: El cliente tiene una duda o objeción. Resolvéla.
- CERRAR: El cliente está listo para afiliarse. Intentá cerrar.
- SALUDAR: Primer contacto. Presentate y hacé la primera pregunta.
- INFORMAR: El cliente pregunta algo informativo. Respondé con datos reales.
- DERIVAR: El cliente necesita un asesor humano. Ofrecé derivación.

REGLAS ESTRICTAS:
- NUNCA inventar precios, coberturas, promociones o beneficios.
- SOLO usá datos que estén en el contexto o en la DB de SERVIRED.
- Máximo 4 oraciones en la respuesta.
- Máximo 1 emoji.
- Voseo argentino SIEMPRE.
- NO repetir saludos si ya te saludaste.
- NO preguntar dos veces lo mismo.
- SIEMPRE avanzar la venta.
- Máxima UNA acción comercial por mensaje.
- Si el cliente pide asesor explícitamente → accion=DERIVAR."""

    def _build_context_prompt(
        self,
        lead: Lead,
        historial: list[dict[str, str]],
        etapa: EtapaConversacion,
        knowledge: str,
        datos_faltantes: list[str] | None,
    ) -> str:
        """Construye el prompt de contexto con todos los datos disponibles."""
        partes: list[str] = []

        # ── Datos del Lead ──
        partes.append("═══ DATOS DEL CLIENTE ═══")
        partes.append(self._format_lead(lead))

        # ── Etapa actual ──
        partes.append(f"\n═══ ETAPA ACTUAL: {etapa.value.upper()} ═══")

        # ── Datos faltantes ──
        if datos_faltantes:
            partes.append("\n═══ DATOS QUE FALTAN PARA COTIZAR ═══")
            for d in datos_faltantes:
                partes.append(f"  - {d}")

        # ── Conocimiento SERVIRED ──
        if knowledge:
            partes.append("\n═══ CONOCIMIENTO SERVIRED ═══")
            partes.append(knowledge[:2000])

        # ── Instrucciones específicas por etapa ──
        partes.append(self._instrucciones_por_etapa(etapa, lead))

        return "\n".join(partes)

    def _format_lead(self, lead: Lead) -> str:
        """Formatea los datos del Lead para el prompt."""
        lineas: list[str] = []

        if lead.nombre:
            lineas.append(f"  Nombre: {lead.nombre}")
        else:
            lineas.append("  Nombre: (desconocido)")

        if lead.edad is not None:
            lineas.append(f"  Edad: {lead.edad} años")

        if lead.localidad:
            lineas.append(f"  Localidad: {lead.localidad}")

        if lead.tipo_afiliacion:
            lineas.append(f"  Tipo afiliación: {lead.tipo_afiliacion.value}")
        else:
            lineas.append("  Tipo afiliación: (no detectado)")

        if lead.categoria_monotributo:
            lineas.append(f"  Categoría monotributo: {lead.categoria_monotributo}")

        if lead.tiene_recibo_sueldo is not None:
            estado = "Sí" if lead.tiene_recibo_sueldo else "No"
            lineas.append(f"  Recibo de sueldo: {estado}")

        if lead.conceptos_obra_social:
            lineas.append(f"  Conceptos OS: {lead.conceptos_obra_social}")

        # Grupo familiar
        gf = lead.grupo_familiar
        integrantes = []
        if gf.titular:
            integrantes.append("titular")
        if gf.conyuge:
            integrantes.append("cónyuge")
        if gf.hijos:
            integrantes.append(f"{lead.cantidad_hijos} hijos")
        lineas.append(f"  Grupo familiar: {', '.join(integrantes) if integrantes else 'solo titular'}")
        lineas.append(f"  Total integrantes: {lead.cantidad_integrantes}")

        if lead.interes_detectado:
            lineas.append(f"  Interés detectado: {lead.interes_detectado.value}")

        if lead.necesidad_principal:
            lineas.append(f"  Necesidad principal: {lead.necesidad_principal.value}")

        if lead.prioridad_cliente:
            lineas.append(f"  Prioridad: {lead.prioridad_cliente.value}")

        lineas.append(f"  Estado comercial: {lead.estado_comercial.value}")

        return "\n".join(lineas)

    def _instrucciones_por_etapa(
        self, etapa: EtapaConversacion, lead: Lead
    ) -> str:
        """Genera instrucciones específicas según la etapa."""
        if etapa == EtapaConversacion.NUEVO:
            return (
                "\n═══ INSTRUCCIONES ═══\n"
                "Es tu primer contacto con el cliente.\n"
                "Presentate brevemente y hacé una pregunta inicial.\n"
                "No le preguntes el nombre si ya lo decís en el mensaje."
            )

        if etapa == EtapaConversacion.DESCUBRIENDO_NECESIDAD:
            return (
                "\n═══ INSTRUCCIONES ═══\n"
                "Estás descubriendo qué necesita el cliente.\n"
                "Preguntá sobre su situación laboral y cobertura.\n"
                "Si detectás una intención comercial, avanzá a CALIFICANDO."
            )

        if etapa == EtapaConversacion.CALIFICANDO:
            return (
                "\n═══ INSTRUCCIONES ═══\n"
                "Estás calificando al lead.\n"
                "Necesitás: tipo afiliación, grupo familiar, localidad, edad.\n"
                "Cuando tengas tipo afiliación → avanzá a ESPERANDO_DATOS."
            )

        if etapa == EtapaConversacion.ESPERANDO_DATOS:
            faltantes = []
            if lead.localidad is None:
                faltantes.append("localidad")
            if lead.edad is None:
                faltantes.append("edad")
            if lead.tipo_afiliacion == TipoAfiliacion.MONOTRIBUTO and not lead.categoria_monotributo:
                faltantes.append("categoría de monotributo")
            if lead.tipo_afiliacion == TipoAfiliacion.RELACION_DEPENDENCIA:
                if not lead.tiene_recibo_sueldo:
                    faltantes.append("recibo de sueldo")
                elif not lead.conceptos_obra_social:
                    faltantes.append("conceptos de obra social del recibo")

            return (
                "\n═══ INSTRUCCIONES ═══\n"
                "Estás reuniendo datos para cotizar.\n"
                f"Faltan: {', '.join(faltantes) if faltantes else 'nada'}.\n"
                "Pedí solo 1-2 datos por mensaje.\n"
                "Cuando tengas todo, decí que vas a cotizar."
            )

        if etapa == EtapaConversacion.COTIZANDO:
            return (
                "\n═══ INSTRUCCIONES ═══\n"
                "Tenés todos los datos. Dejá que la calculadora genere la cotización.\n"
                "Si la calculadora no está disponible, indicá que necesitás asesor."
            )

        if etapa == EtapaConversacion.PRESENTANDO_VALOR:
            return (
                "\n═══ INSTRUCCIONES ═══\n"
                "Ya presentaste la propuesta.\n"
                "Reforzá el valor y buscá el cierre.\n"
                "Si dice sí/dale/ok → CERRAR.\n"
                "Si tiene duda → MANEJAR_OBJECION."
            )

        if etapa == EtapaConversacion.MANEJANDO_OBJECIONES:
            return (
                "\n═══ INSTRUCCIONES ═══\n"
                "El cliente tiene una objeción.\n"
                "Resolvéla con argumentos reales.\n"
                "Si pide asesor explícitamente → DERIVAR.\n"
                "Si la resolvés, volvé a intentar CERRAR."
            )

        if etapa == EtapaConversacion.INTENTANDO_CIERRE:
            return (
                "\n═══ INSTRUCCIONES ═══\n"
                "Estás intentando cerrar la venta.\n"
                "Si acepta → informá que un asesor lo contacta.\n"
                "Si dice que lo piensa → ofrecé seguir después.\n"
                "Si rechaza → despedí amablemente."
            )

        # Default
        return "\n═══ INSTRUCCIONES ═══\nContinuá con la conversación de forma natural."
