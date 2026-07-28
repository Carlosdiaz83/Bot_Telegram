"""
Tests Sprint 22 — Commercial Director.

Cubre:
    - CommercialDirector.decidir() con diferentes estados del Lead
    - Prioridad de datos faltantes
    - Respeta memoria (no repite datos confirmados)
    - Prohibiciones por acción
    - Integración con CommercialPromptBuilder
    - 12 escenarios del Director
"""

from __future__ import annotations

import pytest

from app.models.lead import Lead, TipoAfiliacion
from app.services.commercial_director import CommercialDirector, ObjetivoComercial
from app.services.commercial_memory import CommercialConversationContext, CommercialMemory
from app.services.session_manager import EtapaConversacion


# ─────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────

@pytest.fixture
def director():
    return CommercialDirector()


@pytest.fixture
def memoria():
    return CommercialMemory(dias_inactividad=7)


@pytest.fixture
def lead_vacio():
    return Lead(lead_id="dir_001")


@pytest.fixture
def lead_nombre():
    return Lead(lead_id="dir_002", nombre="Carlos")


@pytest.fixture
def lead_grupo():
    return Lead(lead_id="dir_003", nombre="Carlos", grupo_familiar=None)


@pytest.fixture
def lead_particular():
    return Lead(
        lead_id="dir_004", nombre="Carlos",
        tipo_afiliacion=TipoAfiliacion.PARTICULAR,
        edad=30, localidad="Córdoba",
    )


# ─────────────────────────────────────────
# Tests: Decisiones básicas
# ─────────────────────────────────────────

class TestDecisionesBasicas:
    """Tests de las decisiones fundamentales del Director."""

    def test_sin_grupo_familiar_pide_grupo(self, director, lead_nombre, memoria):
        context = memoria.get_or_create(lead_nombre.lead_id)
        objetivo = director.decidir(lead_nombre, context)
        assert objetivo.accion == "PEDIR_DATO"
        assert objetivo.dato_requerido == "grupo_familiar"

    def test_sin_tipo_afiliacion_pide_tipo(self, director, memoria):
        lead = Lead(
            lead_id="dir_010", nombre="Carlos",
        )
        lead.tipo_afiliacion = None
        context = memoria.get_or_create(lead.lead_id)
        context.confirmar_dato(
            "grupo_familiar",
            {"titular": True, "conyuge": False, "hijos": False, "cantidad": 1},
        )

        objetivo = director.decidir(lead, context)
        assert objetivo.accion == "PEDIR_DATO"
        assert objetivo.dato_requerido == "tipo_afiliacion"

    def test_particular_sin_edad_pide_edad(self, director, memoria):
        lead = Lead(
            lead_id="dir_011", nombre="Carlos",
            tipo_afiliacion=TipoAfiliacion.PARTICULAR,
            localidad="Córdoba",
        )
        context = memoria.get_or_create(lead.lead_id)
        objetivo = director.decidir(lead, context)
        assert objetivo.accion == "PEDIR_DATO"
        assert objetivo.dato_requerido == "edad"

    def test_particular_sin_localidad_pide_localidad(self, director, memoria):
        lead = Lead(
            lead_id="dir_012", nombre="Carlos",
            tipo_afiliacion=TipoAfiliacion.PARTICULAR,
            edad=30,
        )
        context = memoria.get_or_create(lead.lead_id)
        objetivo = director.decidir(lead, context)
        assert objetivo.accion == "PEDIR_DATO"
        assert objetivo.dato_requerido == "localidad"

    def test_datos_completos_cotiza(self, director, lead_particular, memoria):
        context = memoria.get_or_create(lead_particular.lead_id)
        objetivo = director.decidir(lead_particular, context)
        assert objetivo.accion == "COTIZAR"
        assert len(objetivo.todos_faltantes) == 0


# ─────────────────────────────────────────
# Tests: Datos específicos por tipo
# ─────────────────────────────────────────

class TestDatosPorTipo:
    """Tests de datos obligatorios según tipo de afiliación."""

    def test_monotributo_pide_categoria(self, director, memoria):
        lead = Lead(
            lead_id="dir_020", nombre="Carlos",
            tipo_afiliacion=TipoAfiliacion.MONOTRIBUTO,
            edad=30, localidad="Córdoba",
        )
        context = memoria.get_or_create(lead.lead_id)
        objetivo = director.decidir(lead, context)
        assert objetivo.accion == "PEDIR_DATO"
        assert objetivo.dato_requerido == "categoria_monotributo"

    def test_relacion_dependencia_pide_recibo(self, director, memoria):
        lead = Lead(
            lead_id="dir_021", nombre="Carlos",
            tipo_afiliacion=TipoAfiliacion.RELACION_DEPENDENCIA,
            edad=30, localidad="Córdoba",
        )
        context = memoria.get_or_create(lead.lead_id)
        objetivo = director.decidir(lead, context)
        assert objetivo.accion == "PEDIR_DATO"
        assert objetivo.dato_requerido == "recibo_sueldo"

    def test_relacion_dependencia_con_recibo_pide_conceptos(self, director, memoria):
        lead = Lead(
            lead_id="dir_022", nombre="Carlos",
            tipo_afiliacion=TipoAfiliacion.RELACION_DEPENDENCIA,
            edad=30, localidad="Córdoba",
            tiene_recibo_sueldo=True,
        )
        context = memoria.get_or_create(lead.lead_id)
        objetivo = director.decidir(lead, context)
        assert objetivo.accion == "PEDIR_DATO"
        assert objetivo.dato_requerido == "conceptos_obra_social"


# ─────────────────────────────────────────
# Tests: Memoria (no repetir datos)
# ─────────────────────────────────────────

class TestMemoria:
    """Tests de que el Director respeta los datos confirmados en memoria."""

    def test_no_pide_edad_si_confirmada(self, director, memoria):
        lead = Lead(
            lead_id="dir_030", nombre="Carlos",
            tipo_afiliacion=TipoAfiliacion.PARTICULAR,
            localidad="Córdoba",
        )
        context = memoria.get_or_create(lead.lead_id)
        memoria.actualizar(
            lead=lead, mensaje="Tengo 30",
            accion="PEDIR_DATO", datos_detectados={"edad": 30},
        )
        lead.edad = 30  # Sync

        objetivo = director.decidir(lead, context)
        assert objetivo.accion == "COTIZAR"

    def test_no_pide_localidad_si_confirmada(self, director, memoria):
        lead = Lead(
            lead_id="dir_031", nombre="Carlos",
            tipo_afiliacion=TipoAfiliacion.PARTICULAR,
            edad=30,
        )
        context = memoria.get_or_create(lead.lead_id)
        memoria.actualizar(
            lead=lead, mensaje="Córdoba",
            accion="PEDIR_DATO", datos_detectados={"localidad": "Córdoba"},
        )
        lead.localidad = "Córdoba"

        objetivo = director.decidir(lead, context)
        assert objetivo.accion == "COTIZAR"

    def test_no_pide_tipo_si_ya_detectado(self, director, memoria):
        lead = Lead(
            lead_id="dir_032", nombre="Carlos",
            tipo_afiliacion=TipoAfiliacion.PARTICULAR,
            edad=30, localidad="Córdoba",
        )
        context = memoria.get_or_create(lead.lead_id)
        objetivo = director.decidir(lead, context)
        assert objetivo.accion == "COTIZAR"


# ─────────────────────────────────────────
# Tests: Objeciones y cierre
# ─────────────────────────────────────────

class TestObjecionesYCierre:
    """Tests de decisiones ante objeciones y cierre."""

    def test_objecion_rebota(self, director, lead_particular, memoria):
        context = memoria.get_or_create(lead_particular.lead_id)

        class FakeInterpretacion:
            intencion = "objecion_precio"
            objecion_detectada = "precio"

        objetivo = director.decidir(lead_particular, context, FakeInterpretacion())
        assert objetivo.accion == "REBATIR_OBJECION"

    def test_cotizacion_y_cierre_cierra(self, director, lead_particular, memoria):
        context = memoria.get_or_create(lead_particular.lead_id)
        context.cotizacion_realizada = True

        class FakeInterpretacion:
            intencion = "interes_en_cierre"
            objecion_detectada = None

        objetivo = director.decidir(lead_particular, context, FakeInterpretacion())
        assert objetivo.accion == "CERRAR"

    def test_cotizacion_sin_cierre_presenta_valor(self, director, lead_particular, memoria):
        context = memoria.get_or_create(lead_particular.lead_id)
        context.cotizacion_realizada = True

        class FakeInterpretacion:
            intencion = "quiere_info"
            objecion_detectada = None

        objetivo = director.decidir(lead_particular, context, FakeInterpretacion())
        assert objetivo.accion == "PRESENTAR_VALOR"


# ─────────────────────────────────────────
# Tests: Prohibiciones
# ─────────────────────────────────────────

class TestProhibiciones:
    """Tests de que cada acción tiene las prohibiciones correctas."""

    def test_pedir_dato_prohibiciones(self, director, memoria):
        lead = Lead(
            lead_id="dir_040", nombre="Carlos",
            tipo_afiliacion=TipoAfiliacion.PARTICULAR,
            localidad="Córdoba",
        )
        context = memoria.get_or_create(lead.lead_id)
        objetivo = director.decidir(lead, context)
        assert objetivo.accion == "PEDIR_DATO"
        assert any("SERVIRED" in p for p in objetivo.prohibiciones)
        assert any("beneficios" in p for p in objetivo.prohibiciones)
        assert any("planes" in p for p in objetivo.prohibiciones)

    def test_cotizar_prohibiciones(self, director, lead_particular, memoria):
        context = memoria.get_or_create(lead_particular.lead_id)
        objetivo = director.decidir(lead_particular, context)
        assert objetivo.accion == "COTIZAR"
        assert any("datos" in p for p in objetivo.prohibiciones)

    def test_rebatir_prohibiciones(self, director, lead_particular, memoria):
        context = memoria.get_or_create(lead_particular.lead_id)

        class FakeInterpretacion:
            intencion = "objecion_precio"
            objecion_detectada = "precio"

        objetivo = director.decidir(lead_particular, context, FakeInterpretacion())
        assert objetivo.accion == "REBATIR_OBJECION"
        assert any("datos" in p for p in objetivo.prohibiciones)
        assert any("ignorar" in p.lower() or "objeción" in p for p in objetivo.prohibiciones)


# ─────────────────────────────────────────
# Tests: Orden de prioridad
# ─────────────────────────────────────────

class TestPrioridad:
    """Tests de que el Director sigue el orden de prioridad correcto."""

    def test_grupo_antes_que_tipo(self, director, memoria):
        lead = Lead(lead_id="dir_050", nombre="Carlos")
        context = memoria.get_or_create(lead.lead_id)
        objetivo = director.decidir(lead, context)
        assert objetivo.dato_requerido == "grupo_familiar"

    def test_tipo_antes_que_edad(self, director, memoria):
        lead = Lead(lead_id="dir_051", nombre="Carlos")
        context = memoria.get_or_create(lead.lead_id)
        # Confirmar grupo_familiar
        context.confirmar_dato("grupo_familiar", {"titular": True, "conyuge": False, "hijos": False, "cantidad": 1})

        objetivo = director.decidir(lead, context)
        assert objetivo.dato_requerido == "tipo_afiliacion"

    def test_edad_antes_que_localidad(self, director, memoria):
        lead = Lead(
            lead_id="dir_052", nombre="Carlos",
            tipo_afiliacion=TipoAfiliacion.PARTICULAR,
        )
        context = memoria.get_or_create(lead.lead_id)
        objetivo = director.decidir(lead, context)
        assert objetivo.dato_requerido == "edad"

    def test_localidad_ultima(self, director, memoria):
        lead = Lead(
            lead_id="dir_053", nombre="Carlos",
            tipo_afiliacion=TipoAfiliacion.PARTICULAR,
            edad=30,
        )
        context = memoria.get_or_create(lead.lead_id)
        objetivo = director.decidir(lead, context)
        assert objetivo.dato_requerido == "localidad"


# ─────────────────────────────────────────
# Tests: Integración con PromptBuilder
# ─────────────────────────────────────────

class TestIntegracionPromptBuilder:
    """Tests de que el PromptBuilder genera el prompt correcto con objetivo."""

    def test_objetivo_en_prompt(self, director, memoria):
        from app.services.commercial_prompt_builder import CommercialPromptBuilder

        lead = Lead(
            lead_id="dir_060", nombre="Carlos",
            tipo_afiliacion=TipoAfiliacion.PARTICULAR,
            localidad="Córdoba",
        )
        context = memoria.get_or_create(lead.lead_id)
        objetivo = director.decidir(lead, context)

        builder = CommercialPromptBuilder()
        messages = builder.build(
            lead=lead, historial=[], mensaje="Tengo 30",
            etapa=EtapaConversacion.ESPERANDO_DATOS,
            context=context, objetivo=objetivo,
        )

        # El prompt debe contener el objetivo obligatorio
        system_msg = messages[1]["content"]
        assert "OBJETIVO OBLIGATORIO" in system_msg
        assert "PEDIR_DATO" in system_msg
        assert "edad" in system_msg

    def test_prohibiciones_en_prompt(self, director, memoria):
        from app.services.commercial_prompt_builder import CommercialPromptBuilder

        lead = Lead(
            lead_id="dir_061", nombre="Carlos",
            tipo_afiliacion=TipoAfiliacion.PARTICULAR,
            localidad="Córdoba",
        )
        context = memoria.get_or_create(lead.lead_id)
        objetivo = director.decidir(lead, context)

        builder = CommercialPromptBuilder()
        messages = builder.build(
            lead=lead, historial=[], mensaje="Tengo 30",
            etapa=EtapaConversacion.ESPERANDO_DATOS,
            context=context, objetivo=objetivo,
        )

        system_msg = messages[1]["content"]
        assert "PROHIBICIONES" in system_msg
        assert "SERVIRED" in system_msg

    def test_cotizar_sin_prohibiciones_de_datos(self, director, lead_particular, memoria):
        from app.services.commercial_prompt_builder import CommercialPromptBuilder

        context = memoria.get_or_create(lead_particular.lead_id)
        objetivo = director.decidir(lead_particular, context)

        builder = CommercialPromptBuilder()
        messages = builder.build(
            lead=lead_particular, historial=[], mensaje="Dale",
            etapa=EtapaConversacion.ESPERANDO_DATOS,
            context=context, objetivo=objetivo,
        )

        system_msg = messages[1]["content"]
        assert "COTIZAR" in system_msg
        assert "OBJETIVO OBLIGATORIO" in system_msg


# ─────────────────────────────────────────
# Tests: Objeto ObjetivoComercial
# ─────────────────────────────────────────

class TestObjetivoComercial:
    """Tests del dataclass ObjetivoComercial."""

    def test_defaults(self):
        obj = ObjetivoComercial()
        assert obj.accion == "PEDIR_DATO"
        assert obj.dato_requerido is None
        assert len(obj.todos_faltantes) == 0
        assert len(obj.prohibiciones) == 0

    def test_with_values(self):
        obj = ObjetivoComercial(
            accion="COTIZAR",
            razon="datos completos",
            prohibiciones=["no pedir datos"],
        )
        assert obj.accion == "COTIZAR"
        assert obj.razon == "datos completos"
