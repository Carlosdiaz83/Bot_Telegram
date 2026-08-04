"""
Regresión Sprint 26 — Cotización de Monotributo Joven.

Reproduce el caso reportado: monotributo categoría A de 21 años.
El calculador debe:
    - Aplicar el precio "JOVEN" del plan (rango etario más acotado)
      y NO el del titular.
    - Descontar el aporte de la categoría A (valor real MAYO 2026).
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.models import Base
from app.database.repository import AportesMonotributoRepository, PriceRepository
from app.models.lead import Lead, TipoAfiliacion
from app.services.servired_calculator import ServiredCalculator


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture()
def calculator(db_session):
    price_repo = PriceRepository(db_session)
    # Estructura real de la hoja MONOTRIBUTOS del Excel MAYO 2026.
    for plan in ("medimax",):
        for zona, titular, joven, hijo in (
            ("cordoba", 60000.0, 45000.0, 45000.0),
            ("interior", 66150.0, 49612.5, 49612.5),
        ):
            price_repo.crear("monotributo", plan, zona, titular, 0, 44)
            price_repo.crear("monotributo", plan, zona, joven, 0, 30)
            price_repo.crear("monotributo", plan, zona, hijo, 0, 99)

    aportes_repo = AportesMonotributoRepository(db_session)
    aportes_repo.upsert("A", 19791.10)

    return ServiredCalculator(
        db=db_session,
        price_repository=price_repo,
        aportes_monotributo_repository=aportes_repo,
    )


def _lead_joven_28():
    return Lead(
        lead_id="1",
        nombre="Juan",
        edad=28,
        tipo_afiliacion=TipoAfiliacion.MONOTRIBUTO,
        categoria_monotributo="A",
    )


class TestMonotributoJoven:
    def test_aplica_precio_joven_no_titular_cordoba(self, calculator):
        resultado = calculator.cotizar(
            _lead_joven_28(), zona="cordoba", nombre_plan="medimax",
        )
        assert resultado.valor_plan_total == 45000.0
        assert resultado.aportes_calculados == 19791.10
        assert resultado.valor_a_pagar == round(45000.0 - 19791.10, 2)
        assert resultado.plan_joven_disponible is True

    def test_aplica_precio_joven_interior(self, calculator):
        """Caso reportado: interior → 49612.50 - 19791.10 = 29821.40."""
        resultado = calculator.cotizar(
            _lead_joven_28(), zona="interior", nombre_plan="medimax",
        )
        assert resultado.valor_plan_total == 49612.5
        assert resultado.aportes_calculados == 19791.10
        assert resultado.valor_a_pagar == 29821.4
        assert resultado.plan_joven_disponible is True

    def test_mayor_de_30_no_aplica_joven(self, calculator):
        lead = Lead(
            lead_id="2",
            nombre="Luis",
            edad=40,
            tipo_afiliacion=TipoAfiliacion.MONOTRIBUTO,
            categoria_monotributo="A",
        )
        resultado = calculator.cotizar(
            lead, zona="cordoba", nombre_plan="medimax",
        )
        assert resultado.valor_plan_total == 60000.0
        assert resultado.plan_joven_disponible is False
