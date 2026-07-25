"""
Servicios — Sofía Comercial AI.

Lógica de negocio orquestadora.

Uso:
    from app.services.lead_qualifier import LeadQualifierService
    from app.services.servired_rules import clasificar_perfil
    from app.services.conversation_manager import ConversationManager
    from app.services.sales_strategy import generar_argumento
    from app.services.objection_handler import analizar_mensaje
    from app.services.closing_strategy import intentar_cierre
    from app.services.sales_evaluator import SalesEvaluatorService
    from app.services.sales_report import SalesReportService
    from app.services.sales_quality_rules import SalesQualityRules
"""

from app.services.lead_qualifier import LeadQualifierService, QualificationResult
from app.services.servired_rules import clasificar_perfil, PerfilServired
from app.services.conversation_manager import ConversationManager
from app.services.sales_strategy import generar_argumento
from app.services.objection_handler import analizar_mensaje
from app.services.closing_strategy import intentar_cierre
from app.services.sales_evaluator import SalesEvaluatorService
from app.services.sales_report import SalesReportService
from app.services.sales_quality_rules import SalesQualityRules

__all__ = [
    "ConversationManager",
    "LeadQualifierService",
    "PerfilServired",
    "QualificationResult",
    "SalesEvaluatorService",
    "SalesQualityRules",
    "SalesReportService",
    "analizar_mensaje",
    "clasificar_perfil",
    "generar_argumento",
    "intentar_cierre",
]
