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
    """Cierre directo: avanza con la afiliación."""
    nombre = lead.nombre or "Hola"
    return (
        f"Perfecto {nombre}, con lo que me contaste creo que podemos ayudarte. "
        "Avanzo con el proceso de afiliación."
    )


def _cierre_alternativo(lead: Lead) -> str:
    """Cierre alternativo: ofrece dos opciones de forma directa."""
    nombre = lead.nombre or "Hola"
    return (
        f"{nombre}, tenemos dos caminos: podemos avanzar ahora con la afiliación "
        "o coordinar un momento más tranquilo para completar la información. "
        "Si querés, avanzo ahora. Si preferís, coordinamos una llamada."
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
        "Iniciamos el proceso ahora para que tu familia quede cubierta."
    )


def _cierre_urgencia(lead: Lead) -> str:
    """Cierre por urgencia: refuerza el beneficio de actuar rápido."""
    nombre = lead.nombre or "Hola"
    return (
        f"{nombre}, mientras más pronto te afilies, antes empezás a tener la cobertura. "
        "No querés que dejemos iniciado el proceso ahora?"
    )


def recuperar_indeciso(lead: Lead) -> str:
    """
    Recupera un cliente indeciso que no se decide a avanzar.

    Args:
        lead: Lead del cliente indeciso.

    Returns:
        Mensaje de recuperación.
    """
    nombre = lead.nombre or "Hola"

    # Si tiene familia, reforzar beneficio familiar
    if lead.grupo_familiar.conyuge or lead.grupo_familiar.hijos:
        return (
            f"Tranquilo {nombre}, no es una decisión complicada. "
            "Lo que sí es importante es que tu familia esté cubierta. "
            "Dejame tu número y te contactamos para avanzar."
        )

    # Si es sensible al precio, reforzar accesibilidad
    from app.models.lead import PrioridadCliente
    if lead.prioridad_cliente == PrioridadCliente.ECONOMICO:
        return (
            f"Entiendo {nombre}, el presupuesto es importante. "
            "Justamente por eso te cuente que tenemos opciones que se adaptan a distintos presupuestos. "
            "Te preparo la alternativa que mejor se ajuste a tu presupuesto."
        )

    # Default: ofrecer siguiente paso simple
    return (
        f"No te preocupes {nombre}, no es nada complicado. "
        "Dejame tus datos y un asesor te contacta cuando estés listo."
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
    from app.models.lead import PrioridadCliente, TipoAfiliacion

    # Si tiene familia, cierre de beneficio
    if lead.grupo_familiar.conyuge or lead.grupo_familiar.hijos:
        return CierreComercial(
            tipo_cierre="beneficio",
            respuesta=_cierre_beneficio(lead),
        )

    # Si es empresa, cierre directo
    if lead.tipo_afiliacion == TipoAfiliacion.EMPRESA:
        return CierreComercial(
            tipo_cierre="directo",
            respuesta=_cierre_directo(lead),
        )

    # Si busca rapidez, cierre de urgencia
    if lead.prioridad_cliente == PrioridadCliente.RAPIDEZ:
        return CierreComercial(
            tipo_cierre="urgencia",
            respuesta=_cierre_urgencia(lead),
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
