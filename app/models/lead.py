"""
Modelo de dominio: Lead (prospecto comercial).

Representa la información de un cliente potencial durante el proceso
de calificación comercial. Es una entidad pura de dominio, sin
dependencias de base de datos ni frameworks.

Este modelo será utilizado por:
    - LeadQualifierService (lógica de calificación)
    - ServiredRules (clasificación de perfil)
    - IA (para contexto de conversación)
    - CRM (para persistencia futura)
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


# ─────────────────────────────────────────────
# Enums — Datos generales
# ─────────────────────────────────────────────

class InteresDetectado(str, Enum):
    """Interés principal detectado en la consulta inicial."""
    PRECIOS = "precios"
    BENEFICIOS = "beneficios"
    COBERTURA = "cobertura"
    CAMBIO_OBRA_SOCIAL = "cambio_obra_social"
    EMPRESA = "empresa"
    AFILIACION = "afiliacion"
    INFORMACION_GENERAL = "informacion_general"


class EstadoComercial(str, Enum):
    """Estado del lead en el funnel de ventas."""
    NUEVO = "nuevo"
    CONTACTADO = "contactado"
    CALIFICANDO = "calificando"
    INTERESADO = "interesado"
    OBJECION = "objecion"
    INTENTANDO_CIERRE = "intentando_cierre"
    VENDIDO = "vendido"
    PERDIDO = "perdido"
    SEGUIMIENTO = "seguimiento"
    # Compatibilidad con valores anteriores
    CALIFICADO = "calificado"
    DERIVADO = "derivado"
    CERRADO = "cerrado"


# ─────────────────────────────────────────────
# Enums — Datos SERVIRED
# ─────────────────────────────────────────────

class TipoAfiliacion(str, Enum):
    """Tipo de afiliación del cliente."""
    RELACION_DEPENDENCIA = "relacion_dependencia"
    MONOTRIBUTO = "monotributo"
    PARTICULAR = "particular"
    EMPRESA = "empresa"


class NecesidadPrincipal(str, Enum):
    """Necesidad principal del cliente al consultar."""
    PRECIO = "precio"
    BENEFICIOS = "beneficios"
    COBERTURA_FAMILIAR = "cobertura_familiar"
    ACCESO_PRESTADORES = "acceso_prestadores"


class PrioridadCliente(str, Enum):
    """Prioridad o preferencia del cliente al elegir cobertura."""
    ECONOMICO = "economico"
    COMPLETO = "completo"
    FAMILIAR = "familiar"
    RAPIDEZ = "rapidez"


# ─────────────────────────────────────────────
# Modelo de Grupo Familiar
# ─────────────────────────────────────────────

class GrupoFamiliar(BaseModel):
    """
    Composición del grupo familiar para cobertura.

    Solo se contemplan: titular, cónyuge/pareja e hijos.
    No se incluyen padres, hermanos ni otros familiares.
    """
    titular: bool = True
    conyuge: bool = False
    hijos: bool = False


# ─────────────────────────────────────────────
# Modelo principal: Lead
# ─────────────────────────────────────────────

class Lead(BaseModel):
    """
    Prospecto comercial en proceso de calificación.

    Almacena toda la información recopilada durante la conversación
    de venta. El LeadQualifierService actualiza este modelo campo
    por campo a medida que avanza el flujo.

    Attributes:
        lead_id: Identificador único (normalmente el chat_id de Telegram).

        # Datos generales
        nombre: Nombre del cliente.
        edad: Edad del titular.
        localidad: Localidad de residencia.
        telefono: Teléfono del contacto (preparado para uso futuro).
        estado_comercial: Estado actual en el funnel de ventas.

        # Intención
        interes_detectado: Interés principal de la consulta.

        # Datos SERVIRED
        tipo_afiliacion: Tipo de afiliación actual o deseada.
        categoria_monotributo: Categoría de monotributo (A a K).
        tiene_aportes: Si cuenta con aportes previos.
        tiene_recibo_sueldo: Si tiene recibo de sueldo.
        grupo_familiar: Composición del grupo familiar.
        cantidad_hijos: Cantidad de hijos a incluir.
        cantidad_integrantes: Total de personas en el grupo familiar.
        necesidad_principal: Qué busca el cliente en la cobertura.
        prioridad_cliente: Qué valora más al elegir cobertura.
    """
    lead_id: str

    # Datos generales
    nombre: str | None = None
    edad: int | None = None
    localidad: str | None = None
    telefono: str | None = None
    estado_comercial: EstadoComercial = EstadoComercial.NUEVO

    # Intención
    interes_detectado: InteresDetectado | None = None

    # Datos SERVIRED — Situación laboral
    tipo_afiliacion: TipoAfiliacion | None = None
    categoria_monotributo: str | None = None
    tiene_aportes: bool | None = None
    tiene_recibo_sueldo: bool | None = None

    # Datos SERVIRED — Grupo familiar
    grupo_familiar: GrupoFamiliar = Field(default_factory=GrupoFamiliar)
    cantidad_hijos: int = 0
    cantidad_integrantes: int = 1

    # Datos SERVIRED — Perfil
    necesidad_principal: NecesidadPrincipal | None = None
    prioridad_cliente: PrioridadCliente | None = None

    # Scoring comercial
    score: int = 0
    temperatura_lead: str = ""

    def calcular_integrantes(self) -> int:
        """
        Calcula la cantidad total de integrantes del grupo familiar.

        Returns:
            Cantidad total incluyendo al titular.
        """
        total = 1  # Titular siempre presente
        if self.grupo_familiar.conyuge:
            total += 1
        if self.grupo_familiar.hijos:
            total += self.cantidad_hijos
        return total

    def actualizar_grupo_familiar(
        self,
        conyuge: bool = False,
        hijos: bool = False,
        cantidad_hijos: int = 0,
    ) -> None:
        """
        Actualiza el grupo familiar y recalcula integrantes.

        Args:
            conyuge: Si incluye cónyuge/pareja.
            hijos: Si incluye hijos.
            cantidad_hijos: Cantidad de hijos (solo aplica si hijos=True).
        """
        self.grupo_familiar.conyuge = conyuge
        self.grupo_familiar.hijos = hijos
        self.cantidad_hijos = cantidad_hijos if hijos else 0
        self.cantidad_integrantes = self.calcular_integrantes()
