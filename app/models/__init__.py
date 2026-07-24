"""
Modelos de dominio — Health Advisor AI.

Entidades puras del dominio, independientes de framework y DB.

Uso:
    from app.models.lead import (
        Lead, TipoAfiliacion, NecesidadPrincipal,
        PrioridadCliente, EstadoComercial, InteresDetectado,
    )
"""

from app.models.lead import (
    EstadoComercial,
    GrupoFamiliar,
    InteresDetectado,
    Lead,
    NecesidadPrincipal,
    PrioridadCliente,
    TipoAfiliacion,
)

__all__ = [
    "EstadoComercial",
    "GrupoFamiliar",
    "InteresDetectado",
    "Lead",
    "NecesidadPrincipal",
    "PrioridadCliente",
    "TipoAfiliacion",
]
