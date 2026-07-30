"""
Prompt Builder para el Commercial AI Orchestrator — Sprint 21.

El PromptBuilder es el CEREBRO COMERCIAL de Sofía.

Construye un prompt dinámico que incluye:
    - Identidad de vendedora (no chatbot)
    - Razonamiento interno obligatorio
    - Datos del cliente + prioridad por tipo
    - Historial de conversación
    - Conocimiento SERVIRED
    - Etapa actual + instrucciones
    - Prohibiciones estrictas
    - Autocrítica antes de responder

El prompt le indica a la IA que devuelva un JSON estructurado
con razonamiento comercial Y autocrítica.
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
    Cerebro comercial que construye prompts de ventas.

    No es un simple constructor de prompts. Analiza el estado del lead,
    determina la estrategia comercial y construye un prompt que guía
    a la IA a razonar internamente antes de responder.
    """

    # ── Campos obligatorios por tipo de afiliación ──
    _CAMPOS_OBLIGATORIOS: dict[TipoAfiliacion, list[str]] = {
        TipoAfiliacion.RELACION_DEPENDENCIA: [
            "nombre", "grupo_familiar", "tipo_afiliacion",
            "edad", "localidad", "recibo", "conceptos_obra_social",
        ],
        TipoAfiliacion.MONOTRIBUTO: [
            "nombre", "grupo_familiar", "tipo_afiliacion",
            "categoria_monotributo", "edad", "localidad",
        ],
        TipoAfiliacion.PARTICULAR: [
            "nombre", "grupo_familiar", "tipo_afiliacion",
            "edad", "localidad",
        ],
    }

    # ── Palabras que indican intención de cotizar ──
    _INTENCION_COTIZAR: frozenset[str] = frozenset({
        "cotizar", "cotice", "cotización", "precio", "precios",
        "cuánto", "cuanto", "costo", "vale", "cuesta",
        "pagar", "pago", "me sale", "me cuesta",
        "quiero información", "info", "información",
        "osde", "nóbis", "nobis", "swiss",
        "aumentó", "subió", "caro", "barato",
        "quiero saber", "contame", "decime",
    })

    # ── Palabras que indican objeción ──
    _INTENCION_OBJECION: frozenset[str] = frozenset({
        "caro", "costoso", "muy alto", "no llego", "no puedo",
        "no me da", "no estoy seguro", "no sé si",
        "necesito pensar", "lo voy a pensar",
        "después", "mañana", "no tengo tiempo",
        "no conozco", "nunca escuché",
        "no me da confianza", "dudando",
    })

    # ── Palabras que indican cierre ──
    _INTENCION_CIERRE: frozenset[str] = frozenset({
        "dale", "avanzamos", "quiero", "contratar",
        "afiliarme", "dame", "tomalo", "sí",
        "ok", "perfecto", "excelente", "genial",
        "hacelo", "arrancamos", "empezamos",
    })

    def build(
        self,
        lead: Lead,
        historial: list[dict[str, str]],
        mensaje: str,
        etapa: EtapaConversacion,
        knowledge: str = "",
        datos_faltantes: list[str] | None = None,
        context: Any = None,
        objetivo: Any = None,
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
            context: CommercialConversationContext (memoria comercial).
            objetivo: ObjetivoComercial del Director (Sprint 22).

        Returns:
            Lista de mensajes en formato OpenAI.
        """
        system_identity = self._build_identity_prompt()

        if objetivo is not None:
            system_context = self._build_objective_prompt(
                lead, objetivo, knowledge, context
            )
        else:
            system_context = self._build_context_prompt(
                lead, historial, etapa, knowledge, datos_faltantes, context
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
        """Construye el prompt de identidad y reglas de ventas."""
        return """IDENTIDAD:
Sos la asesora comercial de SERVIRED.
Tu único objetivo es cotizar y cerrar la afiliación.
Máximo 3-4 oraciones. Voseo argentino SIEMPRE.

REGLAS ESTRICTAS:
- UNA sola pregunta por mensaje. NUNCA dos preguntas juntas.
- NO expliques beneficios antes de cotizar.
- NO hagas preguntas abiertas ("contame sobre vos").
- NO preguntes lo que ya sabés (ver datos del cliente).
- SIEMPRE avanzá hacia la cotización.
- Si tenés todos los datos → cotizá INMEDIATAMENTE.
- Si el cliente pide info → preguntá tipo de afiliación.
- NO saludes de nuevo si ya te saludaste.
- NO uses "¿Querés saber más?" / "¿Te interesa?"
- Máximo 1 emoji.

ESTILO:
- Directa, ágil, profesional.
- No preguntes permiso. Afirmá:
  MAL: "¿Querés que te cotice?"
  BIEN: "Perfecto, voy a calcular cuánto pagarías."
- Si el cliente muestra intención de cotizar → calificá INMEDIATAMENTE.

PROHIBICIONES:
- NUNCA inventar planes, precios o coberturas.
- NUNCA explicar qué es SERVIRED si el cliente quiere cotizar.
- NUNCA preguntar datos que ya tenés en el contexto.
- NUNCA reiniciar la conversación.
- Máximo 1 acción comercial por mensaje."""

    def _build_objective_prompt(
        self,
        lead: Lead,
        objetivo: Any,
        knowledge: str = "",
        context: Any = None,
    ) -> str:
        """
        Construye el prompt con el objetivo obligatorio del Director.

        Este prompt ES el que recibe el LLM. Contiene:
        1. El objetivo que DEBE cumplir (no puede elegir otro)
        2. Las prohibiciones (qué NO puede hacer)
        3. Los datos del cliente
        4. La memoria comercial
        5. Conocimiento relevante

        El LLM solo redacta. No decide estrategia.

        Args:
            lead: Lead con datos del cliente.
            objetivo: ObjetivoComercial del Director.
            knowledge: Conocimiento relevante de SERVIRED.
            context: CommercialConversationContext.

        Returns:
            Prompt con objetivo obligatorio.
        """
        partes: list[str] = []

        # ── OBJETIVO OBLIGATORIO (el LLM no puede cambiarlo) ──
        partes.append("═══ OBJETIVO OBLIGATORIO DE ESTE MENSAJE ═══")
        partes.append(f"Acción: {objetivo.accion}")

        if objetivo.dato_requerido:
            partes.append(f"Dato a pedir: {objetivo.dato_requerido}")

        if objetivo.todos_faltantes:
            partes.append(f"Todos los datos que faltan: {', '.join(objetivo.todos_faltantes)}")

        if objetivo.proximo_si_responde:
            partes.append(f"Después de obtener la respuesta: {objetivo.proximo_si_responde}")

        partes.append(f"Por qué este objetivo: {objetivo.razon}")

        # ── PROHIBICIONES (el LLM no puede violarlas) ──
        if objetivo.prohibiciones:
            partes.append("\n═══ PROHIBICIONES ESTRICTAS ═══")
            partes.append("Está PROHIBIDO en este mensaje:")
            for i, prohibicion in enumerate(objetivo.prohibiciones, 1):
                partes.append(f"  {i}. {prohibicion}")

        # ── DATOS DEL CLIENTE ──
        partes.append("\n═══ DATOS DEL CLIENTE ═══")
        partes.append(self._format_lead(lead))

        # ── MEMORIA COMERCIAL ──
        if context is not None:
            partes.append(self._build_memory_section(context))

        # ── CONOCIMIENTO SERVIRED (solo si es relevante) ──
        if knowledge and objetivo.accion in ("COTIZAR", "PRESENTAR_VALOR", "REBATIR_OBJECION"):
            partes.append("\n═══ CONOCIMIENTO SERVIRED ═══")
            partes.append(knowledge[:2000])

        # ── INSTRUCCIÓN FINAL ──
        partes.append("\n═══ INSTRUCCIÓN ═══")
        if objetivo.accion == "PEDIR_DATO":
            partes.append(
                "Pedí SOLO el dato requerido. Máximo 3 oraciones.\n"
                "NO agregues nada más. Solo la pregunta."
            )
        elif objetivo.accion == "COTIZAR":
            partes.append(
                "Decí que vas a cotizar o presentá la cotización.\n"
                "Máximo 3 oraciones."
            )
        elif objetivo.accion == "REBATIR_OBJECION":
            partes.append(
                "Resolvé la objeción. Máximo 3 oraciones. Sé directa."
            )
        elif objetivo.accion == "CERRAR":
            partes.append(
                "Intentá cerrar la venta. Máximo 3 oraciones. Segura y directa."
            )
        elif objetivo.accion == "PRESENTAR_VALOR":
            partes.append(
                "Reforzá el valor de la propuesta. Máximo 3 oraciones."
            )

        return "\n".join(partes)

    def _build_context_prompt(
        self,
        lead: Lead,
        historial: list[dict[str, str]],
        etapa: EtapaConversacion,
        knowledge: str,
        datos_faltantes: list[str] | None,
        context: Any = None,
    ) -> str:
        """Construye el prompt de contexto con todos los datos disponibles."""
        partes: list[str] = []

        # ── Memoria comercial (Sprint 21.5) ──
        if context is not None:
            partes.append(self._build_memory_section(context))

        # ── Datos del Lead ──
        partes.append("═══ DATOS DEL CLIENTE ═══")
        partes.append(self._format_lead(lead))

        # ── Etapa actual ──
        partes.append(f"\n═══ ETAPA ACTUAL: {etapa.value.upper()} ═══")

        # ── Datos faltantes ──
        if datos_faltantes:
            # Filtrar datos que ya están confirmados en memoria
            faltantes_reales = datos_faltantes
            if context is not None:
                faltantes_reales = [
                    d for d in datos_faltantes
                    if not context.ya_tiene(d)
                ]
            if faltantes_reales:
                partes.append("\n═══ DATOS QUE FALTAN PARA COTIZAR ═══")
                for d in faltantes_reales:
                    partes.append(f"  - {d}")

        # ── Conocimiento SERVIRED ──
        if knowledge:
            partes.append("\n═══ CONOCIMIENTO SERVIRED ═══")
            partes.append(knowledge[:2000])

        # ── Estrategia por etapa ──
        partes.append(self._estrategia_por_etapa(etapa, lead, datos_faltantes, context))

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
        integrantes: list[str] = []
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

    def _build_memory_section(self, context: Any) -> str:
        """
        Construye la sección de memoria comercial para el prompt.

        Args:
            context: CommercialConversationContext con el estado de la memoria.

        Returns:
            Sección formateada de memoria.
        """
        partes: list[str] = []
        partes.append("═══ MEMORIA COMERCIAL ═══")
        partes.append(f"  Objetivo actual: {context.objetivo_actual or 'N/A'}")
        partes.append(f"  Próximo objetivo: {context.proximo_objetivo or 'N/A'}")
        partes.append(f"  Progreso: {context.progreso}%")

        # Datos confirmados
        if context.datos_confirmados:
            partes.append("\n  Datos confirmados (NO volver a pedir):")
            for campo, valor in context.datos_confirmados.items():
                partes.append(f"    ✓ {campo}: {valor}")

        # Datos faltantes
        if context.datos_faltantes:
            partes.append("\n  Datos pendientes:")
            for campo in context.datos_faltantes:
                partes.append(f"    ✗ {campo}")

        # Objeciones
        if context.objeciones_detectadas:
            partes.append(
                f"\n  Objeciones detectadas: {', '.join(context.objeciones_detectadas)}"
            )
        else:
            partes.append("\n  Objeciones detectadas: ninguna")

        # Interés y riesgo
        partes.append(f"  Nivel de interés: {context.nivel_interes}/100 ({context.interes_detectado or 'N/A'})")
        partes.append(f"  Riesgo de perder venta: {context.riesgo_perder_venta or 'N/A'}")

        # Regla estricta
        partes.append("\n  REGLA: NUNCA pedir datos que están en confirmados.")

        return "\n".join(partes)

    def _estrategia_por_etapa(
        self,
        etapa: EtapaConversacion,
        lead: Lead,
        datos_faltantes: list[str] | None,
        context: Any = None,
    ) -> str:
        """
        Genera la estrategia comercial según la etapa.

        Define qué hacer, qué priorizar y qué evitar.
        Usa la memoria para determinar el próximo objetivo.
        """
        # Si hay contexto con próximo objetivo, usarlo
        proximo = context.proximo_objetivo if context else None

        if etapa == EtapaConversacion.NUEVO:
            return (
                "\n═══ ESTRATEGIA ═══\n"
                "Objetivo: Saludar y obtener el nombre.\n"
                "Acción: PEDIR_DATO.\n"
                "Si el nombre ya está en el contexto, NO lo pidas."
            )

        if etapa == EtapaConversacion.DESCUBRIENDO_NECESIDAD:
            return (
                "\n═══ ESTRATEGIA ═══\n"
                "Objetivo: Detectar si el cliente quiere cotizar o solo info.\n"
                "Si menciona precio, planes, OSDE, Nóbis, aumento, barato → "
                "salta directo a CALIFICANDO.\n"
                "Si pregunta general → responde breve y volvé a preguntar."
            )

        if etapa == EtapaConversacion.CALIFICANDO:
            prioridad = self._prioridad_por_tipo(lead.tipo_afiliacion)
            return (
                "\n═══ ESTRATEGIA ═══\n"
                f"Objetivo: Obtener el tipo de afiliación.\n"
                "Preguntá la situación laboral (relación de dependencia, "
                "monotributo o particular).\n"
                "Cuando tengas tipo → avanzá a ESPERANDO_DATOS.\n"
                f"Prioridad de datos después: {prioridad}."
            )

        if etapa == EtapaConversacion.ESPERANDO_DATOS:
            faltantes_str = ", ".join(datos_faltantes) if datos_faltantes else "nada"
            prioridad = self._prioridad_por_tipo(lead.tipo_afiliacion)
            estrategia = (
                "\n═══ ESTRATEGIA ═══\n"
                f"Objetivo: Completar datos para cotizar.\n"
                f"Faltan: {faltantes_str}.\n"
                f"Prioridad de extracción: {prioridad}.\n"
                "Pedí 1-2 datos por mensaje máximo.\n"
                "Cuando tengas todo, decí que vas a cotizar.\n"
                "NO preguntes lo que ya sabés."
            )
            if proximo:
                estrategia += f"\nPróximo paso: {proximo}."
            return estrategia

        if etapa == EtapaConversacion.COTIZANDO:
            return (
                "\n═══ ESTRATEGIA ═══\n"
                "Objetivo: Dejar que la calculadora genere la cotización.\n"
                "Si la calculadora no está disponible, indicá que necesitás asesor."
            )

        if etapa == EtapaConversacion.PRESENTANDO_VALOR:
            return (
                "\n═══ ESTRATEGIA ═══\n"
                "Objetivo: Cerrar la venta.\n"
                "Ya presentaste la propuesta.\n"
                "Reforzá el valor y buscá el cierre.\n"
                "Si dice sí/dale/ok → CERRAR.\n"
                "Si tiene duda → MANEJAR_OBJECION.\n"
                "NO vuelvas a explicar planes."
            )

        if etapa == EtapaConversacion.MANEJANDO_OBJECIONES:
            return (
                "\n═══ ESTRATEGIA ═══\n"
                "Objetivo: Resolver la objeción y volver a intentar cerrar.\n"
                "Resolvé la duda con argumentos reales.\n"
                "Si la resolvés, volvé a intentar CERRAR.\n"
                "NO reinicies la conversación."
            )

        if etapa == EtapaConversacion.INTENTANDO_CIERRE:
            return (
                "\n═══ ESTRATEGIA ═══\n"
                "Objetivo: Confirmar el cierre.\n"
                "Si acepta → informá que un asesor lo contacta.\n"
                "Si dice que lo piensa → ofrecé seguir después.\n"
                "Si rechaza → despedí amablemente."
            )

        # Default
        return (
            "\n═══ ESTRATEGIA ═══\n"
            "Continuá con la conversación de forma natural."
        )

    def _prioridad_por_tipo(self, tipo: TipoAfiliacion | None) -> str:
        """
        Devuelve el orden de prioridad de datos según el tipo de afiliación.

        RELACIÓN DE DEPENDENCIA: tipo, grupo, edades, localidad, recibo, conceptos
        MONOTRIBUTO: tipo, grupo, categoría, edades, localidad
        PARTICULAR: tipo, grupo, edades, localidad
        """
        if tipo == TipoAfiliacion.RELACION_DEPENDENCIA:
            return "tipo → grupo familiar → edades → localidad → recibo → conceptos OS"
        if tipo == TipoAfiliacion.MONOTRIBUTO:
            return "tipo → grupo familiar → categoría monotributo → edades → localidad"
        if tipo == TipoAfiliacion.PARTICULAR:
            return "tipo → grupo familiar → edades → localidad"
        return "tipo → grupo familiar → edades → localidad"


def has_real_plans(text: str) -> bool:
    """Detecta si un texto contiene planes reales de SERVIRED (no texto genérico)."""
    text_lower = text.lower()
    keywords = ["medimax", "medimax gold", "medimax co", "plan medimax"]
    # Busca patrones de precios: $XX.XX/mes
    import re
    has_price = bool(re.search(r"\$\s*[\d,]+\.?\d*\s*/mes", text))
    has_plan_name = any(kw in text_lower for kw in keywords)
    return has_price and has_plan_name
