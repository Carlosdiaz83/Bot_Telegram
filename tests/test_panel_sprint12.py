"""
Tests — Sprint 12: Panel Comercial Inteligente.

Verifica dashboard, gestión de leads, detalle, evolución
y filtros del panel web.
"""

from __future__ import annotations

import os
import tempfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine as _create_engine

from app.panel.app import create_panel_app
from app.database.database import get_session_factory, crear_tablas
from app.database.models import LeadDB, TrainingSessionDB


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _create_test_app():
    """Crea una app de test con DB temporal."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db_url = f"sqlite:///{tmp.name}"
    app = create_panel_app(database_url=db_url)
    return app, tmp.name, db_url


def _seed_lead(db_url, **kwargs):
    """Inserta un lead directo en la DB de test."""
    engine = _create_engine(db_url)
    crear_tablas(engine)
    Session = get_session_factory(engine)
    db = Session()
    lead = LeadDB(**kwargs)
    db.add(lead)
    db.commit()
    lead_id = lead.id
    db.close()
    engine.dispose()
    return lead_id


def _seed_training(db_url, perfil="test", score_total=75, **kwargs):
    """Inserta una sesión de entrenamiento directa."""
    engine = _create_engine(db_url)
    crear_tablas(engine)
    Session = get_session_factory(engine)
    db = Session()
    sesion = TrainingSessionDB(
        perfil_cliente=perfil,
        score_total=score_total,
        score_descubrimiento=kwargs.get("score_descubrimiento", 15),
        score_calificacion=kwargs.get("score_calificacion", 15),
        score_valor=kwargs.get("score_valor", 15),
        score_objeciones=kwargs.get("score_objeciones", 15),
        score_cierre=kwargs.get("score_cierre", 15),
    )
    db.add(sesion)
    db.commit()
    sesion_id = sesion.id
    db.close()
    engine.dispose()
    return sesion_id


def _cleanup(tmp_name):
    try:
        os.unlink(tmp_name)
    except OSError:
        pass


# ─────────────────────────────────────────────
# Tests — Dashboard
# ─────────────────────────────────────────────

class TestDashboard:
    """Tests del dashboard principal."""

    def test_dashboard_status(self):
        app, tmp_name, db_url = _create_test_app()
        client = TestClient(app)
        response = client.get("/")
        assert response.status_code == 200
        assert "Dashboard Comercial" in response.text
        _cleanup(tmp_name)

    def test_dashboard_muestra_metricas(self):
        app, tmp_name, db_url = _create_test_app()
        _seed_lead(db_url, telegram_id=1001, nombre="Lead A", estado_comercial="nuevo")
        _seed_lead(db_url, telegram_id=1002, nombre="Lead B", estado_comercial="vendido")
        client = TestClient(app)
        response = client.get("/")
        assert response.status_code == 200
        assert "Total Leads" in response.text
        assert "Cierres" in response.text
        assert "Perdidas" in response.text
        _cleanup(tmp_name)

    def test_dashboard_muestra_entrenamiento(self):
        app, tmp_name, db_url = _create_test_app()
        _seed_training(db_url, score_total=80)
        client = TestClient(app)
        response = client.get("/")
        assert response.status_code == 200
        assert "Entrenamiento" in response.text
        _cleanup(tmp_name)

    def test_dashboard_vacio(self):
        app, tmp_name, db_url = _create_test_app()
        client = TestClient(app)
        response = client.get("/")
        assert response.status_code == 200
        assert "0" in response.text
        _cleanup(tmp_name)


# ─────────────────────────────────────────────
# Tests — Gestión de Leads
# ─────────────────────────────────────────────

class TestLeadsList:
    """Tests de la lista de leads."""

    def test_leads_status(self):
        app, tmp_name, db_url = _create_test_app()
        client = TestClient(app)
        response = client.get("/leads")
        assert response.status_code == 200
        assert "Leads" in response.text
        _cleanup(tmp_name)

    def test_leads_muestra_leads(self):
        app, tmp_name, db_url = _create_test_app()
        _seed_lead(db_url, telegram_id=2001, nombre="Juan Perez")
        client = TestClient(app)
        response = client.get("/leads")
        assert response.status_code == 200
        assert "Juan Perez" in response.text
        _cleanup(tmp_name)

    def test_leads_filtro_estado(self):
        app, tmp_name, db_url = _create_test_app()
        _seed_lead(db_url, telegram_id=3001, nombre="Nuevo Lead", estado_comercial="nuevo")
        _seed_lead(db_url, telegram_id=3002, nombre="Vendido Lead", estado_comercial="vendido")
        client = TestClient(app)
        response = client.get("/leads?estado=nuevo")
        assert response.status_code == 200
        assert "Nuevo Lead" in response.text
        assert "Vendido Lead" not in response.text
        _cleanup(tmp_name)

    def test_leads_filtro_temperatura(self):
        app, tmp_name, db_url = _create_test_app()
        _seed_lead(db_url, telegram_id=4001, nombre="Frio Lead", temperatura_lead="frio")
        _seed_lead(db_url, telegram_id=4002, nombre="Caliente Lead", temperatura_lead="caliente")
        client = TestClient(app)
        response = client.get("/leads?temperatura=caliente")
        assert response.status_code == 200
        assert "Caliente Lead" in response.text
        assert "Frio Lead" not in response.text
        _cleanup(tmp_name)

    def test_leads_busqueda_nombre(self):
        app, tmp_name, db_url = _create_test_app()
        _seed_lead(db_url, telegram_id=5001, nombre="Carlos Martinez")
        _seed_lead(db_url, telegram_id=5002, nombre="Ana Garcia")
        client = TestClient(app)
        response = client.get("/leads?q=carlos")
        assert response.status_code == 200
        assert "Carlos Martinez" in response.text
        assert "Ana Garcia" not in response.text
        _cleanup(tmp_name)

    def test_leads_busqueda_localidad(self):
        app, tmp_name, db_url = _create_test_app()
        _seed_lead(db_url, telegram_id=6001, nombre="Lead BA", localidad="Buenos Aires")
        _seed_lead(db_url, telegram_id=6002, nombre="Lead MDQ", localidad="Mar del Plata")
        client = TestClient(app)
        response = client.get("/leads?q=buenos")
        assert response.status_code == 200
        assert "Buenos Aires" in response.text
        assert "Mar del Plata" not in response.text
        _cleanup(tmp_name)

    def test_leads_orden_score_desc(self):
        app, tmp_name, db_url = _create_test_app()
        _seed_lead(db_url, telegram_id=7001, nombre="Bajo", score=20)
        _seed_lead(db_url, telegram_id=7002, nombre="Alto", score=90)
        client = TestClient(app)
        response = client.get("/leads?orden=score_desc")
        assert response.status_code == 200
        alto_pos = response.text.index("Alto")
        bajo_pos = response.text.index("Bajo")
        assert alto_pos < bajo_pos
        _cleanup(tmp_name)

    def test_leads_vacio(self):
        app, tmp_name, db_url = _create_test_app()
        client = TestClient(app)
        response = client.get("/leads")
        assert response.status_code == 200
        assert "No hay leads registrados" in response.text
        _cleanup(tmp_name)

    def test_leads_contador(self):
        app, tmp_name, db_url = _create_test_app()
        _seed_lead(db_url, telegram_id=8001, nombre="L1")
        _seed_lead(db_url, telegram_id=8002, nombre="L2")
        client = TestClient(app)
        response = client.get("/leads")
        assert "2 lead(s) encontrado(s)" in response.text
        _cleanup(tmp_name)


# ─────────────────────────────────────────────
# Tests — Detalle de Lead
# ─────────────────────────────────────────────

class TestLeadDetail:
    """Tests del detalle de lead."""

    def test_detail_status(self):
        app, tmp_name, db_url = _create_test_app()
        lead_id = _seed_lead(db_url, telegram_id=9001, nombre="Detalle Lead", score=75)
        client = TestClient(app)
        response = client.get(f"/leads/{lead_id}")
        assert response.status_code == 200
        assert "Detalle Lead" in response.text
        _cleanup(tmp_name)

    def test_detail_muestra_datos(self):
        app, tmp_name, db_url = _create_test_app()
        lead_id = _seed_lead(
            db_url, telegram_id=9002, nombre="Data Lead",
            telefono="1155551234", localidad="CABA",
            estado_comercial="calificando", score=65,
        )
        client = TestClient(app)
        response = client.get(f"/leads/{lead_id}")
        assert response.status_code == 200
        assert "1155551234" in response.text
        assert "CABA" in response.text
        assert "calificando" in response.text
        assert "65" in response.text
        _cleanup(tmp_name)

    def test_detail_inexistente_redirige(self):
        app, tmp_name, db_url = _create_test_app()
        client = TestClient(app)
        response = client.get("/leads/99999", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/leads"
        _cleanup(tmp_name)

    def test_detail_botones_estado(self):
        app, tmp_name, db_url = _create_test_app()
        lead_id = _seed_lead(db_url, telegram_id=9003, nombre="Btn Lead")
        client = TestClient(app)
        response = client.get(f"/leads/{lead_id}")
        assert response.status_code == 200
        assert "Cambiar Estado" in response.text
        assert "Marcar Vendido" in response.text
        assert "Marcar Perdido" in response.text
        _cleanup(tmp_name)

    def test_cambiar_estado_valido(self):
        app, tmp_name, db_url = _create_test_app()
        lead_id = _seed_lead(db_url, telegram_id=9004, nombre="Estado Lead", estado_comercial="nuevo")
        client = TestClient(app)
        response = client.post(
            f"/leads/{lead_id}/estado",
            data={"estado": "vendido"},
            follow_redirects=False,
        )
        assert response.status_code == 303

        engine = _create_engine(db_url)
        Session = get_session_factory(engine)
        db = Session()
        lead = db.get(LeadDB, lead_id)
        assert lead.estado_comercial == "vendido"
        db.close()
        engine.dispose()
        _cleanup(tmp_name)

    def test_cambiar_estado_invalido(self):
        app, tmp_name, db_url = _create_test_app()
        lead_id = _seed_lead(db_url, telegram_id=9005, nombre="Invalid Lead", estado_comercial="nuevo")
        client = TestClient(app)
        response = client.post(
            f"/leads/{lead_id}/estado",
            data={"estado": "estado_inexistente"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        _cleanup(tmp_name)


# ─────────────────────────────────────────────
# Tests — Evolución de Sofía
# ─────────────────────────────────────────────

class TestEvolucion:
    """Tests de la página de evolución."""

    def test_evolucion_status(self):
        app, tmp_name, db_url = _create_test_app()
        client = TestClient(app)
        response = client.get("/evolucion")
        assert response.status_code == 200
        assert "Evolucion" in response.text
        _cleanup(tmp_name)

    def test_evolucion_muestra_metricas(self):
        app, tmp_name, db_url = _create_test_app()
        _seed_training(db_url, perfil="precio", score_total=80)
        _seed_training(db_url, perfil="calidad", score_total=70)
        client = TestClient(app)
        response = client.get("/evolucion")
        assert response.status_code == 200
        assert "Entrenamientos" in response.text
        assert "Score Promedio" in response.text
        assert "Mejor Score" in response.text
        _cleanup(tmp_name)

    def test_evolucion_muestra_entrenamientos(self):
        app, tmp_name, db_url = _create_test_app()
        _seed_training(db_url, perfil="cliente_frio", score_total=65)
        client = TestClient(app)
        response = client.get("/evolucion")
        assert response.status_code == 200
        assert "cliente_frio" in response.text
        assert "65" in response.text
        _cleanup(tmp_name)

    def test_evolucion_vacio(self):
        app, tmp_name, db_url = _create_test_app()
        client = TestClient(app)
        response = client.get("/evolucion")
        assert response.status_code == 200
        assert "No hay entrenamientos registrados" in response.text
        _cleanup(tmp_name)

    def test_evolucion_fortalezas_debilidades(self):
        app, tmp_name, db_url = _create_test_app()
        for _ in range(3):
            _seed_training(
                db_url, perfil="test", score_total=90,
                score_descubrimiento=18, score_calificacion=18,
                score_valor=18, score_objeciones=18, score_cierre=18,
            )
        client = TestClient(app)
        response = client.get("/evolucion")
        assert response.status_code == 200
        assert "Fortalezas" in response.text
        assert "Debilidades" in response.text
        _cleanup(tmp_name)
