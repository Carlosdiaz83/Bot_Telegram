"""
Commercial Director — Sprint 22.

El ÚNICO componente que decide el objetivo comercial del próximo mensaje.

NO genera texto. NO llama al LLM. NO consulta documentos.
Solo decide: qué se va a hacer en el próximo mensaje.

El LLM solamente redacta siguiendo el objetivo que el Director define.

Flujo:
    ConversationManager → Orchestrator.interpreta()
    → CommercialDirector.decidir() → ObjetivoComercial
    → CommercialPromptBuilder.build(objetivo=...)
    → LLM solo redacta

Regla fundamental:
    Mientras falte un dato obligatorio, queda prohibido:
    - explicar SERVIRED
    - hablar de beneficios o coberturas
    - inventar planes o precios
    - intentar cerrar
    - hacer comparaciones
    El ÚNICO objetivo es conseguir el dato faltante.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.models.lead import Lead, TipoAfiliacion
from app.services.session_manager import EtapaConversacion

logger = logging.getLogger(__name__)


# ── Prohibiciones por tipo de acción ──
_PROHIBICIONES: dict[str, list[str]] = {
    "PEDIR_DATO": [
        "explicar qué es SERVIRED o sus planes",
        "hablar de beneficios, coberturas o prestaciones",
        "inventar planes, precios o montos",
        "intentar cerrar la venta",
        "hacer comparaciones con otras obras sociales",
        "cotizar sin tener todos los datos obligatorios",
        "presentar propuestas o valores approximados",
    ],
    "COTIZAR": [
        "explicar qué es SERVIRED",
        "pedir más datos al cliente",
        "inventar precios o montos",
    ],
    "PRESENTAR_VALOR": [
        "pedir datos al cliente",
        "inventar beneficios o coberturas",
    ],
    "REBATIR_OBJECION": [
        "pedir datos al cliente",
        "cotizar o mostrar precios",
        "ignorar la objeción del cliente",
    ],
    "CERRAR": [
        "pedir datos al cliente",
        "cotizar o mostrar nuevos precios",
        "explicar qué es SERVIRED",
    ],
}


@dataclass
class ObjetivoComercial:
    """
    Objetivo obligatorio del próximo mensaje.

    El LLM NO puede elegir otro objetivo. Solo redacta siguiendo este.

    Attributes:
        accion: Qué se va a hacer (PEDIR_DATO, COTIZAR, etc.).
        dato_requerido: El dato específico a pedir (si accion=PEDIR_DATO).
        todos_faltantes: Todos los datos que aún faltan (para contexto).
        prohibiciones: Qué NO se puede hacer en este mensaje.
        proximo_si_responde: Qué pasa después de que el cliente responda.
        razon: Por qué este objetivo (para debugging).
    """
    accion: str = "PEDIR_DATO"
    dato_requerido: str | None = None
    todos_faltantes: list[str] = field(default_factory=list)
    prohibiciones: list[str] = field(default_factory=list)
    proximo_si_responde: str | None = None
    razon: str = ""


class CommercialDirector:
    """
    Director Comercial — decide el objetivo del próximo mensaje.

    Usa lógica pura (sin LLM) para determinar:
    1. Si hay objeción → rebatir
    2. Si hay señal de cierre y datos completos → cerrar
    3. Si faltan datos → pedir el siguiente
    4. Si todo está completo → cotizar

    El LLM nunca participa en esta decisión.
    """

    def decidir(
        self,
        lead: Lead,
        context: Any,
        interpretacion: Any = None,
    ) -> ObjetivoComercial:
        """
        Decide el objetivo obligatorio del próximo mensaje.

        Args:
            lead: Lead con todos los datos actuales del cliente.
            context: CommercialConversationContext (memoria comercial).
            interpretacion: Resultado del Orchestrator (intención, objeción, etc.).

        Returns:
            ObjetivoComercial con la acción a ejecutar.
        """
        # ── 1. ¿El cliente tiene una objeción? → REBATIR ──
        if interpretacion is not None:
            objecion = getattr(interpretacion, "objecion_detectada", None)
            if objecion is None:
                # Buscar en datos del resultado
                intencion = getattr(interpretacion, "intencion", "")
                if "objecion" in intencion.lower():
                    objecion = intencion

            if objecion:
                return ObjetivoComercial(
                    accion="REBATIR_OBJECION",
                    razon=f"objeción detectada: {objecion}",
                    prohibiciones=_PROHIBICIONES["REBATIR_OBJECION"],
                    proximo_si_responde="PEDIR_DATO",
                )

        # ── 2. ¿Etapa es MANEJANDO_OBJECIONES? → REBATIR ──
        # (Se verifica por si el handler ya cambió la etapa)

        # ── 3. ¿Cotización ya presentada? ──
        if context is not None and context.cotizacion_realizada:
            # Buscar señal de cierre
            es_cierre = False
            if interpretacion is not None:
                intencion = getattr(interpretacion, "intencion", "")
                es_cierre = any(p in intencion.lower() for p in [
                    "cierre", "quiere_cerrar", "interes_en_cierre",
                    "avanzar", "afiliarme", "contratar",
                ])

            if es_cierre:
                return ObjetivoComercial(
                    accion="CERRAR",
                    razon="cotización presentada + cliente quiere avanzar",
                    prohibiciones=_PROHIBICIONES["CERRAR"],
                )

            return ObjetivoComercial(
                accion="PRESENTAR_VALOR",
                razon="cotización presentada, reforzar valor",
                prohibiciones=_PROHIBICIONES["PRESENTAR_VALOR"],
                proximo_si_responde="CERRAR",
            )

        # ── 4. ¿Faltan datos obligatorios? → PEDIR_DATO ──
        faltantes = self._datos_faltantes(lead, context)
        if faltantes:
            siguiente = faltantes[0]
            proximo = faltantes[1] if len(faltantes) > 1 else self._proximo_despues_de(siguiente, lead)
            return ObjetivoComercial(
                accion="PEDIR_DATO",
                dato_requerido=siguiente,
                todos_faltantes=faltantes,
                prohibiciones=_PROHIBICIONES["PEDIR_DATO"],
                proximo_si_responde=proximo,
                razon=f"faltan datos: {', '.join(faltantes)}",
            )

        # ── 5. Todos los datos completos → COTIZAR ──
        return ObjetivoComercial(
            accion="COTIZAR",
            todos_faltantes=[],
            prohibiciones=_PROHIBICIONES["COTIZAR"],
            proximo_si_responde="PRESENTAR_VALOR",
            razon="todos los datos obligatorios están completos",
        )

    def _datos_faltantes(
        self, lead: Lead, context: Any = None
    ) -> list[str]:
        """
        Lista los datos que faltan para poder cotizar, en orden de prioridad.

        Prioridad:
            1. Grupo familiar (solo o familia)
            2. Tipo de afiliación
            3. Según tipo: edades, localidad, categoría, recibo, conceptos

        Args:
            lead: Lead con datos actuales.
            context: Memoria comercial (datos confirmados).

        Returns:
            Lista de nombres de datos faltantes.
        """
        faltantes: list[str] = []

        # ── 1. Grupo familiar ──
        if not self._esta_confirmado("grupo_familiar", lead, context):
            # Si el lead solo tiene titular y no se preguntó → falta
            if not lead.grupo_familiar.conyuge and not lead.grupo_familiar.hijos:
                # Solo falta si no se confirmó que es solo titular
                if not self._esta_confirmado("grupo_familiar_solo", lead, context):
                    faltantes.append("grupo_familiar")

        # ── 2. Tipo de afiliación ──
        if lead.tipo_afiliacion is None:
            faltantes.append("tipo_afiliacion")

        # ── 3. Datos según tipo ──
        if lead.tipo_afiliacion is not None:
            faltantes.extend(
                self._datos_por_tipo(lead, context)
            )

        return faltantes

    def _datos_por_tipo(
        self, lead: Lead, context: Any = None
    ) -> list[str]:
        """Datos obligatorios según el tipo de afiliación."""
        faltantes: list[str] = []

        tipo = lead.tipo_afiliacion

        if tipo == TipoAfiliacion.PARTICULAR:
            if not self._esta_confirmado("edad", lead, context):
                faltantes.append("edad")
            if not self._esta_confirmado("localidad", lead, context):
                faltantes.append("localidad")

        elif tipo == TipoAfiliacion.MONOTRIBUTO:
            if not self._esta_confirmado("categoria_monotributo", lead, context):
                faltantes.append("categoria_monotributo")
            if not self._esta_confirmado("edad", lead, context):
                faltantes.append("edad")
            if not self._esta_confirmado("localidad", lead, context):
                faltantes.append("localidad")

        elif tipo == TipoAfiliacion.RELACION_DEPENDENCIA:
            if lead.tiene_recibo_sueldo is None:
                faltantes.append("recibo_sueldo")
            elif lead.tiene_recibo_sueldo and not lead.conceptos_obra_social:
                if not self._esta_confirmado("conceptos_obra_social", lead, context):
                    faltantes.append("conceptos_obra_social")
            if not self._esta_confirmado("edad", lead, context):
                faltantes.append("edad")
            if not self._esta_confirmado("localidad", lead, context):
                faltantes.append("localidad")

        return faltantes

    def _esta_confirmado(
        self, campo: str, lead: Lead, context: Any = None
    ) -> bool:
        """
        Verifica si un dato está confirmado (en Lead o en Memory).

        Args:
            campo: Nombre del campo a verificar.
            lead: Lead con datos actuales.
            context: CommercialConversationContext.

        Returns:
            True si el dato está confirmado.
        """
        # Verificar en Lead
        if campo == "grupo_familiar":
            # Si tipo_afiliacion ya está set, grupo_familiar ya se resolvió
            if lead.tipo_afiliacion is not None:
                return True
            if lead.grupo_familiar.conyuge or lead.grupo_familiar.hijos:
                return True
            # Si es solo titular pero ya se preguntó → confirmado
            if context is not None and context.ya_tiene("grupo_familiar"):
                return True
            return False

        if campo == "grupo_familiar_solo":
            if context is not None and context.ya_tiene("grupo_familiar"):
                gf = context.grupo_familiar
                if not gf.get("conyuge") and not gf.get("hijos"):
                    return True
            return False

        if campo == "tipo_afiliacion":
            return lead.tipo_afiliacion is not None

        if campo == "edad":
            return lead.edad is not None

        if campo == "localidad":
            return lead.localidad is not None

        if campo == "categoria_monotributo":
            return lead.categoria_monotributo is not None

        if campo == "recibo_sueldo":
            return lead.tiene_recibo_sueldo is not None

        if campo == "conceptos_obra_social":
            return bool(lead.conceptos_obra_social)

        # Verificar en Memory
        if context is not None and context.ya_tiene(campo):
            return True

        return False

    def _proximo_despues_de(
        self, dato_actual: str, lead: Lead
    ) -> str | None:
        """Determina cuál es el siguiente paso después de obtener un dato."""
        orden_tipo = {
            TipoAfiliacion.PARTICULAR: [
                "tipo_afiliacion", "edad", "localidad",
            ],
            TipoAfiliacion.MONOTRIBUTO: [
                "tipo_afiliacion", "categoria_monotributo", "edad", "localidad",
            ],
            TipoAfiliacion.RELACION_DEPENDENCIA: [
                "tipo_afiliacion", "recibo_sueldo", "conceptos_obra_social",
                "edad", "localidad",
            ],
        }

        orden = orden_tipo.get(lead.tipo_afiliacion, [
            "tipo_afiliacion", "edad", "localidad",
        ])

        if dato_actual in orden:
            idx = orden.index(dato_actual)
            if idx + 1 < len(orden):
                return orden[idx + 1]

        return "COTIZAR"
