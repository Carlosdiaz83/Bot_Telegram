"""
Modelos de dominio — Health Advisor AI.

Entidades puras del dominio, independientes de framework y DB.

Uso:
    from app.models.lead import Lead, TipoAfiliacion, EstadoComercial
"""

from app.models.lead import (
    EstadoComercial,
    GrupoFamiliar,
    InteresDetectado,
    Lead,
    TipoAfiliacion,
)

__all__ = [
    "EstadoComercial",
    "GrupoFamiliar",
    "InteresDetectado",
    "Lead",
    "TipoAfiliacion",
]
