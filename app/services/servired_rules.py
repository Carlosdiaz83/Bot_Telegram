"""
Reglas comerciales SERVIRED.

Analiza el perfil de un Lead calificado y devuelve información
estructurada para orientar la respuesta comercial.

Este módulo NO recomienda planes — solo clasifica el perfil
del cliente para que la IA pueda generar una respuesta adecuada.

Uso:
    from app.services.servired_rules import ServiredRules, clasificar_perfil
    from app.models.lead import Lead

    lead = Lead(lead_id="123", ...)
    perfil = clasificar_perfil(lead)
    # perfil → PerfilServired(perfil="familia", tipo_cliente="sensible_precio", ...)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.models.lead import (
    InteresDetectado,
    Lead,
    NecesidadPrincipal,
    PrioridadCliente,
    TipoAfiliacion,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Resultado de clasificación
# ─────────────────────────────────────────────

@dataclass(frozen=True)
class PerfilServired:
    """
    Clasificación del perfil del cliente para SERVIRED.

    Attributes:
        perfil: Categoría del cliente (solo, familia, empresa, etc.).
        tipo_cliente: Comportamiento de compra (sensible_precio, busqueda_calidad, etc.).
        requiere_asesor: Si el lead necesita atención personalizada.
        razon: Breve explicación de la clasificación.
    """
    perfil: str
    tipo_cliente: str
    requiere_asesor: bool
    razon: str


# ─────────────────────────────────────────────
# Reglas de clasificación
# ─────────────────────────────────────────────

def _clasificar_perfil(lead: Lead) -> str:
    """
    Clasifica al cliente en una categoría de perfil.

    Categorías:
        - solo: solo titular
        - familia: titular + al menos 1 integrante
        - empresa: afiliación empresarial
    """
    if lead.tipo_afiliacion == TipoAfiliacion.EMPRESA:
        return "empresa"

    if lead.grupo_familiar.conyuge or lead.grupo_familiar.hijos:
        return "familia"

    return "solo"


def _clasificar_tipo_cliente(lead: Lead) -> str:
    """
    Clasifica el comportamiento de compra del cliente.

    Categorías:
        - sensible_precio: prioriza costo
        - busqueda_calidad: prioriza cobertura completa
        - familiar_proteccion: prioriza grupo familiar
        - rapido: quiere resolver rápido
    """
    if lead.prioridad_cliente == PrioridadCliente.ECONOMICO:
        return "sensible_precio"

    if lead.prioridad_cliente == PrioridadCliente.COMPLETO:
        return "busqueda_calidad"

    if lead.prioridad_cliente == PrioridadCliente.FAMILIAR:
        return "familiar_proteccion"

    if lead.prioridad_cliente == PrioridadCliente.RAPIDEZ:
        return "rapido"

    # Inferir por datos del lead
    if lead.grupo_familiar.conyuge or lead.grupo_familiar.hijos:
        return "familiar_proteccion"

    if lead.necesidad_principal == NecesidadPrincipal.PRECIO:
        return "sensible_precio"

    if lead.necesidad_principal == NecesidadPrincipal.BENEFICIOS:
        return "busqueda_calidad"

    return "generico"


def _determinar_requiere_asesor(lead: Lead) -> bool:
    """
    Determina si el lead necesita atención de un asesor humano.

    Requiere asesor si:
        - Es empresa
        - Tiene más de 4 integrantes
        - Tiene dudas específicas (cambio de obra social)
    """
    if lead.tipo_afiliacion == TipoAfiliacion.EMPRESA:
        return True

    if lead.cantidad_integrantes > 4:
        return True

    if lead.interes_detectado == InteresDetectado.CAMBIO_OBRA_SOCIAL:
        return True

    return False


def _generar_razon(lead: Lead, perfil: str, tipo_cliente: str) -> str:
    """
    Genera una razón breve de la clasificación.
    """
    partes: list[str] = []

    if perfil == "familia":
        integrantes = lead.cantidad_integrantes
        partes.append(f"Grupo familiar de {integrantes} personas")
    elif perfil == "empresa":
        partes.append("Cobertura empresarial")
    else:
        partes.append("Cobertura individual")

    if tipo_cliente == "sensible_precio":
        partes.append("busca precio accesible")
    elif tipo_cliente == "familiar_proteccion":
        partes.append("protege a su familia")
    elif tipo_cliente == "busqueda_calidad":
        partes.append("busca cobertura completa")
    elif tipo_cliente == "rapido":
        partes.append("quiere resolver rápido")

    if lead.interes_detectado:
        partes.append(f"interesado en {lead.interes_detectado.value}")

    return ". ".join(partes)


# ─────────────────────────────────────────────
# API pública
# ─────────────────────────────────────────────

def clasificar_perfil(lead: Lead) -> PerfilServired:
    """
    Clasifica el perfil de un lead calificado para SERVIRED.

    Analiza los datos del Lead y devuelve un PerfilServired con
    la categoría, tipo de cliente y si requiere asesor.

    Args:
        lead: Lead con datos suficientes para clasificar.

    Returns:
        PerfilServired con la clasificación.
    """
    perfil = _clasificar_perfil(lead)
    tipo_cliente = _clasificar_tipo_cliente(lead)
    requiere_asesor = _determinar_requiere_asesor(lead)
    razon = _generar_razon(lead, perfil, tipo_cliente)

    logger.debug(
        "Lead %s clasificado — perfil=%s, tipo=%s, asesor=%s",
        lead.lead_id,
        perfil,
        tipo_cliente,
        requiere_asesor,
    )

    return PerfilServired(
        perfil=perfil,
        tipo_cliente=tipo_cliente,
        requiere_asesor=requiere_asesor,
        razon=razon,
    )
