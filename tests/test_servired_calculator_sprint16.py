"""
Tests del Sprint 16 — Calculadora Comercial SERVIRED.

Cubre: aportes, Plan Joven, Córdoba/Interior, cotización completa,
extracción de conceptos, detección de recibo, integración con ConversationManager.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.models import Base
from app.database.models import ServiredKnowledgeDB
from app.database.repository import KnowledgeRepository
from app.models.lead import (
    GrupoFamiliar,
    Lead,
    PrioridadCliente,
    TipoAfiliacion,
)
from app.services.servired_calculator import (
    FACTOR_APORTES,
    IntegranteCotizacion,
    ServiredCalculator,
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


@pytest.fixture()
def calculator(db_session):
    return ServiredCalculator(db_session)


@pytest.fixture()
def knowledge_repo(db_session):
    return KnowledgeRepository(db_session)


def _cargar_precios_test(knowledge_repo) -> None:
    """Carga precios de prueba en la DB."""
    knowledge_repo.crear(
        titulo="Precios SERVIRED",
        categoria="precios",
        contenido=(
            "Precios SERVIRED 2024:\n"
            "- Medimax CO: $12.000 (Córdoba), $10.000 (Interior)\n"
            "- Medimax: $18.000 (Córdoba), $16.000 (Interior)\n"
            "- Medimax Gold: $28.000 (Córdoba), $25.000 (Interior)\n"
            "- Gold: $35.000 (Córdoba), $32.000 (Interior)\n"
        ),
        tags="precios,medimax,gold,planes",
    )


def _cargar_planes_test(knowledge_repo) -> None:
    """Carga info de planes en la DB."""
    knowledge_repo.crear(
        titulo="Planes SERVIRED",
        categoria="planes",
        contenido=(
            "Planes SERVIRED:\n"
            "Medimax CO: cobertura ambulatoria. Desde $12.000.\n"
            "Medimax: cobertura ambulatoria e internación. Desde $18.000.\n"
            "Medimax Gold: cobertura completa con odontología. Desde $28.000.\n"
            "Gold: cobertura premium. Desde $35.000.\n"
        ),
        tags="planes,medimax,gold",
    )


# ─────────────────────────────────────────
# Tests de Aportes
# ─────────────────────────────────────────


class TestCalcularAportes:
    def test_un_solo_concepto(self, calculator):
        aportes = calculator.calcular_aportes([50000.0])
        esperado = round(50000.0 * FACTOR_APORTES, 2)
        assert aportes == esperado

    def test_varios_conceptos(self, calculator):
        conceptos = [30000.0, 15000.0, 5000.0]
        total = sum(conceptos)
        esperado = round(total * FACTOR_APORTES, 2)
        aportes = calculator.calcular_aportes(conceptos)
        assert aportes == esperado

    def test_lista_vacia(self, calculator):
        assert calculator.calcular_aportes([]) == 0.0

    def test_concepto_unico_cero(self, calculator):
        assert calculator.calcular_aportes([0.0]) == 0.0

    def test_monto_grande(self, calculator):
        conceptos = [100000.0, 50000.0]
        total = sum(conceptos)
        esperado = round(total * FACTOR_APORTES, 2)
        assert calculator.calcular_aportes(conceptos) == esperado

    def test_decimales(self, calculator):
        aportes = calculator.calcular_aportes([12345.67])
        assert aportes > 0
        assert isinstance(aportes, float)


# ─────────────────────────────────────────
# Tests de Plan Joven
# ─────────────────────────────────────────


class TestVerificarPlanJoven:
    def test_todos_menores_30(self, calculator):
        disponible, rechazado = calculator.verificar_plan_joven([25, 28, 20])
        assert disponible is True
        assert rechazado is False

    def test_todos_igual_30(self, calculator):
        disponible, rechazado = calculator.verificar_plan_joven([30, 30, 30])
        assert disponible is True
        assert rechazado is False

    def test_uno_mayor_30(self, calculator):
        disponible, rechazado = calculator.verificar_plan_joven([25, 35, 20])
        assert disponible is False
        assert rechazado is True

    def test_todos_mayores_30(self, calculator):
        disponible, rechazado = calculator.verificar_plan_joven([40, 45, 50])
        assert disponible is False
        assert rechazado is True

    def test_lista_vacia(self, calculator):
        disponible, rechazado = calculator.verificar_plan_joven([])
        assert disponible is False
        assert rechazado is False

    def test_un_solo_integrante_joven(self, calculator):
        disponible, rechazado = calculator.verificar_plan_joven([22])
        assert disponible is True
        assert rechazado is False

    def test_un_solo_integrante_no_joven(self, calculator):
        disponible, rechazado = calculator.verificar_plan_joven([35])
        assert disponible is False
        assert rechazado is True

    def test_edad_limite_exacta(self, calculator):
        disponible, rechazado = calculator.verificar_plan_joven([30])
        assert disponible is True
        assert rechazado is False

    def test_edad_un_mas(self, calculator):
        disponible, rechazado = calculator.verificar_plan_joven([31])
        assert disponible is False
        assert rechazado is True


# ─────────────────────────────────────────
# Tests de Precios desde Knowledge
# ─────────────────────────────────────────


class TestObtenerPrecios:
    def test_precios_en_categoria_precios(self, calculator, knowledge_repo):
        _cargar_precios_test(knowledge_repo)
        precios = calculator._obtener_precios_plan("medimax", "cordoba")
        assert precios is not None
        assert "cordoba" in precios

    def test_precios_en_categoria_planes(self, calculator, knowledge_repo):
        _cargar_planes_test(knowledge_repo)
        precios = calculator._obtener_precios_plan("medimax", "cordoba")
        assert precios is not None

    def test_plan_no_encontrado(self, calculator, knowledge_repo):
        precios = calculator._obtener_precios_plan("plan_inexistente", "cordoba")
        assert precios is None

    def test_db_vacia(self, calculator):
        precios = calculator._obtener_precios_plan("medimax", "cordoba")
        assert precios is None


# ─────────────────────────────────────────
# Tests de Valor del Plan
# ─────────────────────────────────────────


class TestCalcularValorPlan:
    def test_un_integrante_cordoba(self, calculator, knowledge_repo):
        _cargar_precios_test(knowledge_repo)
        valor = calculator.calcular_valor_plan("medimax", "cordoba", [40])
        assert valor == 18000.0

    def test_un_integrante_interior(self, calculator, knowledge_repo):
        _cargar_precios_test(knowledge_repo)
        valor = calculator.calcular_valor_plan("medimax", "interior", [40])
        assert valor == 16000.0

    def test_dos_integrantes(self, calculator, knowledge_repo):
        _cargar_precios_test(knowledge_repo)
        valor = calculator.calcular_valor_plan("medimax", "cordoba", [40, 35])
        assert valor == 36000.0

    def test_familia_4_integrantes(self, calculator, knowledge_repo):
        _cargar_precios_test(knowledge_repo)
        valor = calculator.calcular_valor_plan("medimax", "cordoba", [40, 38, 12, 8])
        assert valor == 72000.0

    def test_plan_gold(self, calculator, knowledge_repo):
        _cargar_precios_test(knowledge_repo)
        valor = calculator.calcular_valor_plan("medimax gold", "cordoba", [30])
        assert valor == 28000.0

    def test_plan_gold_interior(self, calculator, knowledge_repo):
        _cargar_precios_test(knowledge_repo)
        valor = calculator.calcular_valor_plan("medimax gold", "interior", [30])
        assert valor == 25000.0

    def test_sin_precios(self, calculator):
        valor = calculator.calcular_valor_plan("medimax", "cordoba", [40])
        assert valor is None


# ─────────────────────────────────────────
# Tests de Cotización Completa
# ─────────────────────────────────────────


class TestCotizar:
    def _lead_solo(self) -> Lead:
        return Lead(
            lead_id="100",
            nombre="Carlos",
            edad=40,
            localidad="Buenos Aires",
            grupo_familiar=GrupoFamiliar(titular=True),
        )

    def _lead_familia(self) -> Lead:
        return Lead(
            lead_id="200",
            nombre="María",
            edad=35,
            localidad="Córdoba",
            grupo_familiar=GrupoFamiliar(titular=True, conyuge=True, hijos=True),
            cantidad_hijos=2,
        )

    def _lead_joven(self) -> Lead:
        return Lead(
            lead_id="300",
            nombre="Lucas",
            edad=25,
            localidad="Córdoba",
            grupo_familiar=GrupoFamiliar(titular=True, conyuge=True),
        )

    def test_cotizacion_solo_titular(self, calculator, knowledge_repo):
        _cargar_precios_test(knowledge_repo)
        lead = self._lead_solo()
        resultado = calculator.cotizar(lead, zona="cordoba", nombre_plan="medimax")

        assert resultado.plan == "medimax"
        assert resultado.zona == "cordoba"
        assert len(resultado.integrantes) == 1
        assert resultado.valor_plan_total == 18000.0
        assert resultado.aportes_calculados == 0.0
        assert resultado.valor_a_pagar == 18000.0

    def test_cotizacion_familia(self, calculator, knowledge_repo):
        _cargar_precios_test(knowledge_repo)
        lead = self._lead_familia()
        resultado = calculator.cotizar(lead, zona="cordoba", nombre_plan="medimax")

        assert len(resultado.integrantes) == 4
        assert resultado.valor_plan_total == 72000.0

    def test_cotizacion_con_aportes(self, calculator, knowledge_repo):
        _cargar_precios_test(knowledge_repo)
        lead = self._lead_solo()
        resultado = calculator.cotizar(
            lead, conceptos_obra_social=[50000.0], zona="cordoba", nombre_plan="medimax"
        )

        assert resultado.aportes_calculados > 0
        assert resultado.valor_a_pagar < resultado.valor_plan_total

    def test_cotizacion_aportes_superan_plan(self, calculator, knowledge_repo):
        _cargar_precios_test(knowledge_repo)
        lead = self._lead_solo()
        resultado = calculator.cotizar(
            lead,
            conceptos_obra_social=[200000.0],
            zona="cordoba",
            nombre_plan="medimax",
        )

        assert resultado.valor_a_pagar == 0.0
        assert any("superan" in obs.lower() for obs in resultado.observaciones)

    def test_cotizacion_plan_joven_disponible(self, calculator, knowledge_repo):
        _cargar_precios_test(knowledge_repo)
        lead = self._lead_joven()
        resultado = calculator.cotizar(lead, zona="cordoba", nombre_plan="medimax")

        assert resultado.plan_joven_disponible is True
        assert resultado.plan_joven_rechazado is False

    def test_cotizacion_plan_joven_no_disponible(self, calculator, knowledge_repo):
        _cargar_precios_test(knowledge_repo)
        lead = self._lead_solo()  # 40 años
        resultado = calculator.cotizar(lead, zona="cordoba", nombre_plan="medimax")

        assert resultado.plan_joven_disponible is False
        assert resultado.plan_joven_rechazado is True

    def test_cotizacion_interior(self, calculator, knowledge_repo):
        _cargar_precios_test(knowledge_repo)
        lead = self._lead_solo()
        lead.localidad = "Mendoza"
        resultado = calculator.cotizar(lead, zona="interior", nombre_plan="medimax")

        assert resultado.valor_plan_total == 16000.0

    def test_cotizacion_sin_precios(self, calculator):
        lead = self._lead_solo()
        resultado = calculator.cotizar(lead, zona="cordoba", nombre_plan="medimax")

        assert resultado.valor_plan_total == 0.0
        assert len(resultado.observaciones) > 0

    def test_desglose_por_integrante(self, calculator, knowledge_repo):
        _cargar_precios_test(knowledge_repo)
        lead = self._lead_familia()
        resultado = calculator.cotizar(lead, zona="cordoba", nombre_plan="medimax")

        assert len(resultado.desglose_por_integrante) == 4
        for item in resultado.desglose_por_integrante:
            assert "nombre" in item
            assert "edad" in item
            assert "valor" in item
            assert item["valor"] > 0


# ─────────────────────────────────────────
# Tests de Generación de Propuesta
# ─────────────────────────────────────────


class TestGenerarPropuesta:
    def test_propuesta_basica(self, calculator, knowledge_repo):
        _cargar_precios_test(knowledge_repo)
        lead = Lead(
            lead_id="500",
            nombre="Ana",
            edad=30,
            grupo_familiar=GrupoFamiliar(titular=True),
        )
        resultado = calculator.cotizar(lead, zona="cordoba", nombre_plan="medimax")
        propuesta = calculator.generar_propuesta_texto(resultado)

        assert "Cotización SERVIRED" in propuesta
        assert "medimax" in propuesta.lower()
        assert "18,000" in propuesta or "18000" in propuesta

    def test_propuesta_con_aportes(self, calculator, knowledge_repo):
        _cargar_precios_test(knowledge_repo)
        lead = Lead(
            lead_id="501",
            nombre="Roberto",
            edad=45,
            grupo_familiar=GrupoFamiliar(titular=True),
        )
        resultado = calculator.cotizar(
            lead, conceptos_obra_social=[40000.0], zona="cordoba", nombre_plan="medimax"
        )
        propuesta = calculator.generar_propuesta_texto(resultado)

        assert "Aportes obra social" in propuesta
        assert "Valor a pagar" in propuesta

    def test_propuesta_plan_joven(self, calculator, knowledge_repo):
        _cargar_precios_test(knowledge_repo)
        lead = Lead(
            lead_id="502",
            nombre="Sofía",
            edad=25,
            grupo_familiar=GrupoFamiliar(titular=True, conyuge=True),
        )
        resultado = calculator.cotizar(lead, zona="cordoba", nombre_plan="medimax")
        propuesta = calculator.generar_propuesta_texto(resultado)

        assert "Plan Joven" in propuesta

    def test_propuesta_familia(self, calculator, knowledge_repo):
        _cargar_precios_test(knowledge_repo)
        lead = Lead(
            lead_id="503",
            nombre="Pedro",
            edad=40,
            grupo_familiar=GrupoFamiliar(titular=True, conyuge=True, hijos=True),
            cantidad_hijos=1,
        )
        resultado = calculator.cotizar(lead, zona="cordoba", nombre_plan="medimax")
        propuesta = calculator.generar_propuesta_texto(resultado)

        assert "Grupo familiar" in propuesta
        assert "3 personas" in propuesta


# ─────────────────────────────────────────
# Tests de Extracción de Conceptos (ConversationManager)
# ─────────────────────────────────────────


class TestExtraerConceptosObraSocial:
    def _manager(self):
        from app.services.conversation_manager import ConversationManager
        return ConversationManager()

    def test_un_monto_con_dolar(self):
        manager = self._manager()
        conceptos = manager._extraer_conceptos_obra_social("Son $15000")
        assert 15000.0 in conceptos

    def test_varios_montos(self):
        manager = self._manager()
        conceptos = manager._extraer_conceptos_obra_social(
            "$15000, $5000 y $3000"
        )
        assert len(conceptos) == 3
        assert 15000.0 in conceptos
        assert 5000.0 in conceptos
        assert 3000.0 in conceptos

    def test_monto_con_puntos(self):
        manager = self._manager()
        conceptos = manager._extraer_conceptos_obra_social("$15.000")
        assert 15000.0 in conceptos

    def test_sin_montos(self):
        manager = self._manager()
        conceptos = manager._extraer_conceptos_obra_social("No tengo recibo")
        assert len(conceptos) == 0

    def test_texto_largo(self):
        manager = self._manager()
        texto = (
            "En mi recibo dice: Obra Social $18500, "
            "y también Aportes Jubilatorios $5000"
        )
        conceptos = manager._extraer_conceptos_obra_social(texto)
        assert 18500.0 in conceptos


# ─────────────────────────────────────────
# Tests de Detección de Recibo
# ─────────────────────────────────────────


class TestDetectarRecibo:
    def _manager(self):
        from app.services.conversation_manager import ConversationManager
        return ConversationManager()

    def test_detecta_recibo_sueldo(self):
        manager = self._manager()
        assert manager._detectar_recibo_sueldo("Tengo recibo de sueldo") is True

    def test_detecta_recibo(self):
        manager = self._manager()
        assert manager._detectar_recibo_sueldo("Mi recibo dice...") is True

    def test_detecta_sueldo(self):
        manager = self._manager()
        assert manager._detectar_recibo_sueldo("Mi sueldo es...") is True

    def test_no_detecta_otro_mensaje(self):
        manager = self._manager()
        assert manager._detectar_recibo_sueldo("Quiero saber precios") is False

    def test_detecta_boleta(self):
        manager = self._manager()
        assert manager._detectar_recibo_sueldo("Tengo la boleta de pago") is True


# ─────────────────────────────────────────
# Tests de IntegranteCotizacion
# ─────────────────────────────────────────


class TestIntegranteCotizacion:
    def test_crear_integrante(self):
        intg = IntegranteCotizacion(nombre="Carlos", edad=40, es_titular=True)
        assert intg.nombre == "Carlos"
        assert intg.edad == 40
        assert intg.es_titular is True

    def test_integrante_no_titular(self):
        intg = IntegranteCotizacion(nombre="María", edad=35)
        assert intg.es_titular is False


# ─────────────────────────────────────────
# Tests de Construcción de Integrantes
# ─────────────────────────────────────────


class TestConstruirIntegrantes:
    def test_solo_titular(self, calculator):
        lead = Lead(
            lead_id="600",
            nombre="Carlos",
            edad=40,
            grupo_familiar=GrupoFamiliar(titular=True),
        )
        integrantes = calculator._construir_integrantes(lead)
        assert len(integrantes) == 1
        assert integrantes[0].es_titular is True
        assert integrantes[0].edad == 40

    def test_titular_conyuge(self, calculator):
        lead = Lead(
            lead_id="601",
            nombre="Ana",
            edad=30,
            grupo_familiar=GrupoFamiliar(titular=True, conyuge=True),
        )
        integrantes = calculator._construir_integrantes(lead)
        assert len(integrantes) == 2

    def test_titular_conyuge_hijos(self, calculator):
        lead = Lead(
            lead_id="602",
            nombre="Pedro",
            edad=35,
            grupo_familiar=GrupoFamiliar(titular=True, conyuge=True, hijos=True),
            cantidad_hijos=2,
        )
        integrantes = calculator._construir_integrantes(lead)
        assert len(integrantes) == 4

    def test_nombre_default(self, calculator):
        lead = Lead(lead_id="603")
        integrantes = calculator._construir_integrantes(lead)
        assert integrantes[0].nombre == "Titular"
