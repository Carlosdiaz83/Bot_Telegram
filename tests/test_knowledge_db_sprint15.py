"""
Tests — Sprint 15.1: Simplificación Knowledge Engine SERVIRED.

Verifica la tabla única ServiredKnowledgeDB:
    1. Cliente familia + prioridad precio → planes relevantes
    2. Cliente busca mayor cobertura → info de coberturas
    3. Cliente farmacia → info con tags relevantes
    4. Cliente objeta precio → info de objeciones/cierres
    5. Info inexistente → respuesta vacía (no inventa)
    6. DocumentIngester: ingestir texto directo a tabla única
    7. KnowledgeRepository: CRUD completo
    8. KnowledgeEngine: contexto para lead con DB
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.database import crear_tablas
from app.database.models import Base
from app.database.repository import KnowledgeRepository
from app.models.lead import (
    Lead,
    GrupoFamiliar,
    NecesidadPrincipal,
    PrioridadCliente,
    TipoAfiliacion,
)
from app.services.knowledge_engine import KnowledgeEngine
from app.services.document_ingester import DocumentIngester


# ─────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────

@pytest.fixture
def db_session():
    """Sesión de DB SQLite en memoria para tests."""
    engine = create_engine("sqlite:///:memory:")
    crear_tablas(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def repo(db_session):
    """KnowledgeRepository con DB vacía."""
    return KnowledgeRepository(db_session)


@pytest.fixture
def engine(db_session):
    """KnowledgeEngine con DB vacía."""
    return KnowledgeEngine(db_session)


@pytest.fixture
def ingester(engine):
    """DocumentIngester con KnowledgeEngine."""
    return DocumentIngester(engine)


@pytest.fixture
def lead_familia():
    """Lead de familia con prioridad económica."""
    lead = Lead(
        lead_id="12345",
        nombre="Carlos",
        edad=35,
        localidad="Córdoba",
        grupo_familiar=GrupoFamiliar(conyuge=True, hijos=True),
        necesidad_principal=NecesidadPrincipal.COBERTURA_FAMILIAR,
        prioridad_cliente=PrioridadCliente.ECONOMICO,
        tipo_afiliacion=TipoAfiliacion.MONOTRIBUTO,
    )
    lead.cantidad_hijos = 2
    return lead


@pytest.fixture
def lead_soltero():
    """Lead soltero sin grupo familiar."""
    return Lead(
        lead_id="67890",
        nombre="María",
        edad=28,
        localidad="Buenos Aires",
        grupo_familiar=GrupoFamiliar(),
        necesidad_principal=NecesidadPrincipal.ACCESO_PRESTADORES,
        prioridad_cliente=PrioridadCliente.COMPLETO,
        tipo_afiliacion=TipoAfiliacion.PARTICULAR,
    )


def _seed_conocimiento(repo: KnowledgeRepository) -> None:
    """Carga datos de prueba en la tabla única."""
    # Planes
    repo.crear("Planes SERVIRED — Medimax CO", "planes",
               "Plan Medimax CO: $8.500/mes. Cobertura ambulatoria con farmacia.",
               tags="medimax,co,plan,precio,ambulatorio", prioridad_comercial=10)
    repo.crear("Planes SERVIRED — Medimax", "planes",
               "Plan Medimax: $12.000/mes. Cobertura ambulatoria + internación con farmacia.",
               tags="medimax,plan,precio,ambulatorio,internacion", prioridad_comercial=20)
    repo.crear("Planes SERVIRED — Medimax Gold", "planes",
               "Plan Medimax Gold: $18.000/mes. Cobertura premium con farmacia y odontología.",
               tags="medimax,gold,plan,precio,premium,odontologia", prioridad_comercial=30)
    repo.crear("Planes SERVIRED — Gold", "planes",
               "Plan Gold: $25.000/mes. Cobertura total premium sin deducible.",
               tags="gold,plan,precio,premium,total", prioridad_comercial=40)

    # Coberturas
    repo.crear("Red de centros médicos", "coberturas",
               "SERVIRED ofrece cobertura en más de 500 centros médicos en todo el país.",
               tags="centros,medicos,red,cobertura", prioridad_comercial=15)
    repo.crear("Farmacias adheridas", "coberturas",
               "Descuento del 30% en más de 200 farmacias adheridas en todo el país.",
               tags="farmacia,descuento,medicamentos,adheridas", prioridad_comercial=15)

    # Beneficios
    repo.crear("Sin período de permanencia", "beneficios",
               "Podés cancelar tu plan cuando quieras, sin penalidades ni permanencia mínima.",
               tags="permanencia,cancelar,sin", prioridad_comercial=10)
    repo.crear("Acceso inmediato", "beneficios",
               "Tu cobertura activa al momento de la contratación. Sin esperas.",
               tags="acceso,inmediato,activo", prioridad_comercial=5)

    # Objeciones
    repo.crear("Respuesta objeción precio", "objeciones",
               "Entiendo que el precio es una preocupación. Nuestros planes se adaptan a diferentes presupuestos y podés empezar por uno más accesible.",
               tags="precio,costo,caro,accesible,presupuesto", prioridad_comercial=20)
    repo.crear("Respuesta objeción pensar", "objeciones",
               "Tomate tu tiempo para pensarlo. ¿Querés que te deje mi contacto para que cuando estés listo podamos avanzar?",
               tags="pensar,duda,tiempo,contacto", prioridad_comercial=10)

    # Cierres
    repo.crear("Cierre primer mes descuento", "cierres",
               "El primer mes tenés 50% de descuento. Es una excelente oportunidad para probar.",
               tags="descuento,primer,mes,oportunidad", prioridad_comercial=15)
    repo.crear("Cierre acceso inmediato", "cierres",
               "Si avanzás ahora, tu cobertura queda activa inmediatamente.",
               tags="acceso,inmediato,ahora,activar", prioridad_comercial=10)

    # Argumentos comerciales
    repo.crear("Argumento familias", "argumentos",
               "Para familias, SERVIRED ofrece cobertura completa con descuentos para todo el grupo.",
               tags="familia,grupo,descuento,completa", prioridad_comercial=10)
    repo.crear("Argumento monotributistas", "argumentos",
               "Si sos monotributista, tenemos planes especiales que se adaptan a tu situación.",
               tags="monotributista,especial,plan", prioridad_comercial=10)


# ─────────────────────────────────────────
# Test 1: Cliente familia + prioridad precio
# ─────────────────────────────────────────

class TestFamiliaPrioridadPrecio:
    """Verifica que un cliente familia con prioridad precio recibe planes relevantes."""

    def test_planes_en_contexto(self, engine, repo, lead_familia):
        _seed_conocimiento(repo)
        contexto = engine.contexto_para_lead(lead_familia, "presentando_valor", "quiero un plan familiar")
        assert "Medimax" in contexto or "Plan" in contexto

    def test_perfil_detectado(self, engine, lead_familia):
        perfil = engine._detectar_perfil(lead_familia)
        assert perfil == "economico"


# ─────────────────────────────────────────
# Test 2: Cliente busca mayor cobertura
# ─────────────────────────────────────────

class TestBuscaMayorCobertura:
    """Verifica que un cliente buscando cobertura recibe info relevante."""

    def test_coberturas_en_contexto(self, engine, repo, lead_soltero):
        _seed_conocimiento(repo)
        contexto = engine.contexto_para_lead(lead_soltero, "presentando_valor", "quiero mejor cobertura")
        assert "centros médicos" in contexto or "farmacia" in contexto.lower()

    def test_beneficios_en_contexto(self, engine, repo, lead_soltero):
        _seed_conocimiento(repo)
        contexto = engine.contexto_para_lead(lead_soltero, "", "permanencia")
        assert "permanencia" in contexto.lower() or "cancelar" in contexto.lower()


# ─────────────────────────────────────────
# Test 3: Cliente farmacia
# ─────────────────────────────────────────

class TestClienteFarmacia:
    """Verifica que un cliente preguntando por farmacia recibe info relevante."""

    def test_farmacia_en_contexto(self, engine, repo, lead_familia):
        _seed_conocimiento(repo)
        contexto = engine.contexto_para_lead(lead_familia, "", "tienen farmacias con descuento")
        assert "farmacia" in contexto.lower() or "30%" in contexto

    def test_tags_farmacia(self, engine, repo):
        _seed_conocimiento(repo)
        items = repo.buscar_por_tags(["farmacia"], limite=5)
        assert len(items) >= 1
        assert any("farmacia" in i.tags.lower() for i in items)


# ─────────────────────────────────────────
# Test 4: Cliente objeta precio
# ─────────────────────────────────────────

class TestObjecionPrecio:
    """Verifica que un cliente que objeta precio recibe info de objeciones y cierres."""

    def test_objecion_precio_en_contexto(self, engine, repo, lead_familia):
        _seed_conocimiento(repo)
        contexto = engine.contexto_para_lead(lead_familia, "manejando_objeciones", "es muy caro")
        assert "precio" in contexto.lower() or "accesible" in contexto.lower()

    def test_cierre_en_contexto(self, engine, repo, lead_familia):
        _seed_conocimiento(repo)
        contexto = engine.contexto_para_lead(lead_familia, "intentando_cierre", "descuento")
        assert "descuento" in contexto.lower()


# ─────────────────────────────────────────
# Test 5: Info inexistente
# ─────────────────────────────────────────

class TestInfoInexistente:
    """Verifica que no se inventa info cuando no hay datos en la DB."""

    def test_contexto_vacio_sin_datos(self, engine, lead_familia):
        contexto = engine.contexto_para_lead(lead_familia, "presentando_valor", "quiero info")
        assert isinstance(contexto, str)
        assert len(contexto) == 0

    def test_tags_no_inventados(self, engine, repo):
        items = repo.buscar_por_tags(["xyz_inexistente_123"], limite=5)
        assert len(items) == 0

    def test_categoria_vacia(self, engine, repo):
        items = repo.buscar_por_categoria("inexistente")
        assert len(items) == 0


# ─────────────────────────────────────────
# Test 6: DocumentIngester
# ─────────────────────────────────────────

class TestDocumentIngester:
    """Verifica el pipeline de ingestión de documentos."""

    def test_ingestir_texto_crea_registro(self, ingester, db_session):
        item_id = ingester.ingestir_texto(
            categoria="informacion",
            titulo="SERVIRED Info",
            contenido="SERVIRED es una obra social que brinda cobertura médica.",
        )
        assert item_id > 0
        repo = KnowledgeRepository(db_session)
        item = repo.buscar_por_id(item_id)
        assert item is not None
        assert item.titulo == "SERVIRED Info"
        assert item.categoria == "informacion"

    def test_ingestir_texto_con_tags(self, ingester, db_session):
        item_id = ingester.ingestir_texto(
            categoria="test",
            titulo="Test Tags",
            contenido=" contenido de prueba",
            tags="prueba,test,tag",
        )
        repo = KnowledgeRepository(db_session)
        item = repo.buscar_por_id(item_id)
        assert item.tags == "prueba,test,tag"

    def test_ingestir_texto_con_prioridad(self, ingester, db_session):
        item_id = ingester.ingestir_texto(
            categoria="test",
            titulo="Test Prioridad",
            contenido=" contenido",
            prioridad_comercial=50,
        )
        repo = KnowledgeRepository(db_session)
        item = repo.buscar_por_id(item_id)
        assert item.prioridad_comercial == 50


# ─────────────────────────────────────────
# Test 7: KnowledgeRepository CRUD
# ─────────────────────────────────────────

class TestKnowledgeRepository:
    """Verifica operaciones CRUD del repositorio."""

    def test_crear(self, repo):
        item = repo.crear("Test", "test", "Contenido de prueba")
        assert item.id > 0
        assert item.titulo == "Test"
        assert item.activo is True

    def test_buscar_por_categoria(self, repo):
        repo.crear("Doc1", "planes", " contenido 1")
        repo.crear("Doc2", "planes", " contenido 2")
        repo.crear("Doc3", "coberturas", " contenido 3")
        items = repo.buscar_por_categoria("planes")
        assert len(items) == 2

    def test_buscar_por_tags(self, repo):
        repo.crear("Item1", "test", " contenido", tags="farmacia,descuento")
        repo.crear("Item2", "test", " contenido", tags="odontologia,premium")
        items = repo.buscar_por_tags(["farmacia"])
        assert len(items) == 1

    def test_buscar_por_texto(self, repo):
        repo.crear("Item1", "test", "Plan Medimax Gold premium")
        items = repo.buscar_por_texto("Medimax")
        assert len(items) == 1

    def test_desactivar(self, repo):
        item = repo.crear("Desactivar", "test", " contenido")
        assert repo.desactivar(item.id) is True
        item_recargado = repo.buscar_por_id(item.id)
        assert item_recargado.activo is False

    def test_eliminar(self, repo):
        item = repo.crear("Eliminar", "test", " contenido")
        assert repo.eliminar(item.id) is True
        assert repo.buscar_por_id(item.id) is None

    def test_activos(self, repo):
        repo.crear("Activo1", "test", " contenido")
        repo.crear("Activo2", "test", " contenido")
        activos = repo.activos()
        assert len(activos) >= 2

    def test_prioridad_orden(self, repo):
        repo.crear("Baja", "test", " contenido", prioridad_comercial=5)
        repo.crear("Alta", "test", " contenido", prioridad_comercial=50)
        items = repo.buscar_por_categoria("test")
        assert items[0].titulo == "Alta"


# ─────────────────────────────────────────
# Test 8: KnowledgeEngine integración
# ─────────────────────────────────────────

class TestKnowledgeEngineIntegracion:
    """Verifica la integración completa de KnowledgeEngine."""

    def test_disponible_con_datos(self, engine, repo):
        _seed_conocimiento(repo)
        assert engine.disponible is True

    def test_no_disponible_vacio(self, engine):
        assert engine.disponible is False

    def test_guardar(self, engine):
        item_id = engine.guardar("Test", "test", " contenido")
        assert item_id > 0

    def test_contexto_con_datos(self, engine, repo, lead_familia):
        _seed_conocimiento(repo)
        contexto = engine.contexto_para_lead(lead_familia, "presentando_valor", "quiero un plan")
        assert len(contexto) > 50
        assert "Medimax" in contexto or "Plan" in contexto

    def test_contexto_objecion_precio(self, engine, repo, lead_familia):
        _seed_conocimiento(repo)
        contexto = engine.contexto_para_lead(lead_familia, "manejando_objeciones", "precio")
        assert "precio" in contexto.lower() or "accesible" in contexto.lower()

    def test_contexto_cierre(self, engine, repo, lead_familia):
        _seed_conocimiento(repo)
        contexto = engine.contexto_para_lead(lead_familia, "intentando_cierre", "avanzo")
        assert "descuento" in contexto.lower() or "inmediato" in contexto.lower()
