"""
Tests Sprint 22 — Bootstrap idempotente de prestaciones.

Verifica que bootstrap ingesta los markdowns de cartillas oficiales
(prestadores/, planes/beneficios.md) por categoría y que repetir la
ingesta no duplica registros (idempotencia por fuente).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.bootstrap import (
    APP_KNOWLEDGE_DIR,
    _categoria_prestacion,
    _ingestar_markdowns_prestaciones,
)
from app.database.models import Base
from app.database.repository import KnowledgeRepository


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture()
def repo(db_session):
    return KnowledgeRepository(db_session)


class TestCategoriaPrestacion:
    def test_red_medica_es_prestadores(self):
        assert _categoria_prestacion(APP_KNOWLEDGE_DIR / "prestadores/red_medica.md") == "prestadores"

    def test_red_farmacias_es_farmacias(self):
        assert _categoria_prestacion(APP_KNOWLEDGE_DIR / "prestadores/red_farmacias.md") == "farmacias"

    def test_red_odontologica_es_odontologia(self):
        assert _categoria_prestacion(APP_KNOWLEDGE_DIR / "prestadores/red_odontologica.md") == "odontologia"

    def test_archivo_no_prestacion(self):
        assert _categoria_prestacion(APP_KNOWLEDGE_DIR / "planes/beneficios.md") == ""


class TestIngestaPrestaciones:
    def test_ingesta_categorias_esperadas(self, db_session, repo):
        assert APP_KNOWLEDGE_DIR.is_dir(), "app/knowledge/servired no existe"

        creados = _ingestar_markdowns_prestaciones(db_session)
        assert creados >= 4  # red_medica, red_farmacias, red_odontologica, beneficios

        categorias = {i.categoria for i in repo.activos()}
        assert "prestadores" in categorias
        assert "farmacias" in categorias
        assert "odontologia" in categorias
        assert "planes" in categorias

    def test_ingesta_idempotente(self, db_session, repo):
        primero = _ingestar_markdowns_prestaciones(db_session)
        segundo = _ingestar_markdowns_prestaciones(db_session)
        assert primero >= 4
        assert segundo == 0
        assert len(repo.activos()) == primero

    def test_contenido_real_cartillas(self, db_session, repo):
        _ingestar_markdowns_prestaciones(db_session)

        farmacias = repo.buscar_por_categoria("farmacias")
        assert farmacias and "farmacias" in farmacias[0].contenido.lower()

        prestadores = repo.buscar_por_categoria("prestadores")
        assert prestadores and "prestador" in prestadores[0].contenido.lower()

        odontologia = repo.buscar_por_categoria("odontologia")
        assert odontologia and "odontol" in odontologia[0].contenido.lower()

        planes = repo.buscar_por_categoria("planes")
        assert planes and "beneficios" in planes[0].contenido.lower()

    def test_no_duplica_cuando_ya_existe_la_fuente(self, db_session, repo):
        _ingestar_markdowns_prestaciones(db_session)
        total = len(repo.activos())

        # Simular un deploy repetido: nueva sesión sobre la misma DB
        _ingestar_markdowns_prestaciones(db_session)
        assert len(repo.activos()) == total
