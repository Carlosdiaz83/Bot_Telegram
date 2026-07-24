"""
Estrategia de ventas — Generación de valor comercial.

Analiza el perfil del Lead y genera argumentos comerciales
que Sofía utilizará para presentar valor al cliente.

No inventa coberturas ni precios — genera mensajes orientados
a la necesidad detectada.

Uso:
    from app.services.sales_strategy import generar_argumento
    from app.models.lead import Lead
    argumento = generar_argumento(lead)
"""

from __future__ import annotations

import logging

from app.models.lead import (
    Lead,
    NecesidadPrincipal,
    PrioridadCliente,
    TipoAfiliacion,
)

logger = logging.getLogger(__name__)


def generar_argumento(lead: Lead) -> str:
    """
    Genera un argumento comercial basado en el perfil del lead.

    Args:
        lead: Lead con datos suficientes para generar argumento.

    Returns:
        Mensaje comercial orientado a la necesidad del cliente.
    """
    # Determinar el ángulo principal
    if lead.prioridad_cliente == PrioridadCliente.ECONOMICO:
        return _argumento_precio(lead)
    if lead.prioridad_cliente == PrioridadCliente.FAMILIAR:
        return _argumento_familiar(lead)
    if lead.prioridad_cliente == PrioridadCliente.COMPLETO:
        return _argumento_calidad(lead)
    if lead.prioridad_cliente == PrioridadCliente.RAPIDEZ:
        return _argumento_rapidez(lead)

    # Inferir por necesidad principal
    if lead.necesidad_principal == NecesidadPrincipal.PRECIO:
        return _argumento_precio(lead)
    if lead.necesidad_principal == NecesidadPrincipal.BENEFICIOS:
        return _argumento_beneficios(lead)
    if lead.necesidad_principal == NecesidadPrincipal.COBERTURA_FAMILIAR:
        return _argumento_familiar(lead)
    if lead.necesidad_principal == NecesidadPrincipal.ACCESO_PRESTADORES:
        return _argumento_prestadores(lead)

    # Inferir por grupo familiar
    if lead.grupo_familiar.conyuge or lead.grupo_familiar.hijos:
        return _argumento_familiar(lead)

    # Inferir por situación
    if lead.tipo_afiliacion == TipoAfiliacion.MONOTRIBUTO:
        return _argumento_monotributo(lead)
    if lead.tipo_afiliacion == TipoAfiliacion.EMPRESA:
        return _argumento_empresa(lead)

    return _argumento_generico(lead)


def _argumento_precio(lead: Lead) -> str:
    """Argumento para cliente sensible al precio."""
    nombre = lead.nombre or "Hola"
    return (
        f"¡Perfecto {nombre}! Entiendo que el presupuesto es importante. "
        "En Servired tenemos opciones que se adaptan a distintos presupuestos "
        "para que puedas acceder a una cobertura sin pagar de más. "
        "¿Querés que te cuente las alternativas que tenemos?"
    )


def _argumento_familiar(lead: Lead) -> str:
    """Argumento para cliente que busca cobertura familiar."""
    nombre = lead.nombre or "Hola"
    integrantes = lead.cantidad_integrantes
    return (
        f"¡Qué bueno {nombre}! Proteger a la familia es lo más importante. "
        f"Con Servired podemos armar una cobertura para los {integrantes} integrantes "
        "de tu grupo familiar, para que todos tengan la tranquilidad que merecen. "
        "¿Querés que veamos juntos las opciones?"
    )


def _argumento_calidad(lead: Lead) -> str:
    """Argumento para cliente que busca cobertura completa."""
    nombre = lead.nombre or "Hola"
    return (
        f"¡Excelente {nombre}! Si buscás una cobertura completa, "
        "Servired tiene planes que te dan acceso a una amplia red de prestadores "
        "y beneficios integral para que estés tranquilo. "
        "¿Te gustaría que te cuente los detalles?"
    )


def _argumento_beneficios(lead: Lead) -> str:
    """Argumento para cliente que busca beneficios."""
    nombre = lead.nombre or "Hola"
    return (
        f"¡Genial {nombre}! Servired ofrece muchos beneficios: "
        "acceso a consultas, estudios, odontología y más. "
        "¿Querés que te cuente en detalle qué incluye cada plan?"
    )


def _argumento_prestadores(lead: Lead) -> str:
    """Argumento para cliente que busca acceso a prestadores."""
    nombre = lead.nombre or "Hola"
    return (
        f"¡Perfecto {nombre}! Servired tiene una amplia red de prestadores "
        "para que puedas elegir dónde atenderte. "
        "¿Hay algún prestador o zona en particular que necesites?"
    )


def _argumento_monotributista(lead: Lead) -> str:
    """Argumento específico para monotributistas."""
    nombre = lead.nombre or "Hola"
    return (
        f"¡Hola {nombre}! Como monotributista, Servired tiene opciones pensadas "
        "para vos. Podés acceder a una cobertura que se adapte a tu situación "
        "y la de tu familia. ¿Querés que veamos las alternativas?"
    )


def _argumento_empresa(lead: Lead) -> str:
    """Argumento para empresa que busca cobertura para empleados."""
    nombre = lead.nombre or "Hola"
    return (
        f"¡Hola {nombre}! Para empresas, Servired ofrece planes grupales "
        "con beneficios para vos y tus empleados. Es una excelente forma "
        "de cuidar a tu equipo. ¿Querés que te cuente las opciones?"
    )


def _argumento_generico(lead: Lead) -> str:
    """Argumento genérico cuando no se detecta perfil específico."""
    nombre = lead.nombre or "Hola"
    return (
        f"¡Hola {nombre}! Servired tiene diversas opciones de cobertura "
        "para que puedas elegir la que mejor se adapte a tus necesidades. "
        "¿Querés que te cuente las alternativas que tenemos?"
    )


def generar_presentacion_inicial() -> str:
    """Genera el mensaje de bienvenida de Sofía."""
    return (
        "¡Hola! Soy Sofía 😊, asistente de Servired. "
        "Te voy a ayudar a encontrar la opción más conveniente para vos. "
        "¿Cómo te llamás?"
    )


def generar_pregunta_grupo_familiar() -> str:
    """Genera la pregunta sobre grupo familiar."""
    return (
        "¿La cobertura sería para vos o querés incluir a tu familia?"
    )


def generar_pregunta_prioridad() -> str:
    """Genera la pregunta sobre prioridad."""
    return (
        "¿Qué es lo más importante para vos en un servicio de salud? "
        "Precio, beneficios, cobertura familiar o acceso a prestadores?"
    )


def generar_pregunta_situacion_actual() -> str:
    """Genera la pregunta sobre situación actual de cobertura."""
    return (
        "¿Actualmente tenés algún tipo de cobertura? "
        "¿Recibo de sueldo, monotributo o buscás una afiliación particular?"
    )
