"""
Laboratorio de entrenamiento comercial.

Permite ejecutar simulaciones, evaluar comportamiento,
detectar errores y generar reportes de evolución.

Uso:
    from app.training import TrainingEngine
    trainer = TrainingEngine()
    resultado = trainer.ejecutar(perfil="cliente_busca_precio")
"""

from app.training.engine import (
    TrainingEngine,
    ResultadoEntrenamiento,
    ErrorComercial,
)

__all__ = [
    "TrainingEngine",
    "ResultadoEntrenamiento",
    "ErrorComercial",
]
