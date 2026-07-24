"""
Manejo de objeciones comerciales.

Detecta objeciones del cliente y genera respuestas que
validan la preocupación, reforzan valor y orientan al cierre.

Uso:
    from app.services.objection_handler import detectar_objecion, manejar_objecion
    objecion = detectar_objecion("Es muy caro")
    respuesta = manejar_objecion(objecion, lead)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

from app.models.lead import Lead

logger = logging.getLogger(__name__)


class TipoObjecion(str, Enum):
    """Tipos de objeciones detectables."""
    PRECIO = "precio"
    DUDA = "duda"
    PROCRASTINACION = "procrastinacion"
    TIEMPO = "tiempo"
    CONFIANZA = "confianza"
    NINGUNA = "ninguna"


@dataclass
class ResultadoObjecion:
    """
    Resultado del análisis de una objeción.

    Attributes:
        tipo: Tipo de objeción detectada.
        es_objecion: Si el mensaje contiene una objeción.
        respuesta: Respuesta comercial sugerida.
    """
    tipo: TipoObjecion
    es_objecion: bool
    respuesta: str | None = None


# ─────────────────────────────────────────────
# Detección de objeciones
# ─────────────────────────────────────────────

_OBJECION_PALABRAS: dict[TipoObjecion, list[str]] = {
    TipoObjecion.TIEMPO: [
        "no tengo tiempo", "estoy ocupado", "después veo",
        "no ahora", "no puedo ahora", "más tarde",
    ],
    TipoObjecion.PRECIO: [
        "caro", "cuesta", "costo", "dinero", "plata",
        "presupuesto", "no llego", "muy alto", "no puedo pagar",
    ],
    TipoObjecion.DUDA: [
        "no estoy seguro", "no sé si", "no estoy convencido",
        "dudando", "no me queda claro", "necesito pensar",
        "no estoy decidido",
    ],
    TipoObjecion.PROCRASTINACION: [
        "lo voy a pensar", "después", "luego", "mañana",
        "cuando pueda", "ya fue",
    ],
    TipoObjecion.CONFIANZA: [
        "no conozco", "nunca escuché", "no me da confianza",
        "no sé si sirve", "me da miedo", "no confío",
    ],
}


def detectar_objecion(texto: str) -> TipoObjecion:
    """
    Detecta si el mensaje contiene una objeción.

    Args:
        texto: Mensaje del cliente.

    Returns:
        Tipo de objeción detectada o NINGUNA.
    """
    texto_lower = texto.lower()

    for tipo, palabras in _OBJECION_PALABRAS.items():
        for palabra in palabras:
            if palabra in texto_lower:
                return tipo

    return TipoObjecion.NINGUNA


# ─────────────────────────────────────────────
# Respuestas a objeciones
# ─────────────────────────────────────────────

def _responder_precio(lead: Lead) -> str:
    """Responde a objeción de precio."""
    nombre = lead.nombre or "Hola"
    return (
        f"Entiendo {nombre}, es importante cuidar el presupuesto. "
        "En Servired tenemos opciones que se adaptan a distintos presupuestos "
        "para que puedas acceder a beneficios sin pagar de más. "
        "¿Qué monto tenías pensado invertir mensualmente?"
    )


def _responder_duda(lead: Lead) -> str:
    """Responde a objeción de duda/inseguridad."""
    nombre = lead.nombre or "Hola"
    return (
        f"¡No te preocupes {nombre}! Es normal tener dudas. "
        "¿Qué información necesitarías para sentirte más tranquilo? "
        "Puedo contarte todo lo que necesités saber."
    )


def _responder_procrastinacion(lead: Lead) -> str:
    """Responde a objeción de postergación."""
    nombre = lead.nombre or "Hola"
    return (
        f"¡Tranquilo {nombre}! No es nada complicado. "
        "Podemos ir avanzando con lo que necesites cuando te sientas listo. "
        "¿Qué punto te gustaría que evalúemos juntos?"
    )


def _responder_tiempo(lead: Lead) -> str:
    """Responde a objeción de falta de tiempo."""
    nombre = lead.nombre or "Hola"
    return (
        f"¡Entiendo {nombre}! No te quito mucho tiempo. "
        "Solo necesito unos datos y ya dejamos iniciado el proceso. "
        "¿Querés que avancemos rápido?"
    )


def _responder_confianza(lead: Lead) -> str:
    """Responde a objeción de confianza."""
    nombre = lead.nombre or "Hola"
    return (
        f"Es completamente válido {nombre}. Servired es una empresa con trayectoria "
        "y muchos clientes satisfechos. Podes contarme qué te gustaría saber "
        "para que te sientas más tranquilo."
    )


# ─────────────────────────────────────────────
# API pública
# ─────────────────────────────────────────────

def manejar_objecion(tipo: TipoObjecion, lead: Lead) -> str:
    """
    Genera una respuesta para la objeción detectada.

    Args:
        tipo: Tipo de objeción.
        lead: Lead del cliente.

    Returns:
        Respuesta comercial sugerida.
    """
    respuestas = {
        TipoObjecion.PRECIO: _responder_precio,
        TipoObjecion.DUDA: _responder_duda,
        TipoObjecion.PROCRASTINACION: _responder_procrastinacion,
        TipoObjecion.TIEMPO: _responder_tiempo,
        TipoObjecion.CONFIANZA: _responder_confianza,
    }

    handler = respuestas.get(tipo)
    if handler:
        return handler(lead)

    return ""


def analizar_mensaje(texto: str, lead: Lead) -> ResultadoObjecion:
    """
    Analiza un mensaje y devuelve la objeción detectada con su respuesta.

    Args:
        texto: Mensaje del cliente.
        lead: Lead del cliente.

    Returns:
        ResultadoObjecion con tipo, si es objeción, y respuesta sugerida.
    """
    tipo = detectar_objecion(texto)

    if tipo == TipoObjecion.NINGUNA:
        return ResultadoObjecion(tipo=tipo, es_objecion=False)

    respuesta = manejar_objecion(tipo, lead)
    logger.debug("Objeción detectada: %s — respuesta generada", tipo.value)

    return ResultadoObjecion(
        tipo=tipo,
        es_objecion=True,
        respuesta=respuesta,
    )
