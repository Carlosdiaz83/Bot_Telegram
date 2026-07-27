"""
Servicio de calificación comercial de leads (Lead Qualifier).

Orquesta el flujo de recolección de datos de un prospecto comercial
para SERVIRED. No genera texto directamente — devuelve estados
estructurados que serán interpretados por la capa de IA.

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
    NecesidadPrincipal,
    PrioridadCliente,
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
        proxima_pregunta: Clave de la siguiente pregunta (o None si completo).
        lead: Referencia al lead actualizado.
        listo_para_derivar: True si el lead tiene suficiente información.
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

_INTENCION_PALABRAS: dict[InteresDetectado, list[str]] = {
    InteresDetectado.PRECIOS: [
        "cuánto", "cuanto", "precio", "precios", "costo", "costa", "vale",
        "valor", "platita", "plata", "dinero", "pagar",
        "cotización", "cotizacion", "cotizar", "cuánto cuesta",
    ],
    InteresDetectado.BENEFICIOS: [
        "beneficio", "beneficios", "ventajas", "qué incluye", "que incluye",
        "qué ofrece", "que ofrece", "servicios",
    ],
    InteresDetectado.EMPRESA: [
        "empresa", "empleados", "empleador", "comercio", "local", "negocio",
    ],
    InteresDetectado.CAMBIO_OBRA_SOCIAL: [
        "cambiarme", "cambiar", "cambio", "otra obra", "nueva obra",
        "buscar otra", "me quiero cambiar", "no me gusta",
    ],
    InteresDetectado.COBERTURA: [
        "cubrir", "cubre", "cobertura", "incluye", "qué cubre",
        "que cubre", "qué tapa", "que tapa",
    ],
    InteresDetectado.AFILIACION: [
        "afiliarme", "afiliar", "afiliación", "afiliacion", "darme de alta",
        "querés afiliar", "busco obra social", "sin obra",
        "info", "información", "saber", "conocer", "planes",
        "cómo funciona", "como funciona", "me interesa",
        "quiero", "necesito", "busco",
    ],
    InteresDetectado.INFORMACION_GENERAL: [
        "quería saber",
    ],
}


def clasificar_intencion(texto: str) -> InteresDetectado:
    """
    Clasifica la intención del cliente a partir de su mensaje.

    Args:
        texto: Mensaje del cliente.

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
    """Extrae nombre del mensaje. Patrones: Me llamo X, Soy X, Mi nombre es X, o nombre suelto."""
    # Palabras comunes que NO son nombres
    _NO_NOMBRES = {
        "hola", "buenos", "buenas", "bien", "mal", "gracias", "che",
        "quiero", "necesito", "busco", "puedo", "sí", "si", "no",
        "dale", "ok", "genial", "perfecto", "excelente", "ayuda",
        "info", "información", "precio", "precios", "plan", "planes",
        "cobertura", "servired", "obra", "social", "monotributo",
        "particular", "empresa", "familia", "hijos", "esposa",
        "recibo", "sueldo", "aportes", "cuanto", "cuesta",
    }

    patrones = [
        r"(?:me llamo|soy|mi nombre es|nombre)\s+([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)*)",
    ]
    for patron in patrones:
        match = re.search(patron, texto, re.IGNORECASE)
        if match:
            return match.group(1).strip()

    # Nombre suelto: palabra única con mayúscula inicial (2+ chars)
    palabras = texto.strip().split()
    if len(palabras) == 1:
        palabra = palabras[0]
        if (
            len(palabra) >= 3
            and palabra[0].isupper()
            and palabra.isalpha()
            and palabra.lower() not in _NO_NOMBRES
        ):
            return palabra

    return None


def _extraer_edad(texto: str) -> int | None:
    """Extrae edad del mensaje. Patrones: Tengo 30 años, 30 años, 30 anios."""
    patrones = [
        r"(?:tengo|edad|años?|anios?)\s*(\d{1,3})",
        r"(\d{1,3})\s*(?:años?|anios?)",
    ]
    for patron in patrones:
        match = re.search(patron, texto, re.IGNORECASE)
        if match:
            edad = int(match.group(1))
            if 1 <= edad <= 120:
                return edad
    return None


def _extraer_localidad(texto: str) -> str | None:
    """Extrae localidad. Patrones: Soy de X, Vivo en X, o ciudad suelta."""
    patrones = [
        r"(?:soy de|vivo en|localidad|ciudad)\s+([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)*)",
    ]
    for patron in patrones:
        match = re.search(patron, texto, re.IGNORECASE)
        if match:
            return match.group(1).strip()

    # Buscar ciudades conocidas como palabras sueltas
    ciudades_conocidas = [
        "Córdoba", "Cordoba", "Buenos Aires", "Santa Fe", "Mendoza",
        "Tucumán", "Tucuman", "Salta", "Entre Ríos", "Entre Rios",
        "Chaco", "Corrientes", "Misiones", "San Juan", "La Plata",
        "Mar del Plata", "Rosario", "Villa María", "Villa Carlos Paz",
    ]
    texto_lower = texto.lower()
    for ciudad in ciudades_conocidas:
        if ciudad.lower() in texto_lower:
            return ciudad

    return None


def _detectar_tipo_afiliacion(texto: str) -> TipoAfiliacion | None:
    """Detecta tipo de afiliación: relación dependencia, monotributo, particular, empresa."""
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
    """Detecta composición del grupo familiar (conyuge, hijos, cantidad)."""
    texto_lower = texto.lower()

    tiene_conyuge = any(p in texto_lower for p in [
        "esposa", "esposo", "pareja", "cónyuge", "conyuge",
        "marido", "mujer", "novia", "novio", "concubino",
    ])

    tiene_hijos = any(p in texto_lower for p in [
        "hijo", "hijos", "hija", "hijas", "nenes", "nena",
        "chicos", "chicas", "menores",
    ])

    cantidad_hijos = 0
    if tiene_hijos:
        # Intentar extraer cantidad numérica
        match = re.search(r"(\d+)\s*(?:hijos?|hijas?|nenes?|chicos?|menores?)", texto_lower)
        if match:
            cantidad_hijos = int(match.group(1))
        else:
            # Intentar extraer cantidad en palabras
            palabras_a_numeros = {
                "un": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4,
                "cinco": 5, "seis": 6, "siete": 7, "ocho": 8, "nueve": 9,
            }
            for palabra, num in palabras_a_numeros.items():
                if re.search(rf"{palabra}\s+(?:hijos?|hijas?|nenes?|chicos?|menores?)", texto_lower):
                    cantidad_hijos = num
                    break
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
    """Detecta si el cliente tiene aportes."""
    texto_lower = texto.lower()

    if any(p in texto_lower for p in ["tengo aportes", "con aportes", "aportes"]):
        return True
    if any(p in texto_lower for p in ["sin aportes", "no tengo aportes", "no aporté"]):
        return False

    return None


def _detectar_recibo_sueldo(texto: str) -> bool | None:
    """Detecta si tiene recibo de sueldo."""
    texto_lower = texto.lower()

    if any(p in texto_lower for p in ["recibo de sueldo", "recibo", "sueldo", "boleta"]):
        return True
    if any(p in texto_lower for p in ["sin recibo", "no tengo recibo", "no cobro en blanco"]):
        return False

    return None


def _detectar_necesidad_principal(texto: str) -> NecesidadPrincipal | None:
    """Detecta la necesidad principal del cliente."""
    texto_lower = texto.lower()

    if any(p in texto_lower for p in ["precio", "costo", "económico", "economico", "barato", "accesible"]):
        return NecesidadPrincipal.PRECIO
    if any(p in texto_lower for p in ["beneficio", "beneficios", "ventajas", "qué ofrece"]):
        return NecesidadPrincipal.BENEFICIOS
    if any(p in texto_lower for p in ["familia", "familiar", "hijos", "esposa", "pareja"]):
        return NecesidadPrincipal.COBERTURA_FAMILIAR
    if any(p in texto_lower for p in ["hospital", "clínica", "clinica", "médico", "medico", "doctor", "prestador"]):
        return NecesidadPrincipal.ACCESO_PRESTADORES

    return None


def _detectar_prioridad_cliente(texto: str) -> PrioridadCliente | None:
    """Detecta la prioridad del cliente al elegir cobertura."""
    texto_lower = texto.lower()

    if any(p in texto_lower for p in ["económico", "economico", "barato", "accesible", "más barato", "mas barato"]):
        return PrioridadCliente.ECONOMICO
    if any(p in texto_lower for p in ["completo", "todo", "mejor", "premium"]):
        return PrioridadCliente.COMPLETO
    if any(p in texto_lower for p in ["familia", "familiar", "hijos", "esposa"]):
        return PrioridadCliente.FAMILIAR
    if any(p in texto_lower for p in ["rápido", "rapido", "ya", "urgente", "sin demora"]):
        return PrioridadCliente.RAPIDEZ

    return None


# ─────────────────────────────────────────────
# Servicio principal
# ─────────────────────────────────────────────

class LeadQualifierService:
    """
    Servicio de calificación comercial de leads para SERVIRED.

    Implementa un flujo stateful de 9 pasos:
    1. Nombre
    2. Motivo de consulta (interés)
    3. Situación actual (tipo afiliación)
    4. Aportes (si corresponde)
    5. Grupo familiar
    6. Cantidad de integrantes
    7. Localidad
    8. Edad
    9. Necesidad principal / prioridad

    No genera texto — devuelve QualificationResult con estado estructurado.
    """

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
            "Lead %s — estado: %s, proxima: %s, extraidos: %s",
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
        """Extrae información del mensaje y la asigna al lead."""
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

        # Necesidad principal
        if lead.necesidad_principal is None:
            necesidad = _detectar_necesidad_principal(mensaje)
            if necesidad:
                lead.necesidad_principal = necesidad
                datos_extraidos.append("necesidad_principal")

        # Prioridad del cliente
        if lead.prioridad_cliente is None:
            prioridad = _detectar_prioridad_cliente(mensaje)
            if prioridad:
                lead.prioridad_cliente = prioridad
                datos_extraidos.append("prioridad_cliente")

        return datos_extraidos

    def _determinar_siguiente_pregunta(self, lead: Lead) -> str | None:
        """
        Determina cuál es la siguiente pregunta según la información que falta.

        Flujo:
        1. nombre
        2. interes_detectado (motivo de consulta)
        3. tipo_afiliacion (situación actual)
        4. tiene_aportes (si corresponde)
        5. grupo_familiar
        6. cantidad_hijos / cantidad_integrantes
        7. localidad
        8. edad
        9. necesidad_principal / prioridad_cliente
        """
        # 1. Nombre
        if lead.nombre is None:
            return "nombre"

        # 2. Motivo de consulta
        if lead.interes_detectado is None:
            return "interes_detectado"

        # 3. Situación actual
        if lead.tipo_afiliacion is None:
            return "tipo_afiliacion"

        # 4. Aportes (solo si relación de dependencia)
        if (
            lead.tipo_afiliacion == TipoAfiliacion.RELACION_DEPENDENCIA
            and lead.tiene_aportes is None
        ):
            return "tiene_aportes"

        # 5. Grupo familiar
        if not lead.grupo_familiar.conyuge and not lead.grupo_familiar.hijos:
            return "grupo_familiar"

        # 6. Cantidad de hijos (si mencionó hijos)
        if lead.grupo_familiar.hijos and lead.cantidad_hijos == 0:
            return "cantidad_hijos"

        # 7. Localidad
        if lead.localidad is None:
            return "localidad"

        # 8. Edad
        if lead.edad is None:
            return "edad"

        # 9. Necesidad principal
        if lead.necesidad_principal is None:
            return "necesidad_principal"

        return None
