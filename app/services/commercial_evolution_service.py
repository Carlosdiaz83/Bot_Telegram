"""
Servicio de evolución comercial de Sofía.

Analiza entrenamientos históricos para medir la mejora
continua, detectar debilidades y identificar fortalezas.

Uso:
    from app.services.commercial_evolution_service import CommercialEvolutionService
    evo_svc = CommercialEvolutionService(db)
    evolucion = evo_svc.obtener_evolucion()
    metricas = evo_svc.obtener_metricas()
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy.orm import Session

from app.database.repository import TrainingRepository

logger = logging.getLogger(__name__)


@dataclass
class EvolucionComercial:
    """
    Evolución del desempeño comercial de Sofía.

    Attributes:
        primer_score: Score del primer entrenamiento.
        ultimo_score: Score del último entrenamiento.
        mejora: Diferencia entre último y primer score.
        total_entrenamientos: Total de entrenamientos registrados.
        debilidades_principales: Debilidades detectadas.
        fortalezas: Fortalezas detectadas.
        errores_frecuentes: Errores más comunes.
    """
    primer_score: int = 0
    ultimo_score: int = 0
    mejora: int = 0
    total_entrenamientos: int = 0
    debilidades_principales: list[str] = field(default_factory=list)
    fortalezas: list[str] = field(default_factory=list)
    errores_frecuentes: list[tuple[str, int]] = field(default_factory=list)


@dataclass
class MetricasComerciales:
    """
    Métricas consolidadas del entrenamiento.

    Attributes:
        score_promedio: Score promedio histórico.
        mejor_score: Mejor score obtenido.
        peor_score: Peor score obtenido.
        total_entrenamientos: Total de entrenamientos.
        errores_frecuentes: Errores más frecuentes.
        evolucion_por_dimension: Score promedio por dimensión y fecha.
    """
    score_promedio: float = 0.0
    mejor_score: int = 0
    peor_score: int = 0
    total_entrenamientos: int = 0
    errores_frecuentes: list[tuple[str, int]] = field(default_factory=list)
    evolucion_por_dimension: dict[str, list[tuple[str, int]]] = field(default_factory=dict)


class CommercialEvolutionService:
    """
    Servicio de análisis de evolución comercial.

    Analiza el historial de entrenamientos para medir
    la mejora continua de Sofía.
    """

    def __init__(self, db: Session) -> None:
        self._repo = TrainingRepository(db)

    def obtener_evolucion(self, perfil: Optional[str] = None) -> EvolucionComercial:
        """
        Analiza la evolución del desempeño.

        Args:
            perfil: Filtrar por perfil específico (None = todos).

        Returns:
            EvolucionComercial con el análisis.
        """
        if perfil:
            sessions = self._repo.por_perfil(perfil)
        else:
            sessions = self._repo.historial(limit=1000)

        evolucion = EvolucionComercial(total_entrenamientos=len(sessions))

        if not sessions:
            return evolucion

        # Ordenar por fecha ascendente
        sessions_ordenadas = sorted(sessions, key=lambda s: s.creado)

        evolucion.primer_score = sessions_ordenadas[0].score_total
        evolucion.ultimo_score = sessions_ordenadas[-1].score_total
        evolucion.mejora = evolucion.ultimo_score - evolucion.primer_score

        # Analizar debilidades
        evolucion.debilidades_principales = self._analizar_debilidades(sessions)

        # Analizar fortalezas
        evolucion.fortalezas = self._analizar_fortalezas(sessions)

        # Errores frecuentes
        evolucion.errores_frecuentes = self._repo.errores_frecuentes()

        logger.info(
            "Evolución analizada: %d entrenamientos, mejora: %+d",
            evolucion.total_entrenamientos,
            evolucion.mejora,
        )

        return evolucion

    def obtener_metricas(self) -> MetricasComerciales:
        """
        Obtiene métricas consolidadas.

        Returns:
            MetricasComerciales con todas las métricas.
        """
        metricas = MetricasComerciales()
        metricas.score_promedio = self._repo.score_promedio()
        metricas.mejor_score = self._repo.mejor_score()
        metricas.peor_score = self._repo.peor_score()

        historial = self._repo.historial(limit=1000)
        metricas.total_entrenamientos = len(historial)
        metricas.errores_frecuentes = self._repo.errores_frecuentes()

        # Evolución por dimensión
        metricas.evolucion_por_dimension = self._calcular_evolucion_dimensiones(
            historial
        )

        return metricas

    def _analizar_debilidades(self, sessions: list) -> list[str]:
        """
        Analiza las debilidades principales.

        Args:
            sessions: Lista de sesiones de entrenamiento.

        Returns:
            Lista de debilidades detectadas.
        """
        debilidades: list[str] = []

        if not sessions:
            return debilidades

        # Calcular promedio por dimensión
        n = len(sessions)
        prom_desc = sum(s.score_descubrimiento for s in sessions) / n
        prom_calif = sum(s.score_calificacion for s in sessions) / n
        prom_valor = sum(s.score_valor for s in sessions) / n
        prom_obj = sum(s.score_objeciones for s in sessions) / n
        prom_cierre = sum(s.score_cierre for s in sessions) / n

        if prom_desc < 10:
            debilidades.append("Descubrimiento de necesidades débil")
        if prom_calif < 10:
            debilidades.append("Calificación incompleta")
        if prom_valor < 10:
            debilidades.append("Presentación de valor insuficiente")
        if prom_obj < 10:
            debilidades.append("Manejo de objeciones débil")
        if prom_cierre < 10:
            debilidades.append("Cierre inconsistente")

        # Analizar errores más frecuentes
        errores_freq = self._repo.errores_frecuentes()
        for tipo, cantidad in errores_freq[:3]:
            if cantidad >= 2:
                debilidades.append(f"Error frecuente: {tipo} ({cantidad} veces)")

        return debilidades

    def _analizar_fortalezas(self, sessions: list) -> list[str]:
        """
        Analiza las fortalezas principales.

        Args:
            sessions: Lista de sesiones de entrenamiento.

        Returns:
            Lista de fortalezas detectadas.
        """
        fortalezas: list[str] = []

        if not sessions:
            return fortalezas

        n = len(sessions)
        prom_desc = sum(s.score_descubrimiento for s in sessions) / n
        prom_calif = sum(s.score_calificacion for s in sessions) / n
        prom_valor = sum(s.score_valor for s in sessions) / n
        prom_obj = sum(s.score_objeciones for s in sessions) / n
        prom_cierre = sum(s.score_cierre for s in sessions) / n

        if prom_desc >= 15:
            fortalezas.append("Buen descubrimiento de necesidades")
        if prom_calif >= 15:
            fortalezas.append("Calificación completa")
        if prom_valor >= 15:
            fortalezas.append("Buena presentación de valor")
        if prom_obj >= 15:
            fortalezas.append("Manejo de objeciones efectivo")
        if prom_cierre >= 15:
            fortalezas.append("Cierre efectivo")

        # Verificar mejora
        if len(sessions) >= 2:
            sessions_ordenadas = sorted(sessions, key=lambda s: s.creado)
            primer = sessions_ordenadas[0].score_total
            ultimo = sessions_ordenadas[-1].score_total
            if ultimo > primer:
                fortalezas.append(
                    f"Mejora consistente (+{ultimo - primer} puntos)"
                )

        return fortalezas

    def _calcular_evolucion_dimensiones(
        self, sessions: list
    ) -> dict[str, list[tuple[str, int]]]:
        """
        Calcula la evolución por dimensión.

        Args:
            sessions: Lista de sesiones ordenadas por fecha.

        Returns:
            Diccionario con evolución de cada dimensión.
        """
        if not sessions:
            return {}

        # Ordenar por fecha
        sessions_ordenadas = sorted(sessions, key=lambda s: s.creado)

        # Agrupar por fecha (solo fecha, sin hora)
        por_fecha: dict[str, list] = {}
        for s in sessions_ordenadas:
            fecha_str = s.creado.strftime("%Y-%m-%d")
            if fecha_str not in por_fecha:
                por_fecha[fecha_str] = []
            por_fecha[fecha_str].append(s)

        evolucion: dict[str, list[tuple[str, int]]] = {
            "descubrimiento": [],
            "calificacion": [],
            "valor": [],
            "objeciones": [],
            "cierre": [],
        }

        for fecha, sess_grupo in sorted(por_fecha.items()):
            n = len(sess_grupo)
            evolucion["descubrimiento"].append((
                fecha,
                sum(s.score_descubrimiento for s in sess_grupo) // n,
            ))
            evolucion["calificacion"].append((
                fecha,
                sum(s.score_calificacion for s in sess_grupo) // n,
            ))
            evolucion["valor"].append((
                fecha,
                sum(s.score_valor for s in sess_grupo) // n,
            ))
            evolucion["objeciones"].append((
                fecha,
                sum(s.score_objeciones for s in sess_grupo) // n,
            ))
            evolucion["cierre"].append((
                fecha,
                sum(s.score_cierre for s in sess_grupo) // n,
            ))

        return evolucion
