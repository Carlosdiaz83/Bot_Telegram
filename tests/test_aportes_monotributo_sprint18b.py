"""
Tests Sprint 18B — Aportes Monotributo desde Knowledge Database.

Cubre:
    - ServiredAportesMonotributoDB: modelo de aportes
    - AportesMonotributoRepository: upsert y búsquedas
    - aportes_importer: lectura de Excel y carga idempotente
    - ServiredCalculator: cotización con aportes monotributo
    - Lead: campo categoria_monotributo
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from openpyxl import Workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.models import Base, ServiredAportesMonotributoDB
from app.database.repository import AportesMonotributoRepository
from app.models.lead import Lead, GrupoFamiliar, TipoAfiliacion
from app.services.aportes_importer import (
    _normalizar_categoria,
    _parsear_monto,
    _buscar_columna_categoria,
    _buscar_columna_monto,
    importar_aportes,
)


# ─────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────

@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture()
def aportes_repo(db_session):
    return AportesMonotributoRepository(db_session)


def _crear_xlsx_aportes(ruta: str, data: list[tuple[str, float]] | None = None):
    if data is None:
        data = [
            ("A", 5386.79),
            ("B", 8002.16),
            ("H", 42737.30),
        ]
    wb = Workbook()
    ws = wb.active
    ws.title = "Aportes"
    ws.append(["Categoria", "Aporte Mensual"])
    for cat, monto in data:
        ws.append([cat, monto])
    wb.save(ruta)
    wb.close()


# ─────────────────────────────────────────
# Tests: _normalizar_categoria
# ─────────────────────────────────────────

class TestNormalizarCategoria:
    def test_letra_simple(self):
        assert _normalizar_categoria("A") == "A"

    def test_minuscula(self):
        assert _normalizar_categoria("h") == "H"

    def test_con_espacios(self):
        assert _normalizar_categoria("  B  ") == "B"

    def test_invalida(self):
        assert _normalizar_categoria("Z") is None

    def test_none(self):
        assert _normalizar_categoria(None) is None

    def test_texto_largo(self):
        assert _normalizar_categoria("Categoria A") is None


# ─────────────────────────────────────────
# Tests: _parsear_monto
# ─────────────────────────────────────────

class TestParsearMonto:
    def test_float(self):
        assert _parsear_monto(42737.30) == 42737.30

    def test_entero(self):
        assert _parsear_monto(5000) == 5000.0

    def test_string_simple(self):
        assert _parsear_monto("42737.30") == 42737.30

    def test_string_formato_argentino(self):
        assert _parsear_monto("$42.737,30") == 42737.30

    def test_none(self):
        assert _parsear_monto(None) == 0.0

    def test_vacio(self):
        assert _parsear_monto("") == 0.0


# ─────────────────────────────────────────
# Tests: _buscar_columna_categoria / _buscar_columna_monto
# ─────────────────────────────────────────

class TestBuscarColumnas:
    def test_categoria_en_header(self):
        header = ["Categoria", "Aporte Mensual"]
        assert _buscar_columna_categoria(header) == 0

    def test_monto_en_header(self):
        header = ["Categoria", "Aporte Mensual"]
        idx_cat = _buscar_columna_categoria(header)
        assert _buscar_columna_monto(header, idx_cat) == 1

    def test_categoria_con_acentos(self):
        header = ["Categoría", "Monto"]
        assert _buscar_columna_categoria(header) == 0

    def test_no_encuentra_categoria(self):
        header = ["Nombre", "Valor"]
        assert _buscar_columna_categoria(header) == -1


# ─────────────────────────────────────────
# Tests: AportesMonotributoRepository.upsert
# ─────────────────────────────────────────

class TestAportesMonotributoRepository:
    def test_crear_nuevo(self, aportes_repo):
        accion, reg = aportes_repo.upsert("H", 42737.30, "test.xlsx")
        assert accion == "created"
        assert reg.categoria == "H"
        assert reg.monto == 42737.30

    def test_buscar_por_categoria(self, aportes_repo):
        aportes_repo.upsert("H", 42737.30)
        resultado = aportes_repo.buscar_por_categoria("H")
        assert resultado is not None
        assert resultado.monto == 42737.30

    def test_buscar_no_existe(self, aportes_repo):
        assert aportes_repo.buscar_por_categoria("Z") is None

    def test_actualizar_monto(self, aportes_repo):
        aportes_repo.upsert("H", 40000.0)
        accion, reg = aportes_repo.upsert("H", 42737.30)
        assert accion == "updated"
        assert reg.monto == 42737.30

    def test_sin_cambio(self, aportes_repo):
        aportes_repo.upsert("H", 42737.30)
        accion, reg = aportes_repo.upsert("H", 42737.30)
        assert accion == "unchanged"

    def test_buscar_todos(self, aportes_repo):
        aportes_repo.upsert("A", 5000.0)
        aportes_repo.upsert("B", 8000.0)
        todos = aportes_repo.buscar_todos()
        assert len(todos) == 2
        assert todos[0].categoria == "A"
        assert todos[1].categoria == "B"

    def test_minuscula_se_normaliza(self, aportes_repo):
        accion, reg = aportes_repo.upsert("h", 42737.30)
        assert reg.categoria == "H"


# ─────────────────────────────────────────
# Tests: importar_aportes
# ─────────────────────────────────────────

class TestImportarAportes:
    def test_importar_basico(self, db_session):
        with tempfile.TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "aportes.xlsx"
            _crear_xlsx_aportes(str(ruta))
            resultado = importar_aportes(ruta, db_session)
            assert resultado.exitoso
            assert resultado.registros_creados == 3

    def test_importar_idempotente(self, db_session):
        with tempfile.TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "aportes.xlsx"
            _crear_xlsx_aportes(str(ruta))
            importar_aportes(ruta, db_session)
            resultado = importar_aportes(ruta, db_session)
            assert resultado.registros_creados == 0
            assert resultado.registros_sin_cambio == 3

    def test_importar_actualiza(self, db_session):
        with tempfile.TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "aportes.xlsx"
            _crear_xlsx_aportes(str(ruta), [("H", 40000.0)])
            importar_aportes(ruta, db_session)
            _crear_xlsx_aportes(str(ruta), [("H", 42737.30)])
            resultado = importar_aportes(ruta, db_session)
            assert resultado.registros_actualizados == 1

    def test_archivo_no_existe(self, db_session):
        resultado = importar_aportes("/no/existe.xlsx", db_session)
        assert not resultado.exitoso


# ─────────────────────────────────────────
# Tests: ServiredCalculator con aportes monotributo
# ─────────────────────────────────────────

class TestCalculadoraAportesMonotributo:
    def _setup_calculator(self, db_session, aportes_data=None):
        from app.database.repository import KnowledgeRepository, PriceRepository
        from app.services.servired_calculator import ServiredCalculator

        if aportes_data is None:
            aportes_data = [("H", 42737.30)]

        repo = AportesMonotributoRepository(db_session)
        for cat, monto in aportes_data:
            repo.upsert(cat, monto)

        return ServiredCalculator(
            db=db_session,
            aportes_monotributo_repository=repo,
        )

    def test_aporte_categoria_H_un_integrante(self, db_session):
        calc = self._setup_calculator(db_session)
        lead = Lead(
            lead_id="1",
            nombre="Juan",
            edad=35,
            tipo_afiliacion=TipoAfiliacion.MONOTRIBUTO,
            categoria_monotributo="H",
        )
        resultado = calc.cotizar(lead, zona="cordoba")
        assert resultado.aportes_calculados == 42737.30

    def test_aporte_categoria_H_tres_integrantes(self, db_session):
        calc = self._setup_calculator(db_session)
        lead = Lead(
            lead_id="1",
            nombre="Juan",
            edad=35,
            tipo_afiliacion=TipoAfiliacion.MONOTRIBUTO,
            categoria_monotributo="H",
            grupo_familiar=GrupoFamiliar(conyuge=True, hijos=True),
            cantidad_hijos=1,
            cantidad_integrantes=3,
        )
        resultado = calc.cotizar(lead, zona="cordoba")
        assert resultado.aportes_calculados == round(42737.30 * 3, 2)

    def test_aporte_categoria_A(self, db_session):
        calc = self._setup_calculator(db_session, [("A", 5386.79)])
        lead = Lead(
            lead_id="1",
            nombre="Maria",
            edad=28,
            tipo_afiliacion=TipoAfiliacion.MONOTRIBUTO,
            categoria_monotributo="A",
        )
        resultado = calc.cotizar(lead, zona="cordoba")
        assert resultado.aportes_calculados == 5386.79

    def test_aporte_sin_categoria_no_aplica(self, db_session):
        calc = self._setup_calculator(db_session)
        lead = Lead(
            lead_id="1",
            nombre="SinCategoria",
            edad=30,
            tipo_afiliacion=TipoAfiliacion.MONOTRIBUTO,
        )
        resultado = calc.cotizar(lead, zona="cordoba")
        assert resultado.aportes_calculados == 0.0

    def test_aporte_particular_no_aplica(self, db_session):
        calc = self._setup_calculator(db_session)
        lead = Lead(
            lead_id="1",
            nombre="Particular",
            edad=30,
            tipo_afiliacion=TipoAfiliacion.PARTICULAR,
        )
        resultado = calc.cotizar(lead, zona="cordoba")
        assert resultado.aportes_calculados == 0.0

    def test_calcular_valor_final(self, db_session):
        calc = self._setup_calculator(db_session)
        lead = Lead(
            lead_id="1",
            nombre="Juan",
            edad=35,
            tipo_afiliacion=TipoAfiliacion.MONOTRIBUTO,
            categoria_monotributo="H",
        )
        resultado = calc.cotizar(
            lead, zona="cordoba", nombre_plan="medimax",
        )
        # valor_a_pagar = valor_plan - aportes
        if resultado.valor_plan_total > 0:
            expected = max(0.0, resultado.valor_plan_total - 42737.30)
            assert resultado.valor_a_pagar == round(expected, 2)


# ─────────────────────────────────────────
# Tests: Lead model con categoria_monotributo
# ─────────────────────────────────────────

class TestLeadCategoriaMonotributo:
    def test_lead_con_categoria(self):
        lead = Lead(
            lead_id="1",
            tipo_afiliacion=TipoAfiliacion.MONOTRIBUTO,
            categoria_monotributo="H",
        )
        assert lead.categoria_monotributo == "H"

    def test_lead_sin_categoria(self):
        lead = Lead(lead_id="1")
        assert lead.categoria_monotributo is None

    def test_lead_db_sync_roundtrip(self, db_session):
        from app.database.repository import LeadRepository
        repo = LeadRepository(db_session)
        lead_db = repo.crear_lead(telegram_id=123)
        lead_db.tipo_afiliacion = "monotributo"
        lead_db.categoria_monotributo = "H"
        db_session.commit()

        lead = repo.db_a_lead_domain(lead_db)
        assert lead.categoria_monotributo == "H"

    def test_lead_domain_a_db_sync(self, db_session):
        from app.database.repository import LeadRepository
        repo = LeadRepository(db_session)
        lead_db = repo.crear_lead(telegram_id=123)

        lead = Lead(
            lead_id="123",
            tipo_afiliacion=TipoAfiliacion.MONOTRIBUTO,
            categoria_monotributo="B",
        )
        repo.lead_domain_a_db(lead, lead_db)
        assert lead_db.categoria_monotributo == "B"
