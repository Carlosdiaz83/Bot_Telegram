"""
Servicio de calificación comercial de leads (Lead Qualifier).

Orquesta el flujo de recolección de datos de un prospecto comercial.
No genera texto directamente — devuelve estados estructurados que
serán interpretados por la capa de IA para generar la respuesta.

Responsabilidades:
    - Detectar la intención del cliente a partir de su mensaje.
    - Saber qué información falta en el perfil del lead.
    - Decidir cuál es la siguiente pregunta a realizar.
    - Actualizar el perfil del lead con la información extraída.
    - Detectar cuándo un lead está listo para ser derivado.

Uso:
    qualifier = LeadQualifierService()
    resultado = qualifier.process_message(lead, "Quiero precios para mi familia")
    # resultado → QualificationResult(estado=..., proxima_pregunta=..., lead=...)
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field

from app.models.lead import (
    EstadoComercial,
    InteresDetectado,
    Lead,
    TipoAfiliacion,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Resultado de calificación
# ─────────────────────────────────────────────

@dataclass
class QualificationResult:
    """
    Resultado estructurado del procesamiento de un mensaje.

    Attributes:
        estado: Estado comercial actual del lead.
        proxima_pregunta: Clave de la siguiente pregunta a realizar (o None si está completo).
        lead: Referencia al lead actualizado.
        listo_para_derivar: True si el lead tiene suficiente información para un asesor.
        datos_extraidos: Campos que se actualizaron con este mensaje.
    """
    estado: EstadoComercial
    proxima_pregunta: str | None
    lead: Lead
    listo_para_derivar: bool = False
    datos_extraidos: list[str] = field(default_factory=list)


# ─────────────────────────────────────────────
# Clasificador de intención (sin IA)
# ─────────────────────────────────────────────

# Palabras clave para clasificar intención
# Orden: EMPRESA y MONOTRIBUTO antes de COBERTURA para evitar falsos positivos
_INTENCION_PALABRAS: dict[InteresDetectado, list[str]] = {
    InteresDetectado.PRECIO: [
        "cuánto", "cuanto", "precio", "costo", "costa", "vale", "valor",
        "platita", "plata", "dinero", "pagar",
    ],
    InteresDetectado.EMPRESA: [
        "empresa", "empleados", "empleador", "comercio", "local",
        "negocio",
    ],
    InteresDetectado.MONOTRIBUTO: [
        "monotributo", "monotributista", "monotribut",
    ],
    InteresDetectado.CAMBIO_OBRA_SOCIAL: [
        "cambiarme", "cambiar", "cambio", "otra obra", "nueva obra",
        "buscar otra", "me quiero cambiar", "no me gusta",
    ],
    InteresDetectado.COBERTURA: [
        "cubrir", "cubre", "cobertura", "incluye", "qué cubre",
        "que cubre", "servicio", "plan", "planes",
    ],
    InteresDetectado.INFORMACION_GENERAL: [
        "información", "informacion", "saber", "conocer", "qué es",
        "que es", "como funciona", "cómo funciona", "quería saber",
    ],
}


def clasificar_intencion(texto: str) -> InteresDetectado:
    """
    Clasifica la intención del cliente a partir de su mensaje.

    Utiliza匹配 por palabras clave (sin IA) para determinar
    el interés principal del cliente.

    Args:
        texto: Mensaje del cliente en minúsculas.

    Returns:
        Interés detectado (default: INFORMACION_GENERAL).
    """
    texto_lower = texto.lower()

    for interes, palabras in _INTENCION_PALABRAS.items():
        for palabra in palabras:
            if palabra in texto_lower:
                return interes

    return InteresDetectado.INFORMACION_GENERAL


# ─────────────────────────────────────────────
# Extracción de datos del mensaje
# ─────────────────────────────────────────────

def _extraer_nombre(texto: str) -> str | None:
    """
    Extrae el nombre del mensaje del cliente.

    Maneja patrones como:
        - "Me llamo Juan"
        - "Soy María"
        - "Juan"
        - "Mi nombre es Carlos"
    """
    patrones = [
        r"(?:me llamo|soy|mi nombre es|nombre)\s+([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)*)",
    ]
    for patron in patrones:
        match = re.search(patron, texto, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def _extraer_edad(texto: str) -> int | None:
    """
    Extrae la edad del mensaje.

    Maneja patrones como:
        - "Tengo 30 años"
        - "30 años"
        - "30"
    """
    patrones = [
        r"(?:tengo|edad|años?)\s*(\d{1,3})",
        r"(\d{1,3})\s*(?:años?)",
    ]
    for patron in patrones:
        match = re.search(patron, texto, re.IGNORECASE)
        if match:
            edad = int(match.group(1))
            if 1 <= edad <= 120:
                return edad
    return None


def _extraer_localidad(texto: str) -> str | None:
    """
    Extrae la localidad del mensaje.

    Maneja patrones como:
        - "Soy de Córdoba"
        - "Vivo en Buenos Aires"
        - "Villa Carlos Paz"
    """
    patrones = [
        r"(?:soy de|vivo en|localidad|ciudad)\s+([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)*)",
    ]
    for patron in patrones:
        match = re.search(patron, texto, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def _detectar_tipo_afiliacion(texto: str) -> TipoAfiliacion | None:
    """
    Detecta el tipo de afiliación a partir del mensaje.

    Args:
        texto: Mensaje del cliente.

    Returns:
        Tipo de afiliación detectado o None.
    """
    texto_lower = texto.lower()

    if any(p in texto_lower for p in ["monotributo", "monotributista", "monotribut"]):
        return TipoAfiliacion.MONOTRIBUTO
    if any(p in texto_lower for p in ["empresa", "empleados", "empleador", "comercio"]):
        return TipoAfiliacion.EMPRESA
    if any(p in texto_lower for p in ["recibo", "sueldo", "empleado", "dependencia", "contrato"]):
        return TipoAfiliacion.RELACION_DEPENDENCIA
    if any(p in texto_lower for p in ["particular", "sin obra", "sin cobertura", "busco obra"]):
        return TipoAfiliacion.PARTICULAR

    return None


def _detectar_grupo_familiar(texto: str) -> dict | None:
    """
    Detecta la composición del grupo familiar.

    Returns:
        Dict con conyuge, hijos, cantidad_hijos o None.
    """
    texto_lower = texto.lower()

    tiene_conyuge = any(p in texto_lower for p in [
        "esposa", "esposo", "pareja", "cónyuge", "conyuge",
        "marido", "mujer", "novia", "novio", "concubino",
    ])

    tiene_hijos = any(p in texto_lower for p in [
        "hijo", "hijos", "hija", "hijas", "nenes", "nena", "nenes",
        "chicos", "chicas", "menores",
    ])

    cantidad_hijos = 0
    if tiene_hijos:
        # Intentar extraer cantidad de hijos
        match = re.search(r"(\d+)\s*(?:hijos?|hijas?|nenes?|chicos?|menores?)", texto_lower)
        if match:
            cantidad_hijos = int(match.group(1))
        else:
            # Asumir al menos 1 si menciona hijos sin cantidad
            cantidad_hijos = 1

    if not tiene_conyuge and not tiene_hijos:
        return None

    return {
        "conyuge": tiene_conyuge,
        "hijos": tiene_hijos,
        "cantidad_hijos": cantidad_hijos,
    }


def _detectar_tiene_aportes(texto: str) -> bool | None:
    """
    Detecta si el cliente menciona tener aportes.

    Returns:
        True si tiene aportes, False si no, None si no se detecta.
    """
    texto_lower = texto.lower()

    if any(p in texto_lower for p in ["tengo aportes", "con aportes", "aportes"]):
        return True
    if any(p in texto_lower for p in ["sin aportes", "no tengo aportes", "no aporté"]):
        return False

    return None


def _detectar_recibo_sueldo(texto: str) -> bool | None:
    """
    Detecta si el cliente menciona tener recibo de sueldo.

    Returns:
        True si tiene recibo, False si no, None si no se detecta.
    """
    texto_lower = texto.lower()

    if any(p in texto_lower for p in ["recibo de sueldo", "recibo", "sueldo", "boleta"]):
        return True
    if any(p in texto_lower for p in ["sin recibo", "no tengo recibo", "no cobro en blanco"]):
        return False

    return None


def _detectar_respuesta_bool(texto: str) -> bool | None:
    """
    Detecta respuestas afirmativas o negativas simples.

    Returns:
        True si afirmativo, False si negativo, None si no se detecta.
    """
    texto_lower = texto.lower().strip()

    afirmativas = ["sí", "si", "claro", "obvio", "dale", "bueno", "ok", "s", "yes", "afirmativo"]
    negativas = ["no", "nah", "nop", "para nada", "negativo"]

    if texto_lower in afirmativas:
        return True
    if texto_lower in negativas:
        return False

    return None


# ─────────────────────────────────────────────
# Servicio principal
# ─────────────────────────────────────────────

class LeadQualifierService:
    """
    Servicio de calificación comercial de leads.

    Implementa un flujo stateful que:
    1. Recibe el mensaje del cliente y el lead actual.
    2. Extrae información del mensaje.
    3. Actualiza el lead con los datos detectados.
    4. Determina la siguiente pregunta (o si el lead está listo).

    No genera texto — devuelve QualificationResult con estado estructurado.
    """

    # Orden de preguntas del flujo de calificación
    FLUJO_PREGUNTAS: list[str] = [
        "nombre",
        "tipo_afiliacion",
        "tiene_aportes",
        "recibo_sueldo",
        "grupo_familiar",
        "cantidad_hijos",
        "cantidad_integrantes",
        "localidad",
        "edad",
    ]

    def process_message(self, lead: Lead, mensaje: str) -> QualificationResult:
        """
        Procesa un mensaje del cliente y actualiza el lead.

        Args:
            lead: Estado actual del lead.
            mensaje: Texto del mensaje del cliente.

        Returns:
            QualificationResult con el estado actualizado y la siguiente acción.
        """
        logger.debug("Procesando mensaje de lead %s: %s", lead.lead_id, mensaje[:50])

        # 1. Detectar intención si es lead nuevo
        datos_extraidos: list[str] = []
        if lead.interes_detectado is None:
            lead.interes_detectado = clasificar_intencion(mensaje)
            datos_extraidos.append("interes_detectado")

        # 2. Extraer datos del mensaje
        datos_extraidos.extend(self._extraer_datos(lead, mensaje))

        # 3. Determinar siguiente paso
        proxima_pregunta = self._determinar_siguiente_pregunta(lead)

        # 4. Actualizar estado comercial
        if lead.estado_comercial == EstadoComercial.NUEVO:
            lead.estado_comercial = EstadoComercial.CALIFICANDO

        # 5. Verificar si está listo para derivar
        listo_para_derivar = proxima_pregunta is None

        if listo_para_derivar:
            lead.estado_comercial = EstadoComercial.CALIFICADO
            proxima_pregunta = None
            logger.info("Lead %s calificado — listo para derivar", lead.lead_id)

        logger.debug(
            "Lead %s — estado: %s, proxima_pregunta: %s, datos_extraidos: %s",
            lead.lead_id,
            lead.estado_comercial.value,
            proxima_pregunta,
            datos_extraidos,
        )

        return QualificationResult(
            estado=lead.estado_comercial,
            proxima_pregunta=proxima_pregunta,
            lead=lead,
            listo_para_derivar=listo_para_derivar,
            datos_extraidos=datos_extraidos,
        )

    def _extraer_datos(self, lead: Lead, mensaje: str) -> list[str]:
        """
        Extrae información del mensaje y la asigna al lead.

        Returns:
            Lista de nombres de campos que fueron actualizados.
        """
        datos_extraidos: list[str] = []

        # Nombre
        if lead.nombre is None:
            nombre = _extraer_nombre(mensaje)
            if nombre:
                lead.nombre = nombre
                datos_extraidos.append("nombre")

        # Edad
        if lead.edad is None:
            edad = _extraer_edad(mensaje)
            if edad:
                lead.edad = edad
                datos_extraidos.append("edad")

        # Localidad
        if lead.localidad is None:
            localidad = _extraer_localidad(mensaje)
            if localidad:
                lead.localidad = localidad
                datos_extraidos.append("localidad")

        # Tipo de afiliación
        if lead.tipo_afiliacion is None:
            tipo = _detectar_tipo_afiliacion(mensaje)
            if tipo:
                lead.tipo_afiliacion = tipo
                datos_extraidos.append("tipo_afiliacion")

        # Aportes
        if lead.tiene_aportes is None:
            aportes = _detectar_tiene_aportes(mensaje)
            if aportes is not None:
                lead.tiene_aportes = aportes
                datos_extraidos.append("tiene_aportes")

        # Recibo de sueldo
        if lead.tiene_recibo_sueldo is None:
            recibo = _detectar_recibo_sueldo(mensaje)
            if recibo is not None:
                lead.tiene_recibo_sueldo = recibo
                datos_extraidos.append("tiene_recibo_sueldo")

        # Grupo familiar
        if lead.grupo_familiar.conyuge is False and lead.grupo_familiar.hijos is False:
            gf = _detectar_grupo_familiar(mensaje)
            if gf:
                lead.actualizar_grupo_familiar(
                    conyuge=gf["conyuge"],
                    hijos=gf["hijos"],
                    cantidad_hijos=gf["cantidad_hijos"],
                )
                datos_extraidos.append("grupo_familiar")

        return datos_extraidos

    def _determinar_siguiente_pregunta(self, lead: Lead) -> str | None:
        """
        Determina cuál es la siguiente pregunta según la información que falta.

        Returns:
            Clave de la pregunta pendiente o None si toda la información está completa.
        """
        if lead.nombre is None:
            return "nombre"
        if lead.tipo_afiliacion is None:
            return "tipo_afiliacion"
        if lead.tiene_aportes is None:
            return "tiene_aportes"

        # Si tiene relación de dependencia, preguntar por recibo
        if (
            lead.tipo_afiliacion == TipoAfiliacion.RELACION_DEPENDENCIA
            and lead.tiene_recibo_sueldo is None
        ):
            return "recibo_sueldo"

        if not lead.grupo_familiar.conyuge and not lead.grupo_familiar.hijos:
            return "grupo_familiar"

        if lead.grupo_familiar.hijos and lead.cantidad_hijos == 0:
            return "cantidad_hijos"

        if lead.cantidad_integrantes <= 1:
            return "cantidad_integrantes"

        if lead.localidad is None:
            return "localidad"
        if lead.edad is None:
            return "edad"

        return None

    def _verificar_listo_para_derivar(self, lead: Lead) -> bool:
        """
        Verifica si el lead tiene suficiente información para ser derivado a un asesor.

        Criterios mínimos:
            - Tiene nombre
            - Tiene tipo de afiliación
            - Ha respondido sobre grupo familiar (solo, con pareja, o con hijos)
        """
        # Verificar que el usuario respondió sobre grupo familiar
        grupo_familiar_respondido = (
            lead.grupo_familiar.conyuge
            or lead.grupo_familiar.hijos
            or lead.cantidad_integrantes == 1  # Solo titular
        )

        return (
            lead.nombre is not None
            and lead.tipo_afiliacion is not None
            and grupo_familiar_respondido
        )
