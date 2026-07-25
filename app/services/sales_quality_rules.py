"""
Reglas de calidad comercial.

Define las reglas del método de venta consultivo que Sofía debe seguir.
Basado en el método comercial: diagnosticar antes de vender.

Uso:
    from app.services.sales_quality_rules import SalesQualityRules
    reglas = SalesQualityRules()
    errores = reglas.verificar(resultado_simulacion)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.simulation.engine import ResultadoSimulacion, IntercambioSimulacion
from app.models.lead import Lead

logger = logging.getLogger(__name__)


@dataclass
class ReglaCalidad:
    """
    Regla de calidad comercial.

    Attributes:
        nombre: Identificador de la regla.
        fase: Fase del método comercial (descubrimiento, propuesta, objeciones, cierre).
        descripcion: Descripción de la regla.
        verificar: Función que verifica si se cumple la regla.
    """
    nombre: str
    fase: str
    descripcion: str


# ─────────────────────────────────────────────
# Reglas del método comercial
# ─────────────────────────────────────────────

REGLAS_DESCUBRIMIENTO: list[ReglaCalidad] = [
    ReglaCalidad(
        nombre="nombre_obligatorio",
        fase="descubrimiento",
        descripcion="Debe obtener el nombre del cliente antes de ofrecer.",
    ),
    ReglaCalidad(
        nombre="grupo_familiar",
        fase="descubrimiento",
        descripcion="Debe preguntar sobre grupo familiar.",
    ),
    ReglaCalidad(
        nombre="edades",
        fase="descubrimiento",
        descripcion="Debe obtener edades del titular y grupo familiar.",
    ),
    ReglaCalidad(
        nombre="localidad",
        fase="descubrimiento",
        descripcion="Debe conocer la localidad del cliente.",
    ),
    ReglaCalidad(
        nombre="situacion_laboral",
        fase="descubrimiento",
        descripcion="Debe conocer la situación laboral (tipo de afiliación).",
    ),
    ReglaCalidad(
        nombre="aportes",
        fase="descubrimiento",
        descripcion="Debe preguntar por aportes cuando corresponde.",
    ),
    ReglaCalidad(
        nombre="necesidad_principal",
        fase="descubrimiento",
        descripcion="Debe detectar la necesidad principal.",
    ),
]

REGLAS_PROPUESTA: list[ReglaCalidad] = [
    ReglaCalidad(
        nombre="no_vender_solo_precio",
        fase="propuesta",
        descripcion="No debe vender solamente por precio.",
    ),
    ReglaCalidad(
        nombre="explicar_valor",
        fase="propuesta",
        descripcion="Debe explicar el valor de la cobertura.",
    ),
    ReglaCalidad(
        nombre="personalizar_argumentos",
        fase="propuesta",
        descripcion="Debe personalizar argumentos según el perfil.",
    ),
]

REGLAS_OBJECIONES: list[ReglaCalidad] = [
    ReglaCalidad(
        nombre="validar_objecion",
        fase="objeciones",
        descripcion="Debe validar la preocupación del cliente.",
    ),
    ReglaCalidad(
        nombre="preguntar_motivo_real",
        fase="objeciones",
        descripcion="Debe preguntar el motivo real de la objeción.",
    ),
    ReglaCalidad(
        nombre="resolver_objecion",
        fase="objeciones",
        descripcion="Debe resolver la objeción antes de avanzar.",
    ),
]

REGLAS_CIERRE: list[ReglaCalidad] = [
    ReglaCalidad(
        nombre="detectar_intencion",
        fase="cierre",
        descripcion="Debe detectar la intención del cliente.",
    ),
    ReglaCalidad(
        nombre="pedir_avance",
        fase="cierre",
        descripcion="Debe pedir avance cuando hay interés.",
    ),
    ReglaCalidad(
        nombre="solicitar_documentacion",
        fase="cierre",
        descripcion="Debe solicitar documentación cuando corresponde.",
    ),
]

TODAS_LAS_REGLAS = (
    REGLAS_DESCUBRIMIENTO
    + REGLAS_PROPUESTA
    + REGLAS_OBJECIONES
    + REGLAS_CIERRE
)


class SalesQualityRules:
    """
    Servicio de reglas de calidad comercial.

    Verifica que una conversación siga el método de venta consultivo.
    """

    def verificar(self, resultado: ResultadoSimulacion) -> list[dict]:
        """
        Verifica todas las reglas de calidad.

        Args:
            resultado: Resultado de la simulación.

        Returns:
            Lista de diccionarios con reglas incumplidas.
        """
        incumplidas: list[dict] = []
        lead = resultado.lead_final
        intercambios = resultado.intercambios

        if lead is None or len(intercambios) < 1:
            return incumplidas

        # Verificar reglas de descubrimiento
        incumplidas.extend(
            self._verificar_descubrimiento(lead, intercambios)
        )

        # Verificar reglas de propuesta
        incumplidas.extend(
            self._verificar_propuesta(lead, intercambios)
        )

        # Verificar reglas de objeciones
        incumplidas.extend(
            self._verificar_objeciones(lead, intercambios)
        )

        # Verificar reglas de cierre
        incumplidas.extend(
            self._verificar_cierre(lead, intercambios)
        )

        return incumplidas

    def _verificar_descubrimiento(
        self, lead: Lead, intercambios: list[IntercambioSimulacion]
    ) -> list[dict]:
        """Verifica reglas de la fase de descubrimiento."""
        incumplidas: list[dict] = []

        if lead.nombre is None:
            incumplidas.append({
                "regla": "nombre_obligatorio",
                "fase": "descubrimiento",
                "descripcion": "No obtuvo el nombre del cliente.",
            })

        if not (lead.grupo_familiar.conyuge or lead.grupo_familiar.hijos):
            # Solo verificar si el cliente mencionó familia
            menciona_familia = any(
                "familia" in i.mensaje_cliente.lower()
                or "esposo" in i.mensaje_cliente.lower()
                or "esposa" in i.mensaje_cliente.lower()
                or "hijo" in i.mensaje_cliente.lower()
                for i in intercambios
            )
            if menciona_familia:
                incumplidas.append({
                    "regla": "grupo_familiar",
                    "fase": "descubrimiento",
                    "descripcion": "No detectó el grupo familiar del cliente.",
                })

        if lead.edad is None:
            incumplidas.append({
                "regla": "edades",
                "fase": "descubrimiento",
                "descripcion": "No obtuvo la edad del cliente.",
            })

        if lead.localidad is None:
            incumplidas.append({
                "regla": "localidad",
                "fase": "descubrimiento",
                "descripcion": "No obtuvo la localidad del cliente.",
            })

        if lead.tipo_afiliacion is None:
            incumplidas.append({
                "regla": "situacion_laboral",
                "fase": "descubrimiento",
                "descripcion": "No obtuvo la situación laboral del cliente.",
            })

        if lead.necesidad_principal is None and lead.prioridad_cliente is None:
            incumplidas.append({
                "regla": "necesidad_principal",
                "fase": "descubrimiento",
                "descripcion": "No detectó la necesidad principal del cliente.",
            })

        return incumplidas

    def _verificar_propuesta(
        self, lead: Lead, intercambios: list[IntercambioSimulacion]
    ) -> list[dict]:
        """Verifica reglas de la fase de propuesta."""
        incumplidas: list[dict] = []

        # Verificar que avanzó a presentación de valor
        etapas_valor = [
            "presentando_valor",
            "manejando_objeciones",
            "intentando_cierre",
            "calificado",
        ]
        # Inferir si hubo presentación de valor
        hubo_valor = any(
            "beneficio" in i.respuesta_sofia.lower()
            or "cobertura" in i.respuesta_sofia.lower()
            or "plan" in i.respuesta_sofia.lower()
            for i in intercambios
        )

        if not hubo_valor and len(intercambios) >= 3:
            incumplidas.append({
                "regla": "explicar_valor",
                "fase": "propuesta",
                "descripcion": "No explicó el valor de la cobertura.",
            })

        # Verificar personalización
        tiene_perfil = (
            lead.necesidad_principal is not None
            or lead.prioridad_cliente is not None
            or lead.tipo_afiliacion is not None
        )
        if not tiene_perfil and len(intercambios) >= 4:
            incumplidas.append({
                "regla": "personalizar_argumentos",
                "fase": "propuesta",
                "descripcion": "No personalizó argumentos según el perfil.",
            })

        return incumplidas

    def _verificar_objeciones(
        self, lead: Lead, intercambios: list[IntercambioSimulacion]
    ) -> list[dict]:
        """Verifica reglas de la fase de objeciones."""
        incumplidas: list[dict] = []

        # Detectar si hubo objeciones
        tiene_objeciones = any(
            any(
                p in i.mensaje_cliente.lower()
                for p in ["caro", "cuesta", "pensar", "después", "no sé", "duda"]
            )
            for i in intercambios
        )

        if tiene_objeciones:
            # Verificar que respondió a la objeción
            respuestas_despues_objecion = []
            for i, intercambio in enumerate(intercambios):
                if any(
                    p in intercambio.mensaje_cliente.lower()
                    for p in ["caro", "cuesta", "pensar", "después"]
                ):
                    if i + 1 < len(intercambios):
                        respuestas_despues_objecion.append(
                            intercambios[i + 1].respuesta_sofia
                        )

            if not respuestas_despues_objecion:
                incumplidas.append({
                    "regla": "resolver_objecion",
                    "fase": "objeciones",
                    "descripcion": "No resolvió las objeciones del cliente.",
                })

        return incumplidas

    def _verificar_cierre(
        self, lead: Lead, intercambios: list[IntercambioSimulacion]
    ) -> list[dict]:
        """Verifica reglas de la fase de cierre."""
        incumplidas: list[dict] = []

        # Verificar que intentó cerrar
        intento_cierre = any(
            any(
                p in i.respuesta_sofia.lower()
                for p in ["avancemos", "querés", "proceso", "afiliación"]
            )
            for i in intercambios
        )

        if not intento_cierre and len(intercambios) >= 4:
            incumplidas.append({
                "regla": "pedir_avance",
                "fase": "cierre",
                "descripcion": "No intentó avanzar hacia el cierre.",
            })

        return incumplidas
