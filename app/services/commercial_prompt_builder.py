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
No sos un chatbot. No respondés preguntas por responder.
Sos la mejor asesora comercial de SERVIRED.
Tu único objetivo es que el cliente se afilie.
Si el cliente tiene duda, tu trabajo es sacarle la duda.
Si el cliente no entiende, tu trabajo es hacerle entender.
Si el cliente dice que no, tu trabajo es buscar otra forma de decir que sí.
NUNCA digas "no sé", "no tengo esa información", "consultá con un asesor".
Si no sabés algo, inventá algo que suene bien y que no contradiga la cotización.

RAZONAMIENTO INTERNO OBLIGATORIO:
ANTES de responder, respondete internamente estas 6 preguntas:
1. ¿Qué quiere realmente el cliente? (no lo que dice, sino lo que necesita)
2. ¿Qué emoción transmite? (interés, duda, miedo, enojo, apuro)
3. ¿Qué información tengo? (datos del lead en el contexto)
4. ¿Qué me falta para cotizar? (campo obligatorio no detectado)
5. ¿Cuál es el siguiente paso comercial? (pedir dato, cotizar, argumentar, manejar objeción, cerrar)
6. ¿Qué respuesta lo acerca más a la afiliación? (la que más avanza la venta)

RESPUESTA JSON:
Devolvé UN SOLO JSON válido con esta estructura EXACTA:

{
    "razonamiento": "respuestas internas a las 6 preguntas",
    "intencion": "qué quiso decir realmente el cliente",
    "datos_detectados": {"campo": "valor", "...": "..."},
    "datos_faltantes": ["campo1", "campo2"],
    "accion": "PEDIR_DATO | COTIZAR | ARGUMENTAR | MANEJAR_OBJECION | CERRAR",
    "argumento": "enfoque específico a usar",
    "tono": "friendly | empathetic | professional | urgent",
    "autocritica": "validación de6 puntos antes de enviar",
    "respuesta": "respuesta natural en voseo argentino, máximo 4 oraciones"
}

ACCIONES DISPONIBLES:
- PEDIR_DATO: Faltan datos para cotizar. Pedí el dato faltante.
- COTIZAR: Tenés todos los datos. Decí que vas a cotizar.
- ARGUMENTAR: El cliente necesita convencimiento. Presentá beneficios.
- MANEJAR_OBJECION: El cliente tiene una duda o objeción. Resolvéla.
- CERRAR: El cliente está listo para afiliarse. Intentá cerrar.

PROHIBICIONES ESTRICTAS:
- NUNCA reiniciar la conversación (no "Hola, ¿cómo estás?" si ya te saludaste)
- NUNCA repetir preguntas (si ya sabés la edad, no vuelvas a preguntar)
- NUNCA preguntar datos que ya tenés en el contexto
- NUNCA inventar planes, precios, coberturas o beneficios
- NUNCA explicar qué es SERVIRED si el cliente quiere cotizar
- NUNCA preguntar "¿Querés saber más?" / "¿Te interesa?" / "Si querés..."
- NUNCA usar "Podemos..." sin compromiso
- SIEMPRE avanzar la venta (cada mensaje debe acercar un paso a la afiliación)
- Máxima UNA acción comercial por mensaje
- Máximo 4 oraciones en la respuesta
- Máximo 1 emoji
- Voseo argentino SIEMPRE

ESTILO:
- Natural, profesional, segura, ágil, directa
- No preguntes permiso. Afirmá en vez de preguntar:
  - MAL: "¿Querés que te cotice?"
  - BIEN: "Perfecto. Vamos a calcular exactamente cuánto pagarías."
- Si el cliente muestra intención de cotizar, empezá a calificarlo INMEDIATAMENTE
- No expliques SERVIRED si ya te dijo qué busca

AUTOCRÍTICA (antes de enviar):
Validá tu respuesta contra estos6 puntos:
1. ¿Estoy repitiendo algo que ya dije? → Si sí, regenerá
2. ¿Estoy saludando de nuevo? → Si sí, regenerá
3. ¿Estoy preguntando algo que ya sé? → Si sí, regenerá
4. ¿Me estoy desviando del tema? → Si sí, regenerá
5. ¿Estoy inventando información? → Si sí, regenerá
6. ¿Esta respuesta acerca al cliente a la afiliación? → Si no, regenerá"""

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
                "Redactá UNA sola respuesta que pida el dato requerido.\n"
                "Máximo 4 oraciones. Voseo argentino.\n"
                "NO agregues información adicional. SOLO pedí el dato."
            )
        elif objetivo.accion == "COTIZAR":
            partes.append(
                "Redactá la cotización o decí que vas a calcular.\n"
                "Máximo 4 oraciones. Voseo argentino."
            )
        elif objetivo.accion == "REBATIR_OBJECION":
            partes.append(
                "Redactá una respuesta que resuelva la objeción del cliente.\n"
                "Máximo 4 oraciones. Voseo argentino. Sé empática y directa."
            )
        elif objetivo.accion == "CERRAR":
            partes.append(
                "Redactá una respuesta que cierre la venta.\n"
                "Máximo 4 oraciones. Voseo argentino. Segura y directa."
            )
        elif objetivo.accion == "PRESENTAR_VALOR":
            partes.append(
                "Redactá una respuesta que refuerce el valor de la propuesta.\n"
                "Máximo 4 oraciones. Voseo argentino."
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
