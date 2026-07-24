"""
Estrategia de cierre comercial.

Intenta cerrar la venta cuando el lead está calificado.
Registra el resultado del intento.

Uso:
    from app.services.closing_strategy import intentar_cierre, ResultadoCierre
    resultado = intentar_cierre(lead)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

from app.models.lead import Lead

logger = logging.getLogger(__name__)


class ResultadoCierre(str, Enum):
    """Resultado del intento de cierre."""
    ACEPTO = "acepto"
    PENDIENTE = "pendiente"
    RECHAZO = "rechazó"
    NECESITA_ASESOR = "necesita_asesor"


@dataclass
class CierreComercial:
    """
    Resultado de un intento de cierre.

    Attributes:
        tipo_cierre: Tipo de cierre utilizado.
        respuesta: Mensaje de cierre sugerido.
        registrado: Si ya se registró el intento.
    """
    tipo_cierre: str
    respuesta: str
    registrado: bool = False


# ─────────────────────────────────────────────
# Tipos de cierre
# ─────────────────────────────────────────────

def _cierre_directo(lead: Lead) -> str:
    """Cierre directo: pregunta si quiere avanzar."""
    nombre = lead.nombre or "Hola"
    return (
        f"Perfecto {nombre}, con lo que me contaste creo que podemos ayudarte. "
        "¿Querés que avancemos con la afiliación?"
    )


def _cierre_alternativo(lead: Lead) -> str:
    """Cierre alternativo: ofrece dos opciones."""
    nombre = lead.nombre or "Hola"
    return (
        f"{nombre}, tenemos dos caminos: podemos avanzar ahora con la afiliación "
        "o coordinar un momento más tranquilo para completar la información. "
        "¿Qué preferís?"
    )


def _cierre_siguiente_paso(lead: Lead) -> str:
    """Cierre de siguiente paso: pide datos finales."""
    nombre = lead.nombre or "Hola"
    return (
        f"{nombre}, para continuar necesito unos datos finales "
        "y dejamos iniciado el proceso. ¿Avanzamos?"
    )


def _cierre_beneficio(lead: Lead) -> str:
    """Cierre reforzando beneficio."""
    nombre = lead.nombre or "Hola"
    integrantes = lead.cantidad_integrantes
    return (
        f"{nombre}, con tu perfil podemos armar una cobertura para los "
        f"{integrantes} integrantes de tu grupo familiar. "
        "¿Querés que iniciemos el proceso ahora?"
    )


# ─────────────────────────────────────────────
# API pública
# ─────────────────────────────────────────────

def seleccionar_cierre(lead: Lead) -> CierreComercial:
    """
    Selecciona el tipo de cierre más adecuado según el perfil.

    Args:
        lead: Lead del cliente.

    Returns:
        CierreComercial con tipo y respuesta.
    """
    # Si tiene familia, cierre de beneficio
    if lead.grupo_familiar.conyuge or lead.grupo_familiar.hijos:
        return CierreComercial(
            tipo_cierre="beneficio",
            respuesta=_cierre_beneficio(lead),
        )

    # Si es empresa, cierre directo
    from app.models.lead import TipoAfiliacion
    if lead.tipo_afiliacion == TipoAfiliacion.EMPRESA:
        return CierreComercial(
            tipo_cierre="directo",
            respuesta=_cierre_directo(lead),
        )

    # Default: cierre alternativo
    return CierreComercial(
        tipo_cierre="alternativo",
        respuesta=_cierre_alternativo(lead),
    )


def intentar_cierre(lead: Lead) -> CierreComercial:
    """
    Intenta cerrar la venta con el lead calificado.

    Args:
        lead: Lead con suficiente información.

    Returns:
        CierreComercial con respuesta y tipo de cierre.
    """
    cierre = seleccionar_cierre(lead)
    cierre.registrado = True
    logger.info(
        "Intento de cierre para lead %s — tipo: %s",
        lead.lead_id,
        cierre.tipo_cierre,
    )
    return cierre


def interpretar_respuesta_cierre(texto: str) -> ResultadoCierre:
    """
    Interpreta la respuesta del cliente a un intento de cierre.

    Args:
        texto: Mensaje del cliente.

    Returns:
        Resultado del cierre.
    """
    texto_lower = texto.lower().strip()

    rechazos = [
        "no quiero", "no gracias", "no me interesa",
        "no ahora", "no estoy interesado",
    ]
    aceptaciones = [
        "sí", "si", "dale", "avanzamos", "ok", "bueno",
        "perfecto", "quiero avanzar", "avancemos",
    ]
    pendientes = [
        "pensar", "después", "luego",
        "todavía no", "no estoy seguro",
    ]

    # Rechazo primero (capturar "no quiero" antes que "quiero")
    if any(p in texto_lower for p in rechazos):
        return ResultadoCierre.RECHAZO
    if any(p in texto_lower for p in aceptaciones):
        return ResultadoCierre.ACEPTO
    if any(p in texto_lower for p in pendientes):
        return ResultadoCierre.PENDIENTE

    return ResultadoCierre.PENDIENTE
