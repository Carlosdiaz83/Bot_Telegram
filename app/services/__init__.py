"""
Servicios — Health Advisor AI.

Lógica de negocio orquestadora.

Uso:
    from app.services.lead_qualifier import LeadQualifierService
    from app.services.servired_rules import clasificar_perfil
"""

from app.services.lead_qualifier import LeadQualifierService, QualificationResult
from app.services.servired_rules import clasificar_perfil, PerfilServired

__all__ = [
    "LeadQualifierService",
    "QualificationResult",
    "PerfilServired",
    "clasificar_perfil",
]
