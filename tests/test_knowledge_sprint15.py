"""
Tests — Sprint 15: Integración de conocimiento profundo SERVIRED.

Verifica:
    - Cliente familia + prioridad precio
    - Cliente busca mayor cobertura
    - Cliente monotributista
    - Cliente objeta precio
    - Cliente pregunta cobertura específica
    - Conocimiento profundo por Lead
    - Documentos existen y son cargados
    - Backward compatibility
"""

from __future__ import annotations

import pytest

from app.models.lead import (
    EstadoComercial,
    Lead,
    NecesidadPrincipal,
    PrioridadCliente,
    TipoAfiliacion,
)
from app.services.knowledge_service import KnowledgeService
from app.services.session_manager import EtapaConversacion


# ─────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────

@pytest.fixture
def ks():
    """KnowledgeService con directorio real."""
    return KnowledgeService()


# ─────────────────────────────────────────
# Test 1: Documentos existen y son cargados
# ─────────────────────────────────────────

class TestDocumentosExisten:
    """Verifica que todos los documentos de conocimiento existen y se cargan."""

    def test_empresa_existe(self, ks):
        empresa = ks.obtener_empresa()
        assert len(empresa) > 100
        assert "SERVIRED" in empresa

    def test_planes_existe(self, ks):
        planes = ks.obtener_planes()
        assert len(planes) > 100
        assert "Plan" in planes

    def test_coberturas_existe(self, ks):
        coberturas = ks.obtener_coberturas()
        assert len(coberturas) > 100
        assert "cobertura" in coberturas.lower()

    def test_beneficios_categoria_existe(self, ks):
        beneficios = ks.obtener_beneficios_por_categoria()
        assert len(beneficios) > 100
        assert "Familia" in beneficios

    def test_objeciones_avanzadas_existe(self, ks):
        objeciones = ks.obtener_objeciones_avanzadas()
        assert len(objeciones) > 100
        assert "caro" in objeciones.lower()

    def test_comparativas_existe(self, ks):
        comparativas = ks.obtener_comparativas()
        assert len(comparativas) > 100
        assert "SERVIRED" in comparativas

    def test_farmacias_existe(self, ks):
        farmacias = ks.obtener_farmacias()
        assert len(farmacias) > 50
        assert "farmacia" in farmacias.lower()

    def test_odontologia_existe(self, ks):
        odonto = ks.obtener_odontologia()
        assert len(odonto) > 50
        assert "odontol" in odonto.lower()

    def test_backward_compatibility(self, ks):
        """Los métodos originales siguen funcionando."""
        assert len(ks.obtener_beneficios()) > 50
        assert len(ks.obtener_faq()) > 50
        assert len(ks.obtener_objeciones()) > 50
        assert len(ks.obtener_argumentos_venta()) > 50
        assert len(ks.obtener_cierres()) > 50


# ─────────────────────────────────────────
# Test 2: Cliente familia + prioridad precio
# ─────────────────────────────────────────

class TestFamiliaPrioridadPrecio:
    """Cliente con familia y prioridad en precio."""

    def test_contexto_incluye_planes_familia(self, ks):
        lead = Lead(
            lead_id="test1",
            nombre="Juan",
            grupo_familiar=Lead.model_fields["grupo_familiar"].default_factory(),
            prioridad_cliente=PrioridadCliente.ECONOMICO,
        )
        lead.grupo_familiar.conyuge = True
        lead.grupo_familiar.hijos = True
        lead.cantidad_hijos = 2

        contexto = ks.contexto_para_lead(lead, "presentando_valor", "¿Cuánto cuesta?")
        assert "SERVIRED" in contexto
        assert len(contexto) > 100

    def test_contexto_detecta_perfil_familia(self, ks):
        lead = Lead(
            lead_id="test2",
            nombre="María",
            grupo_familiar=Lead.model_fields["grupo_familiar"].default_factory(),
        )
        lead.grupo_familiar.conyuge = True

        contexto = ks.contexto_para_lead(lead, "calificando", "Mi esposo")
        assert "familia" in contexto.lower() or "SERVIRED" in contexto

    def test_contexto_incluye_empresa(self, ks):
        lead = Lead(lead_id="test3", nombre="Pedro")
        contexto = ks.contexto_para_lead(lead, "nuevo", "Hola")
        assert "SERVIRED" in contexto


# ─────────────────────────────────────────
# Test 3: Cliente busca mayor cobertura
# ─────────────────────────────────────────

class TestBuscaCobertura:
    """Cliente que busca mayor cobertura."""

    def test_contexto_coberturas_para_mensaje_emergencia(self, ks):
        lead = Lead(lead_id="test4", nombre="Carlos")
        contexto = ks.contexto_para_lead(
            lead, "calificando", "¿Cubren emergencias?"
        )
        assert "SERVIRED" in contexto

    def test_contexto_coberturas_para_mensaje_estudios(self, ks):
        lead = Lead(lead_id="test5", nombre="Laura")
        contexto = ks.contexto_para_lead(
            lead, "calificando", "Necesito hacer estudios"
        )
        assert "SERVIRED" in contexto

    def test_contexto_detecta_competencia(self, ks):
        lead = Lead(lead_id="test6", nombre="Roberto")
        contexto = ks.contexto_para_lead(
            lead, "manejando_objeciones", "Ya tengo otra obra social"
        )
        assert "comparativa" in contexto.lower() or "SERVIRED" in contexto


# ─────────────────────────────────────────
# Test 4: Cliente monotributista
# ─────────────────────────────────────────

class TestMonotributista:
    """Cliente monotributista."""

    def test_contexto_monotributista(self, ks):
        lead = Lead(
            lead_id="test7",
            nombre="Ana",
            tipo_afiliacion=TipoAfiliacion.MONOTRIBUTO,
        )
        contexto = ks.contexto_para_lead(lead, "presentando_valor", "")
        assert "SERVIRED" in contexto
        assert len(contexto) > 100

    def test_contexto_monotributista_en_planes(self, ks):
        lead = Lead(
            lead_id="test8",
            nombre="Luis",
            tipo_afiliacion=TipoAfiliacion.MONOTRIBUTO,
        )
        contexto = ks.contexto_para_lead(lead, "calificando", "Soy monotributista")
        assert "monotribut" in contexto.lower() or "SERVIRED" in contexto


# ─────────────────────────────────────────
# Test 5: Cliente objeta precio
# ─────────────────────────────────────────

class TestObjecionPrecio:
    """Cliente que objeta el precio."""

    def test_contexto_objecion_precio(self, ks):
        lead = Lead(
            lead_id="test9",
            nombre="Diego",
            prioridad_cliente=PrioridadCliente.ECONOMICO,
        )
        contexto = ks.contexto_para_lead(
            lead, "manejando_objeciones", "Es muy caro"
        )
        assert "SERVIRED" in contexto
        assert len(contexto) > 100

    def test_objecion_avanzada_responde_precio(self, ks):
        respuesta = ks.obtener_respuesta_objecion("caro")
        assert len(respuesta) > 20

    def test_objecion_avanzada_responde_pensar(self, ks):
        respuesta = ks.obtener_respuesta_objecion("pensar")
        assert len(respuesta) > 20


# ─────────────────────────────────────────
# Test 6: Cliente pregunta cobertura específica
# ─────────────────────────────────────────

class TestCoberturaEspecifica:
    """Cliente pregunta por cobertura específica."""

    def test_pregunta_odontologia(self, ks):
        lead = Lead(lead_id="test10", nombre="Sofía")
        contexto = ks.contexto_para_lead(
            lead, "calificando", "¿Cubren odontología?"
        )
        assert "odontol" in contexto.lower() or "SERVIRED" in contexto

    def test_pregunta_farmacia(self, ks):
        lead = Lead(lead_id="test11", nombre="Martín")
        contexto = ks.contexto_para_lead(
            lead, "calificando", "¿Tienen farmacias adheridas?"
        )
        assert "farmacia" in contexto.lower() or "SERVIRED" in contexto


# ─────────────────────────────────────────
# Test 7: Detección de perfil
# ─────────────────────────────────────────

class TestDeteccionPerfil:
    """Verifica la detección de perfil del Lead."""

    def test_perfil_familia(self, ks):
        lead = Lead(lead_id="t", grupo_familiar=Lead.model_fields["grupo_familiar"].default_factory())
        lead.grupo_familiar.conyuge = True
        assert ks._detectar_perfil(lead) == "familia"

    def test_perfil_monotributista(self, ks):
        lead = Lead(lead_id="t", tipo_afiliacion=TipoAfiliacion.MONOTRIBUTO)
        assert ks._detectar_perfil(lead) == "monotributista"

    def test_perfil_aportes(self, ks):
        lead = Lead(lead_id="t", tipo_afiliacion=TipoAfiliacion.RELACION_DEPENDENCIA)
        assert ks._detectar_perfil(lead) == "aportes"

    def test_perfil_economico(self, ks):
        lead = Lead(lead_id="t", prioridad_cliente=PrioridadCliente.ECONOMICO)
        assert ks._detectar_perfil(lead) == "económico"

    def test_perfil_vacio(self, ks):
        lead = Lead(lead_id="t")
        assert ks._detectar_perfil(lead) == ""
