"""
Tests Sprint 23 — Cartillas en PDF como adjuntos.

Cubre:
    - RespuestaBot: subclase de str con archivos_adjuntos
    - CartillaService: plan/categoría → PDF de cartilla oficial
    - Flujo integrado: procesar_mensaje retorna RespuestaBot con adjuntos
      (cotización → PDFs de planes; plan específico → PDF del plan;
       odontología/farmacias → PDF de cobertura)
    - session.adjuntos_pendientes queda limpio tras la respuesta
    - Saludo puro en etapas avanzadas no cambia la etapa
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.respuesta_bot import RespuestaBot
from app.services.cartilla_service import CartillaService
from app.services.session_manager import EtapaConversacion
from app.services.conversation_manager import ConversationManager

# ─────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────

@pytest.fixture
def manager():
    """ConversationManager sin DB ni IA."""
    return ConversationManager(ai_service=None, database_url=None)


@pytest.fixture
def cartilla():
    return CartillaService()


# ─────────────────────────────────────────
# RespuestaBot: compatibilidad str + adjuntos
# ─────────────────────────────────────────

class TestRespuestaBot:
    def test_es_subclase_de_str(self):
        r = RespuestaBot("Hola")
        assert isinstance(r, str)
        assert str(r) == "Hola"

    def test_adjuntos_vacios_por_defecto(self):
        r = RespuestaBot("Hola")
        assert r.archivos_adjuntos == []
        assert not r.tiene_adjuntos

    def test_adjuntos_con_archivo(self):
        r = RespuestaBot("Hola", archivos_adjuntos=["a.pdf"])
        assert r.archivos_adjuntos == ["a.pdf"]
        assert r.tiene_adjuntos

    def test_con_adjunto_encadena(self):
        r = RespuestaBot("Hola").con_adjunto("a.pdf")
        assert r.archivos_adjuntos == ["a.pdf"]

    def test_funciona_en_contextos_de_string(self):
        r = RespuestaBot("¿Cómo te llamás?")
        assert "¿Cómo te llamás?" in r
        assert r.lower().startswith("¿cómo")


# ─────────────────────────────────────────
# CartillaService: plan/categoría → PDF
# ─────────────────────────────────────────

class TestCartillaService:
    def test_plan_gold(self, cartilla):
        pdf = cartilla.plan_a_pdf("gold")
        assert pdf and Path(pdf).is_file()
        assert "GOLD" in Path(pdf).name

    def test_plan_medimax_gold(self, cartilla):
        pdf = cartilla.plan_a_pdf("medimax_gold")
        assert pdf and Path(pdf).is_file()
        assert "MEDIMAX GOLD" in Path(pdf).name

    def test_plan_medimax(self, cartilla):
        pdf = cartilla.plan_a_pdf("medimax")
        assert pdf and Path(pdf).is_file()
        assert "MEDIMAX" in Path(pdf).name

    def test_plan_medimax_co(self, cartilla):
        pdf = cartilla.plan_a_pdf("medimax_co")
        assert pdf and Path(pdf).is_file()
        assert "MEDIMAX CO" in Path(pdf).name

    def test_plan_desconocido_devuelve_none(self, cartilla):
        assert cartilla.plan_a_pdf("plan_inexistente") is None

    def test_odontologia(self, cartilla):
        pdfs = cartilla.categoria_pdfs("odontologia")
        assert pdfs and all(Path(p).is_file() for p in pdfs)

    def test_farmacias(self, cartilla):
        pdfs = cartilla.categoria_pdfs("farmacias")
        assert pdfs and all(Path(p).is_file() for p in pdfs)

    def test_planes_detecta_plan_gold_en_mensaje(self, cartilla):
        pdfs = cartilla.categoria_pdfs("planes", "que cubre el plan gold?")
        assert len(pdfs) == 1
        assert "GOLD" in Path(pdfs[0]).name

    def test_planes_detecta_medimax_gold(self, cartilla):
        pdfs = cartilla.categoria_pdfs("planes", "que onda el medimax gold?")
        assert len(pdfs) == 1
        assert "MEDIMAX GOLD" in Path(pdfs[0]).name

    def test_planes_generico_incluye_todos(self, cartilla):
        pdfs = cartilla.categoria_pdfs("planes")
        assert len(pdfs) == 4


# ─────────────────────────────────────────
# Flujo integrado: procesar_mensaje con adjuntos
# ─────────────────────────────────────────

def _completar_flujo(manager, tid):
    manager.procesar_mensaje(tid, "Hola")
    manager.procesar_mensaje(tid, "Soy Test")
    manager.procesar_mensaje(tid, "Quiero info")
    manager.procesar_mensaje(tid, "Particular, solo para mí")
    return manager.procesar_mensaje(tid, "Córdoba, 30 años")


class TestFlujoAdjuntos:
    def test_cotizacion_adjunta_planes(self, manager):
        respuesta = _completar_flujo(manager, 7001)
        assert isinstance(respuesta, RespuestaBot)
        nombres = [Path(p).name for p in respuesta.archivos_adjuntos]
        assert any("MEDIMAX" in n for n in nombres)

    def test_adjuntos_limpian_pendiente(self, manager):
        tid = 7002
        _completar_flujo(manager, tid)
        session = manager.session_manager.get(tid)
        assert session.adjuntos_pendientes == []

    def test_plan_especifico_adjunta_su_pdf(self, manager):
        tid = 7003
        _completar_flujo(manager, tid)
        respuesta = manager.procesar_mensaje(tid, "contame mas del plan gold")
        assert isinstance(respuesta, RespuestaBot)
        nombres = [Path(p).name for p in respuesta.archivos_adjuntos]
        assert any("GOLD" in n for n in nombres)
        assert "Gold" in respuesta or "gold" in respuesta

    def test_medimax_gold_especifico(self, manager):
        tid = 7004
        _completar_flujo(manager, tid)
        respuesta = manager.procesar_mensaje(tid, "que onda el medimax gold?")
        nombres = [Path(p).name for p in respuesta.archivos_adjuntos]
        assert any("MEDIMAX GOLD" in n for n in nombres)

    def test_odontologia_adjunta_pdf(self, manager):
        tid = 7005
        _completar_flujo(manager, tid)
        respuesta = manager.procesar_mensaje(tid, "cubren odontologia?")
        nombres = [Path(p).name for p in respuesta.archivos_adjuntos]
        assert any("ODONTO" in n for n in nombres)

    def test_farmacias_adjunta_pdf(self, manager):
        tid = 7006
        _completar_flujo(manager, tid)
        respuesta = manager.procesar_mensaje(tid, "hay farmacias adheridas?")
        nombres = [Path(p).name for p in respuesta.archivos_adjuntos]
        assert any("FARMACIA" in n for n in nombres)


# ─────────────────────────────────────────
# Saludo puro en etapas avanzadas
# ─────────────────────────────────────────

class TestSaludoReturning:
    def test_saludo_no_cambia_etapa(self, manager):
        tid = 7007
        _completar_flujo(manager, tid)
        before = manager.session_manager.get(tid).etapa
        respuesta = manager.procesar_mensaje(tid, "hola")
        session = manager.session_manager.get(tid)
        assert session.etapa == before
        assert session._handler_ejecutado == "_handle_saludo"
        assert "Juan" not in respuesta  # no inventa nombre

    def test_saludo_con_nombre_usa_nombre(self, manager):
        tid = 7008
        _completar_flujo(manager, tid)
        respuesta = manager.procesar_mensaje(tid, "Hola!")
        assert "Test" in respuesta

    def test_saludo_no_rompe_en_nuevo(self, manager):
        tid = 7009
        respuesta = manager.procesar_mensaje(tid, "hola")
        assert "¿Cómo te llamás?" in respuesta
