"""
Evaluador comercial de conversaciones.

Analiza el resultado de una simulación y asigna scores
por dimensión para medir la efectividad de Sofía.

Uso:
    from app.services.sales_evaluator import SalesEvaluatorService
    evaluador = SalesEvaluatorService()
    evaluacion = evaluador.evaluar(resultado_simulacion)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from app.models.lead import EstadoComercial, Lead, NecesidadPrincipal, PrioridadCliente, TipoAfiliacion
from app.simulation.engine import ResultadoSimulacion

logger = logging.getLogger(__name__)


@dataclass
class EvaluacionComercial:
    """
    Resultado de la evaluación de una conversación.

    Attributes:
        descubrimiento: Score de descubrimiento de necesidad (0-20).
        calificacion: Score de calificación del lead (0-20).
        valor: Score de presentación de valor (0-20).
        objeciones: Score de manejo de objeciones (0-20).
        cierre: Score de intento de cierre (0-20).
        score_total: Score total (0-100).
        detalle: Explicación del scoring.
        perfil_evaluado: Nombre del perfil evaluado.
    """
    descubrimiento: int = 0
    calificacion: int = 0
    valor: int = 0
    objeciones: int = 0
    cierre: int = 0
    score_total: int = 0
    detalle: str = ""
    perfil_evaluado: str = ""


class SalesEvaluatorService:
    """
    Servicio de evaluación comercial.

    Analiza una conversación simulada y evalúa 5 dimensiones:
    1. Descubrimiento: ¿detectó necesidad?
    2. Calificación: ¿obtuvo datos importantes?
    3. Valor: ¿explicó beneficios?
    4. Objeciones: ¿respondió correctamente?
    5. Cierre: ¿intentó avanzar?
    """

    def evaluar(self, resultado: ResultadoSimulacion) -> EvaluacionComercial:
        """
        Evalúa una conversación simulada.

        Args:
            resultado: Resultado de la simulación.

        Returns:
            EvaluacionComercial con scores por dimensión.
        """
        evaluacion = EvaluacionComercial(perfil_evaluado=resultado.perfil.nombre)

        evaluacion.descubrimiento = self._evaluar_descubrimiento(resultado)
        evaluacion.calificacion = self._evaluar_calificacion(resultado)
        evaluacion.valor = self._evaluar_valor(resultado)
        evaluacion.objeciones = self._evaluar_objeciones(resultado)
        evaluacion.cierre = self._evaluar_cierre(resultado)

        evaluacion.score_total = (
            evaluacion.descubrimiento
            + evaluacion.calificacion
            + evaluacion.valor
            + evaluacion.objeciones
            + evaluacion.cierre
        )

        evaluacion.detalle = self._generar_detalle(evaluacion)

        logger.info(
            "Evaluación %s: total=%d (D:%d, C:%d, V:%d, O:%d, Ci:%d)",
            resultado.perfil.nombre,
            evaluacion.score_total,
            evaluacion.descubrimiento,
            evaluacion.calificacion,
            evaluacion.valor,
            evaluacion.objeciones,
            evaluacion.cierre,
        )

        return evaluacion

    def _evaluar_descubrimiento(self, resultado: ResultadoSimulacion) -> int:
        """
        Evalúa la capacidad de descubrir necesidades del cliente.

        +5 por cada dato extraído: nombre, edad, localidad, necesidad, prioridad.
        """
        score = 0
        lead = resultado.lead_final
        if lead is None:
            return 0

        if lead.nombre is not None:
            score += 5
        if lead.edad is not None:
            score += 5
        if lead.localidad is not None:
            score += 5
        if lead.necesidad_principal is not None:
            score += 5

        return min(score, 20)

    def _evaluar_calificacion(self, resultado: ResultadoSimulacion) -> int:
        """
        Evalúa la calificación del lead.

        +5 por cada campo completo: tipo_afiliacion, grupo_familiar, tiene_aportes, prioridad.
        """
        score = 0
        lead = resultado.lead_final
        if lead is None:
            return 0

        if lead.tipo_afiliacion is not None:
            score += 5
        if lead.grupo_familiar.conyuge or lead.grupo_familiar.hijos:
            score += 5
        if lead.tiene_aportes is not None:
            score += 5
        if lead.prioridad_cliente is not None:
            score += 5

        return min(score, 20)

    def _evaluar_valor(self, resultado: ResultadoSimulacion) -> int:
        """
        Evalúa la presentación de valor.

        +10 si el lead avanzó a etapa PRESENTANDO_VALOR o más allá.
        +10 si el lead tiene necesidad o prioridad definida (argumento personalizado).
        """
        score = 0
        lead = resultado.lead_final
        if lead is None:
            return 0

        etapa = resultado.etapa_final

        # Avanzó a presentación de valor o más allá
        etapas_valor = [
            "presentando_valor",
            "manejando_objeciones",
            "intentando_cierre",
            "calificado",
        ]
        if etapa in etapas_valor:
            score += 10

        # Tiene necesidad o prioridad definida
        if lead.necesidad_principal is not None or lead.prioridad_cliente is not None:
            score += 10

        return min(score, 20)

    def _evaluar_objeciones(self, resultado: ResultadoSimulacion) -> int:
        """
        Evalúa el manejo de objeciones.

        +20 si el lead tuvo objeciones y se manejaron (pasó por MANEJANDO_OBJECIONES).
        +10 si el lead tiene necesidad/prioridad definida (personalización).
        """
        score = 0
        lead = resultado.lead_final
        if lead is None:
            return 0

        etapa = resultado.etapa_final

        # Pasó por manejo de objeciones
        etapas_con_objeciones = [
            "manejando_objeciones",
            "intentando_cierre",
            "calificado",
        ]
        if etapa in etapas_con_objeciones:
            score += 15

        # Perfil completo (puede manejar mejor objeciones)
        if lead.necesidad_principal is not None and lead.prioridad_cliente is not None:
            score += 5

        return min(score, 20)

    def _evaluar_cierre(self, resultado: ResultadoSimulacion) -> int:
        """
        Evalúa el intento de cierre.

        +10 si el lead llegó a INTENTANDO_CIERRE.
        +10 si el resultado es VENDIDO o SEGUIMIENTO.
        """
        score = 0
        lead = resultado.lead_final
        if lead is None:
            return 0

        etapa = resultado.etapa_final
        estado = resultado.estado_final

        # Llegó a intento de cierre
        etapas_cierre = [
            "intentando_cierre",
            "calificado",
        ]
        if etapa in etapas_cierre:
            score += 10

        # Resultado exitoso
        estados_exitosos = {"vendido", "seguimiento"}
        if estado.lower() in estados_exitosos:
            score += 10

        return min(score, 20)

    @staticmethod
    def _generar_detalle(evaluacion: EvaluacionComercial) -> str:
        """Genera una explicación del scoring."""
        partes = []

        if evaluacion.descubrimiento >= 15:
            partes.append("Buen descubrimiento de necesidades")
        elif evaluacion.descubrimiento >= 10:
            partes.append("Descubrimiento parcial")
        else:
            partes.append("Descubrimiento insuficiente")

        if evaluacion.calificacion >= 15:
            partes.append("Calificación completa")
        elif evaluacion.calificacion >= 10:
            partes.append("Calificación parcial")
        else:
            partes.append("Calificación insuficiente")

        if evaluacion.valor >= 15:
            partes.append("Presentación de valor efectiva")
        elif evaluacion.valor >= 10:
            partes.append("Presentación de valor aceptable")
        else:
            partes.append("Sin presentación de valor")

        if evaluacion.objeciones >= 15:
            partes.append("Manejo de objeciones efectivo")
        elif evaluacion.objeciones >= 10:
            partes.append("Manejo de objeciones parcial")
        else:
            partes.append("Sin manejo de objeciones")

        if evaluacion.cierre >= 15:
            partes.append("Cierre efectivo")
        elif evaluacion.cierre >= 10:
            partes.append("Intento de cierre realizado")
        else:
            partes.append("Sin intento de cierre")

        return " | ".join(partes)
