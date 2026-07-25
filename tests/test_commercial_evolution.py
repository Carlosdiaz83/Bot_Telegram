"""
Tests — Sprint 11: Memoria y evolución comercial.

Verifica el modelo TrainingSession, TrainingRepository,
CommercialEvolutionService y la integración con TrainingEngine.
"""

from __future__ import annotations

import json
import pytest
from datetime import datetime, timedelta

from app.database.database import get_engine, crear_tablas, cerrar_engine, get_session_factory
from app.database.models import Base, TrainingSessionDB
from app.database.repository import TrainingRepository
from app.services.commercial_evolution_service import (
    CommercialEvolutionService,
    EvolucionComercial,
    MetricasComerciales,
)


# ─────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────

@pytest.fixture
def db_session():
    """Crea una sesión de test con DB en memoria."""
    engine = get_engine("sqlite:///:memory:")
    crear_tablas(engine)
    factory = get_session_factory(engine)
    session = factory()
    yield session
    session.close()
    cerrar_engine()


@pytest.fixture
def repo(db_session) -> TrainingRepository:
    """Instancia del TrainingRepository con DB en memoria."""
    return TrainingRepository(db_session)


@pytest.fixture
def evolution_service(db_session) -> CommercialEvolutionService:
    """Instancia del CommercialEvolutionService."""
    return CommercialEvolutionService(db_session)


def _guardar_sesion(repo, perfil="test_perfil", score_total=75, **kwargs):
    """Helper para guardar una sesión con la API de dict."""
    data = {
        "perfil": perfil,
        "score_total": score_total,
        "score_descubrimiento": kwargs.get("score_descubrimiento", 15),
        "score_calificacion": kwargs.get("score_calificacion", 15),
        "score_valor": kwargs.get("score_valor", 15),
        "score_objeciones": kwargs.get("score_objeciones", 15),
        "score_cierre": kwargs.get("score_cierre", 15),
        "cantidad_errores": kwargs.get("cantidad_errores", 0),
        "errores": kwargs.get("errores", []),
        "recomendaciones": kwargs.get("recomendaciones", []),
    }
    return repo.guardar(data)


# ─────────────────────────────────────────────
# Tests — TrainingSessionDB model
# ─────────────────────────────────────────────

class TestTrainingSessionModel:
    """Tests del modelo TrainingSessionDB."""

    def test_crear_sesion_minima(self, repo):
        sesion = _guardar_sesion(repo, perfil="test_perfil", score_total=75)
        assert sesion.id is not None
        assert sesion.perfil_cliente == "test_perfil"
        assert sesion.score_total == 75
        assert sesion.errores_detectados == "[]"
        assert sesion.recomendaciones == "[]"

    def test_crear_sesion_con_errores(self, repo):
        sesion = _guardar_sesion(
            repo,
            perfil="cliente_busca_precio",
            score_total=60,
            errores=["cotizacion_sin_diagnostico", "hablar_demasiado"],
            recomendaciones=["Mejorar descubrimiento"],
        )
        assert "cotizacion_sin_diagnostico" in sesion.errores_detectados
        assert "hablar_demasiado" in sesion.errores_detectados
        assert "Mejorar descubrimiento" in sesion.recomendaciones

    def test_crear_sesion_score_total(self, repo):
        sesion = _guardar_sesion(repo, perfil="test", score_total=80)
        assert sesion.score_total == 80

    def test_crear_sesion_scores_individuales(self, repo):
        sesion = _guardar_sesion(
            repo,
            score_total=85,
            score_descubrimiento=17,
            score_calificacion=17,
            score_valor=17,
            score_objeciones=17,
            score_cierre=17,
        )
        assert sesion.score_descubrimiento == 17
        assert sesion.score_calificacion == 17
        assert sesion.score_valor == 17
        assert sesion.score_objeciones == 17
        assert sesion.score_cierre == 17

    def test_crear_sesion_repr(self, repo):
        sesion = _guardar_sesion(repo, perfil="p", score_total=70)
        r = repr(sesion)
        assert "TrainingSessionDB" in r
        assert "p" in r


# ─────────────────────────────────────────────
# Tests — TrainingRepository
# ─────────────────────────────────────────────

class TestTrainingRepository:
    """Tests del TrainingRepository."""

    def test_historial_vacio(self, repo):
        historial = repo.historial()
        assert historial == []

    def test_historial_con_sesiones(self, repo):
        _guardar_sesion(repo, perfil="p1", score_total=80,
                        score_descubrimiento=16, score_calificacion=16,
                        score_valor=16, score_objeciones=16, score_cierre=16)
        _guardar_sesion(repo, perfil="p2", score_total=70,
                        score_descubrimiento=14, score_calificacion=14,
                        score_valor=14, score_objeciones=14, score_cierre=14)
        historial = repo.historial()
        assert len(historial) == 2

    def test_historial_con_limit(self, repo):
        for i in range(5):
            _guardar_sesion(repo, perfil=f"p{i}", score_total=60 + i,
                            score_descubrimiento=12, score_calificacion=12,
                            score_valor=12, score_objeciones=12, score_cierre=12)
        historial = repo.historial(limit=3)
        assert len(historial) == 3

    def test_por_perfil(self, repo):
        _guardar_sesion(repo, perfil="precio", score_total=70,
                        score_descubrimiento=14, score_calificacion=14,
                        score_valor=14, score_objeciones=14, score_cierre=14)
        _guardar_sesion(repo, perfil="calidad", score_total=80,
                        score_descubrimiento=16, score_calificacion=16,
                        score_valor=16, score_objeciones=16, score_cierre=16)
        _guardar_sesion(repo, perfil="precio", score_total=75,
                        score_descubrimiento=15, score_calificacion=15,
                        score_valor=15, score_objeciones=15, score_cierre=15)
        precio = repo.por_perfil("precio")
        assert len(precio) == 2
        assert all(s.perfil_cliente == "precio" for s in precio)

    def test_score_promedio(self, repo):
        _guardar_sesion(repo, perfil="p", score_total=80,
                        score_descubrimiento=16, score_calificacion=16,
                        score_valor=16, score_objeciones=16, score_cierre=16)
        _guardar_sesion(repo, perfil="p", score_total=60,
                        score_descubrimiento=12, score_calificacion=12,
                        score_valor=12, score_objeciones=12, score_cierre=12)
        promedio = repo.score_promedio()
        assert promedio == 70.0

    def test_score_promedio_vacio(self, repo):
        promedio = repo.score_promedio()
        assert promedio == 0.0

    def test_mejor_score(self, repo):
        _guardar_sesion(repo, perfil="p", score_total=60,
                        score_descubrimiento=12, score_calificacion=12,
                        score_valor=12, score_objeciones=12, score_cierre=12)
        _guardar_sesion(repo, perfil="p", score_total=90,
                        score_descubrimiento=18, score_calificacion=18,
                        score_valor=18, score_objeciones=18, score_cierre=18)
        mejor = repo.mejor_score()
        assert mejor == 90

    def test_mejor_score_vacio(self, repo):
        mejor = repo.mejor_score()
        assert mejor == 0

    def test_peor_score(self, repo):
        _guardar_sesion(repo, perfil="p", score_total=60,
                        score_descubrimiento=12, score_calificacion=12,
                        score_valor=12, score_objeciones=12, score_cierre=12)
        _guardar_sesion(repo, perfil="p", score_total=90,
                        score_descubrimiento=18, score_calificacion=18,
                        score_valor=18, score_objeciones=18, score_cierre=18)
        peor = repo.peor_score()
        assert peor == 60

    def test_errores_frecuentes(self, repo):
        _guardar_sesion(repo, perfil="p", score_total=70, errores=["cotizacion_sin_diagnostico", "hablar_demasiado"])
        _guardar_sesion(repo, perfil="p", score_total=65, errores=["cotizacion_sin_diagnostico"])
        frecuentes = repo.errores_frecuentes()
        assert len(frecuentes) > 0
        assert frecuentes[0][0] == "cotizacion_sin_diagnostico"
        assert frecuentes[0][1] == 2

    def test_ultimos(self, repo):
        for i in range(5):
            _guardar_sesion(repo, perfil=f"p{i}", score_total=60 + i,
                            score_descubrimiento=12, score_calificacion=12,
                            score_valor=12, score_objeciones=12, score_cierre=12)
        ultimos = repo.ultimos(3)
        assert len(ultimos) == 3


# ─────────────────────────────────────────────
# Tests — CommercialEvolutionService
# ─────────────────────────────────────────────

class TestCommercialEvolutionService:
    """Tests del CommercialEvolutionService."""

    def test_evolucion_sin_datos(self, evolution_service):
        evolucion = evolution_service.obtener_evolucion()
        assert evolucion.total_entrenamientos == 0
        assert evolucion.mejora == 0

    def test_evolucion_con_datos(self, evolution_service):
        _guardar_sesion(evolution_service._repo, perfil="p", score_total=60,
                        score_descubrimiento=12, score_calificacion=12,
                        score_valor=12, score_objeciones=12, score_cierre=12)
        _guardar_sesion(evolution_service._repo, perfil="p", score_total=85,
                        score_descubrimiento=17, score_calificacion=17,
                        score_valor=17, score_objeciones=17, score_cierre=17)
        evolucion = evolution_service.obtener_evolucion()
        assert evolucion.total_entrenamientos == 2
        assert evolucion.primer_score == 60
        assert evolucion.ultimo_score == 85
        assert evolucion.mejora == 25

    def test_evolucion_filtrar_por_perfil(self, evolution_service):
        _guardar_sesion(evolution_service._repo, perfil="precio", score_total=70,
                        score_descubrimiento=14, score_calificacion=14,
                        score_valor=14, score_objeciones=14, score_cierre=14)
        _guardar_sesion(evolution_service._repo, perfil="calidad", score_total=80,
                        score_descubrimiento=16, score_calificacion=16,
                        score_valor=16, score_objeciones=16, score_cierre=16)
        evolucion = evolution_service.obtener_evolucion(perfil="precio")
        assert evolucion.total_entrenamientos == 1

    def test_evolucion_debilidades(self, evolution_service):
        for _ in range(3):
            _guardar_sesion(evolution_service._repo, perfil="p", score_total=50,
                            score_descubrimiento=8, score_calificacion=12,
                            score_valor=12, score_objeciones=12, score_cierre=8)
        evolucion = evolution_service.obtener_evolucion()
        assert any("Descubrimiento" in d for d in evolucion.debilidades_principales)

    def test_evolucion_fortalezas(self, evolution_service):
        for _ in range(3):
            _guardar_sesion(evolution_service._repo, perfil="p", score_total=90,
                            score_descubrimiento=18, score_calificacion=18,
                            score_valor=18, score_objeciones=18, score_cierre=18)
        evolucion = evolution_service.obtener_evolucion()
        assert any("Buen descubrimiento" in f for f in evolucion.fortalezas)

    def test_evolucion_fortalezas_mejora(self, evolution_service):
        _guardar_sesion(evolution_service._repo, perfil="p", score_total=60,
                        score_descubrimiento=12, score_calificacion=12,
                        score_valor=12, score_objeciones=12, score_cierre=12)
        _guardar_sesion(evolution_service._repo, perfil="p", score_total=90,
                        score_descubrimiento=18, score_calificacion=18,
                        score_valor=18, score_objeciones=18, score_cierre=18)
        evolucion = evolution_service.obtener_evolucion()
        assert any("Mejora consistente" in f for f in evolucion.fortalezas)

    def test_metricas_basicas(self, evolution_service):
        _guardar_sesion(evolution_service._repo, perfil="p", score_total=70,
                        score_descubrimiento=14, score_calificacion=14,
                        score_valor=14, score_objeciones=14, score_cierre=14)
        _guardar_sesion(evolution_service._repo, perfil="p", score_total=90,
                        score_descubrimiento=18, score_calificacion=18,
                        score_valor=18, score_objeciones=18, score_cierre=18)
        metricas = evolution_service.obtener_metricas()
        assert metricas.total_entrenamientos == 2
        assert metricas.score_promedio == 80.0
        assert metricas.mejor_score == 90
        assert metricas.peor_score == 70

    def test_metricas_por_dimension(self, evolution_service):
        _guardar_sesion(evolution_service._repo, perfil="p", score_total=70,
                        score_descubrimiento=14, score_calificacion=14,
                        score_valor=14, score_objeciones=14, score_cierre=14)
        _guardar_sesion(evolution_service._repo, perfil="p", score_total=80,
                        score_descubrimiento=16, score_calificacion=16,
                        score_valor=16, score_objeciones=16, score_cierre=16)
        metricas = evolution_service.obtener_metricas()
        assert "descubrimiento" in metricas.evolucion_por_dimension
        assert len(metricas.evolucion_por_dimension["descubrimiento"]) > 0

    def test_metricas_vacias(self, evolution_service):
        metricas = evolution_service.obtener_metricas()
        assert metricas.total_entrenamientos == 0
        assert metricas.score_promedio == 0.0
        assert metricas.mejor_score == 0
        assert metricas.peor_score == 0
        assert metricas.evolucion_por_dimension == {}
