"""
Servicio de reportes comerciales.

Genera reportes consolidados a partir de múltiples
entrenamientos para analizar el desempeño de Sofía.

Uso:
    from app.services.sales_report import SalesReportService
    reporte_svc = SalesReportService()
    reporte = reporte_svc.generar_reporte(resultados)
    texto = reporte_svc.generar_texto(reporte)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.training.engine import ResultadoEntrenamiento

logger = logging.getLogger(__name__)


@dataclass
class ReporteComercial:
    """
    Reporte consolidado de entrenamientos.

    Attributes:
        score_promedio: Score promedio de todos los entrenamientos.
        scores_por_dimension: Promedio de cada dimensión.
        scores_por_perfil: Score por perfil.
        fortalezas_por_perfil: Fortalezas detectadas por perfil.
        debilidades_por_perfil: Debilidades detectadas por perfil.
        total_simulaciones: Total de simulaciones ejecutadas.
        tasa_exito: Porcentaje de simulaciones exitosas.
        total_errores: Total de errores detectados.
    """
    score_promedio: int = 0
    scores_por_dimension: dict[str, int] = field(default_factory=dict)
    scores_por_perfil: dict[str, int] = field(default_factory=dict)
    fortalezas_por_perfil: dict[str, list[str]] = field(default_factory=dict)
    debilidades_por_perfil: dict[str, list[str]] = field(default_factory=dict)
    total_simulaciones: int = 0
    tasa_exito: float = 0.0
    total_errores: int = 0


class SalesReportService:
    """
    Servicio de generación de reportes comerciales.

    Analiza múltiples resultados de entrenamiento y genera
    un reporte consolidado con métricas y recomendaciones.
    """

    def generar_reporte(
        self, resultados: list[ResultadoEntrenamiento]
    ) -> ReporteComercial:
        """
        Genera un reporte consolidado.

        Args:
            resultados: Lista de resultados de entrenamiento.

        Returns:
            ReporteComercial con métricas consolidadas.
        """
        if not resultados:
            return ReporteComercial()

        reporte = ReporteComercial(total_simulaciones=len(resultados))

        # Score promedio
        scores = [r.score_final for r in resultados]
        reporte.score_promedio = sum(scores) // len(scores)

        # Scores por dimensión
        reporte.scores_por_dimension = self._calcular_scores_dimensiones(resultados)

        # Scores por perfil
        reporte.scores_por_perfil = {
            r.perfil: r.score_final for r in resultados
        }

        # Fortalezas y debilidades por perfil
        for r in resultados:
            fortalezas = self._analizar_fortalezas(r)
            debilidades = self._analizar_debilidades(r)
            if fortalezas:
                reporte.fortalezas_por_perfil[r.perfil] = fortalezas
            if debilidades:
                reporte.debilidades_por_perfil[r.perfil] = debilidades

        # Tasa de éxito
        exitosos = sum(
            1 for r in resultados if r.resultado_simulacion.exitosa
        )
        reporte.tasa_exito = (exitosos / len(resultados)) * 100

        # Total de errores
        reporte.total_errores = sum(len(r.errores) for r in resultados)

        logger.info(
            "Reporte generado: %d simulaciones, score promedio: %d, "
            "tasa éxito: %.1f%%, errores: %d",
            reporte.total_simulaciones,
            reporte.score_promedio,
            reporte.tasa_exito,
            reporte.total_errores,
        )

        return reporte

    def generar_texto(self, reporte: ReporteComercial) -> str:
        """
        Genera texto formateado del reporte.

        Args:
            reporte: ReporteComercial a formatear.

        Returns:
            Texto formateado para mostrar.
        """
        lineas = []
        lineas.append("=" * 50)
        lineas.append("REPORTE COMERCIAL — SOFÍA SERVIRED")
        lineas.append("=" * 50)
        lineas.append("")

        # Resumen general
        lineas.append("## Resumen General")
        lineas.append(f"  Score promedio: {reporte.score_promedio}/100")
        lineas.append(f"  Total simulaciones: {reporte.total_simulaciones}")
        lineas.append(f"  Tasa de éxito: {reporte.tasa_exito:.1f}%")
        lineas.append(f"  Total errores: {reporte.total_errores}")
        lineas.append("")

        # Scores por dimensión
        lineas.append("## Scores por Dimensión")
        for dimension, score in reporte.scores_por_dimension.items():
            barra = "█" * (score // 5) + "░" * (20 - score // 5)
            lineas.append(f"  {dimension:20s}: {score:2d}/20 {barra}")
        lineas.append("")

        # Scores por perfil
        lineas.append("## Scores por Perfil")
        for perfil, score in sorted(
            reporte.scores_por_perfil.items(),
            key=lambda x: x[1],
            reverse=True,
        ):
            lineas.append(f"  {perfil:35s}: {score:3d}/100")
        lineas.append("")

        # Fortalezas
        if reporte.fortalezas_por_perfil:
            lineas.append("## Fortalezas por Perfil")
            for perfil, fortalezas in reporte.fortalezas_por_perfil.items():
                lineas.append(f"  {perfil}:")
                for f in fortalezas:
                    lineas.append(f"    + {f}")
            lineas.append("")

        # Debilidades
        if reporte.debilidades_por_perfil:
            lineas.append("## Debilidades por Perfil")
            for perfil, debilidades in reporte.debilidades_por_perfil.items():
                lineas.append(f"  {perfil}:")
                for d in debilidades:
                    lineas.append(f"    - {d}")
            lineas.append("")

        lineas.append("=" * 50)
        return "\n".join(lineas)

    def _calcular_scores_dimensiones(
        self, resultados: list[ResultadoEntrenamiento]
    ) -> dict[str, int]:
        """Calcula el promedio de cada dimensión."""
        n = len(resultados)
        return {
            "descubrimiento": sum(
                r.evaluacion.descubrimiento for r in resultados
            ) // n,
            "calificacion": sum(
                r.evaluacion.calificacion for r in resultados
            ) // n,
            "valor": sum(
                r.evaluacion.valor for r in resultados
            ) // n,
            "objeciones": sum(
                r.evaluacion.objeciones for r in resultados
            ) // n,
            "cierre": sum(
                r.evaluacion.cierre for r in resultados
            ) // n,
        }

    @staticmethod
    def _analizar_fortalezas(resultado: ResultadoEntrenamiento) -> list[str]:
        """Analiza las fortalezas de un entrenamiento."""
        fortalezas: list[str] = []
        ev = resultado.evaluacion

        if ev.descubrimiento >= 15:
            fortalezas.append("Detecta necesidades del cliente")
        if ev.calificacion >= 15:
            fortalezas.append("Calificación completa del lead")
        if ev.valor >= 15:
            fortalezas.append("Presenta valor personalizado")
        if ev.objeciones >= 15:
            fortalezas.append("Maneja objeciones efectivamente")
        if ev.cierre >= 15:
            fortalezas.append("Cierra con technique adecuada")

        if not resultado.errores:
            fortalezas.append("Sin errores comerciales detectados")

        return fortalezas

    @staticmethod
    def _analizar_debilidades(resultado: ResultadoEntrenamiento) -> list[str]:
        """Analiza las debilidades de un entrenamiento."""
        debilidades: list[str] = []
        ev = resultado.evaluacion

        if ev.descubrimiento < 10:
            debilidades.append("Descubrimiento insuficiente")
        if ev.calificacion < 10:
            debilidades.append("Calificación incompleta")
        if ev.valor < 10:
            debilidades.append("Sin presentación de valor")
        if ev.objeciones < 10:
            debilidades.append("Manejo de objeciones débil")
        if ev.cierre < 10:
            debilidades.append("No intenta cerrar la venta")

        for error in resultado.errores:
            debilidades.append(f"Error: {error.descripcion}")

        return debilidades
