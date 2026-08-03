"""
Tests Sprint 25 — Orden de planes en la cotización y plan económico.

Cubre:
    - La cotización (cliente y vendedor) lista 3 planes en orden:
      Gold → Medimax Gold → Medimax
    - Medimax Co NO se cotiza en el listado principal
    - Medimax Co se ofrece ante una objeción de precio
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.models.lead import Lead
from app.services.conversation_manager import ConversationManager
from app.services.session_manager import EtapaConversacion


# ─────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────

class _CalcFake:
    """Calculadora fake con precios para los 4 planes."""

    _PRECIOS = {
        "gold": 120000.0,
        "medimax gold": 98000.0,
        "medimax": 78000.0,
        "medimax co": 58000.0,
    }

    def cotizar(self, *, lead, zona, nombre_plan, conceptos_obra_social=None):
        valor = self._PRECIOS.get(nombre_plan, 0.0)
        return SimpleNamespace(
            plan=nombre_plan,
            valor_plan_total=valor,
            valor_a_pagar=valor,
            plan_joven_disponible=False,
        )


@pytest.fixture
def manager_con_calculadora():
    manager = ConversationManager(ai_service=None, database_url=None)
    manager._calculator = _CalcFake()
    return manager


@pytest.fixture
def manager_sin_calculadora():
    return ConversationManager(ai_service=None, database_url=None)


def _lead_completo(manager, tid=98001):
    session = manager.session_manager.get_or_create(tid)
    session.lead = Lead(
        lead_id=str(tid),
        nombre="Pedro",
        edad=30,
        localidad="Córdoba",
        tipo_afiliacion="particular",
    )
    return session


def _indices_planes(texto: str) -> dict[str, int]:
    lower = texto.lower()
    # Los encabezados pueden ser "*Gold*" (sin calculadora) o "*Plan Gold*" (con).
    patrones = {
        "gold": r"\*(?:plan )?gold\*",
        "medimax_gold": r"\*(?:plan )?medimax gold\*",
        "medimax": r"\*(?:plan )?medimax\*",
        "medimax_co": r"\*(?:plan )?medimax co\*",
    }
    return {
        nombre: (m.start() if (m := re.search(patron, lower)) else -1)
        for nombre, patron in patrones.items()
    }


# ─────────────────────────────────────────
# Orden en la cotización
# ─────────────────────────────────────────

class TestOrdenPlanesCotizacion:
    def test_cotizacion_cliente_orden_gold_medimax_gold_medimax(self, manager_con_calculadora):
        manager = manager_con_calculadora
        session = _lead_completo(manager)

        respuesta = manager._handle_cotizando(session, "")

        idx = _indices_planes(respuesta)
        assert idx["gold"] != -1
        assert idx["medimax_gold"] != -1
        assert idx["medimax"] != -1
        assert idx["gold"] < idx["medimax_gold"] < idx["medimax"]
        # Medimax Co no se lista en la cotización principal
        assert idx["medimax_co"] == -1
        assert any("GOLD" in Path(p).name for p in session.adjuntos_pendientes)

    def test_cotizacion_vendedor_orden_gold_medimax_gold_medimax(self, manager_con_calculadora):
        manager = manager_con_calculadora
        session = _lead_completo(manager, tid=98002)
        session.es_vendedor = True

        respuesta = manager._handle_vendedor_cotizando(session, "")

        idx = _indices_planes(respuesta)
        assert idx["gold"] != -1
        assert idx["medimax_gold"] != -1
        assert idx["medimax"] != -1
        assert idx["gold"] < idx["medimax_gold"] < idx["medimax"]
        assert idx["medimax_co"] == -1
        assert any("GOLD" in Path(p).name for p in session.adjuntos_pendientes)

    def test_cotizacion_cliente_sin_calculadora_no_lista_medimax_co(self, manager_sin_calculadora):
        manager = manager_sin_calculadora
        session = _lead_completo(manager, tid=98003)

        respuesta = manager._handle_cotizando(session, "")

        idx = _indices_planes(respuesta)
        assert idx["gold"] != -1
        assert idx["medimax_gold"] != -1
        assert idx["medimax"] != -1
        assert idx["gold"] < idx["medimax_gold"] < idx["medimax"]
        assert idx["medimax_co"] == -1
        assert session.etapa == EtapaConversacion.PRESENTANDO_VALOR


# ─────────────────────────────────────────
# Medimax Co ante objeción de precio
# ─────────────────────────────────────────

class TestMedimaxCoPorPrecio:
    def test_objeccion_precio_ofrece_medimax_co_con_adjunto(self, manager_con_calculadora):
        manager = manager_con_calculadora
        session = _lead_completo(manager, tid=98011)

        respuesta = manager._handle_objeciones(session, "es muy caro")

        assert "Medimax Co" in respuesta
        assert "58,000" in respuesta
        assert any("MEDIMAX CO" in Path(p).name for p in session.adjuntos_pendientes)

    def test_objeccion_precio_sin_calculadora_usa_respuesta_generica(self, manager_sin_calculadora):
        manager = manager_sin_calculadora
        session = _lead_completo(manager, tid=98012)

        respuesta = manager._handle_objeciones(session, "es muy caro")

        assert "Medimax Co" not in respuesta
        assert session.adjuntos_pendientes == []

    def test_objeccion_precio_sin_datos_cotizables_no_ofrece_plan(self, manager_con_calculadora):
        manager = manager_con_calculadora
        session = manager.session_manager.get_or_create(98013)
        session.lead = Lead(lead_id="98013", nombre="Pedro")

        respuesta = manager._handle_objeciones(session, "es muy caro")

        assert "Medimax Co" not in respuesta
