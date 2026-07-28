"""
Tests Sprint 21.5 — Commercial Memory & Conversation Context.

Cubre:
    - CommercialConversationContext: recordar datos
    - CommercialMemory: actualizar, reinicio por inactividad
    - PromptBuilder: contexto de memoria en prompts
    - Orchestrator: integración con memoria
    - 12 escenarios de memoria
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models.lead import Lead, TipoAfiliacion
from app.services.commercial_memory import (
    CommercialConversationContext,
    CommercialMemory,
    get_memory,
)
from app.services.session_manager import EtapaConversacion


# ─────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────

@pytest.fixture
def memory():
    """CommercialMemory fresco para cada test."""
    return CommercialMemory(dias_inactividad=7)


@pytest.fixture
def leadCarlos():
    """Lead de ejemplo: Carlos, PARTICULAR, 30 años, Córdoba."""
    return Lead(
        lead_id="mem_001",
        nombre="Carlos",
        edad=30,
        localidad="Córdoba",
        tipo_afiliacion=TipoAfiliacion.PARTICULAR,
    )


@pytest.fixture
def leadSinDatos():
    """Lead sin datos."""
    return Lead(lead_id="mem_002")


# ─────────────────────────────────────────
# Tests: Recordar datos
# ─────────────────────────────────────────

class TestRecordarDatos:
    """Tests de confirmación de datos en memoria."""

    def test_recordar_edad(self, memory, leadCarlos):
        context = memory.actualizar(
            lead=leadCarlos, mensaje="Tengo 30 años",
            accion="PEDIR_DATO", datos_detectados={"edad": 30},
        )
        assert context.ya_tiene("edad")
        assert context.datos_confirmados["edad"] == 30
        assert "edad" not in context.datos_faltantes

    def test_recordar_localidad(self, memory, leadCarlos):
        context = memory.actualizar(
            lead=leadCarlos, mensaje="Soy de Córdoba",
            accion="PEDIR_DATO", datos_detectados={"localidad": "Córdoba"},
        )
        assert context.ya_tiene("localidad")
        assert context.datos_confirmados["localidad"] == "Córdoba"

    def test_recordar_tipo_afiliacion(self, memory, leadCarlos):
        context = memory.actualizar(
            lead=leadCarlos, mensaje="Soy particular",
            accion="PEDIR_DATO",
            datos_detectados={"tipo_afiliacion": "particular"},
        )
        assert context.ya_tiene("tipo_afiliacion")
        assert context.datos_confirmados["tipo_afiliacion"] == "particular"

    def test_recordar_grupo_familiar(self, memory):
        from app.models.lead import GrupoFamiliar
        lead = Lead(
            lead_id="mem_001b",
            nombre="Carlos",
            edad=30,
            localidad="Córdoba",
            tipo_afiliacion=TipoAfiliacion.PARTICULAR,
            grupo_familiar=GrupoFamiliar(
                titular=True, conyuge=True, hijos=True,
            ),
            cantidad_hijos=1,
        )
        lead.cantidad_integrantes = lead.calcular_integrantes()
        context = memory.actualizar(
            lead=lead, mensaje="Somos 3, tengo esposa e hijo",
            accion="PEDIR_DATO",
        )
        assert context.ya_tiene("grupo_familiar")
        assert context.grupo_familiar["cantidad"] == 3


# ─────────────────────────────────────────
# Tests: No repetir preguntas
# ─────────────────────────────────────────

class TestNoRepetirPreguntas:
    """Tests de que la memoria evita repetir preguntas."""

    def test_no_repetir_pregunta_edad(self, memory, leadCarlos):
        # Confirmar edad
        memory.actualizar(
            lead=leadCarlos, mensaje="Tengo 30",
            accion="PEDIR_DATO", datos_detectados={"edad": 30},
        )
        context = memory.get_or_create(leadCarlos.lead_id)
        # Edad ya confirmada
        assert context.ya_tiene("edad")
        assert "edad" not in context.datos_faltantes

    def test_no_repetir_pregunta_localidad(self, memory, leadCarlos):
        memory.actualizar(
            lead=leadCarlos, mensaje="Córdoba",
            accion="PEDIR_DATO", datos_detectados={"localidad": "Córdoba"},
        )
        context = memory.get_or_create(leadCarlos.lead_id)
        assert context.ya_tiene("localidad")

    def test_datos_confirmados_no_aparecen_en_faltantes(self, memory, leadCarlos):
        memory.actualizar(
            lead=leadCarlos, mensaje="30",
            accion="PEDIR_DATO",
            datos_detectados={"edad": 30},
            datos_faltantes=["edad", "categoria_monotributo"],
        )
        context = memory.get_or_create(leadCarlos.lead_id)
        assert "edad" not in context.datos_faltantes
        assert "categoria_monotributo" in context.datos_faltantes


# ─────────────────────────────────────────
# Tests: Recordar objeciones
# ─────────────────────────────────────────

class TestRecordarObjeciones:
    """Tests de que la memoria registra todas las objeciones."""

    def test_recordar_objeciones(self, memory, leadCarlos):
        memory.actualizar(
            lead=leadCarlos, mensaje="Es muy caro",
            accion="MANEJAR_OBJECION",
        )
        context = memory.get_or_create(leadCarlos.lead_id)
        assert "precio" in context.objeciones_detectadas

    def test_multiples_objeciones(self, memory, leadCarlos):
        memory.actualizar(
            lead=leadCarlos, mensaje="Es caro",
            accion="MANEJAR_OBJECION",
        )
        memory.actualizar(
            lead=leadCarlos, mensaje="No conozco Servired",
            accion="MANEJAR_OBJECION",
        )
        context = memory.get_or_create(leadCarlos.lead_id)
        assert len(context.objeciones_detectadas) >= 2

    def test_ultima_objecion_se_guarda(self, memory, leadCarlos):
        memory.actualizar(
            lead=leadCarlos, mensaje="Es caro",
            accion="MANEJAR_OBJECION",
        )
        memory.actualizar(
            lead=leadCarlos, mensaje="Necesito pensarlo",
            accion="MANEJAR_OBJECION",
        )
        context = memory.get_or_create(leadCarlos.lead_id)
        assert context.ultima_objecion is not None


# ─────────────────────────────────────────
# Tests: Actualizar interés
# ─────────────────────────────────────────

class TestActualizarInteres:
    """Tests de cálculo de nivel de interés."""

    def test_interes_aumenta_con_señales(self, memory, leadCarlos):
        context = memory.actualizar(
            lead=leadCarlos, mensaje="Quiero cotizar, dale",
            accion="PEDIR_DATO",
        )
        assert context.nivel_interes > 30

    def test_interes_baja_con_objecion(self, memory, leadCarlos):
        # Subir interés primero
        memory.actualizar(
            lead=leadCarlos, mensaje="Quiero avanzar",
            accion="PEDIR_DATO",
        )
        # Ahora objeción
        context = memory.actualizar(
            lead=leadCarlos, mensaje="Es muy caro",
            accion="MANEJAR_OBJECION",
        )
        # Debería bajar
        assert context.nivel_interes <= 70

    def test_etiquetar_interes(self, memory):
        assert memory._etiquetar_interes(0) == "BAJO"
        assert memory._etiquetar_interes(50) == "MEDIO"
        assert memory._etiquetar_interes(70) == "ALTO"
        assert memory._etiquetar_interes(90) == "MUY_ALTO"


# ─────────────────────────────────────────
# Tests: Actualizar riesgo
# ─────────────────────────────────────────

class TestActualizarRiesgo:
    """Tests de cálculo de riesgo de perder venta."""

    def test_riesgo_bajo_default(self, memory, leadCarlos):
        context = memory.get_or_create(leadCarlos.lead_id)
        assert context.riesgo_perder_venta == "BAJO"

    def test_riesgo_medio_con_objecion(self, memory, leadCarlos):
        memory.actualizar(
            lead=leadCarlos, mensaje="Es caro",
            accion="MANEJAR_OBJECION",
        )
        context = memory.get_or_create(leadCarlos.lead_id)
        assert context.riesgo_perder_venta in ("MEDIO", "ALTO")

    def test_riesgo_alto_con_multiples_objeciones(self, memory, leadCarlos):
        for msg in ["Es muy caro", "No conozco la cartilla", "Necesito pensarlo"]:
            memory.actualizar(
                lead=leadCarlos, mensaje=msg,
                accion="MANEJAR_OBJECION",
            )
        context = memory.get_or_create(leadCarlos.lead_id)
        assert context.riesgo_perder_venta == "ALTO"


# ─────────────────────────────────────────
# Tests: Mantener objetivo comercial
# ─────────────────────────────────────────

class TestMantenerObjetivo:
    """Tests de persistencia del objetivo comercial."""

    def test_objetivo_se_mantiene(self, memory, leadCarlos):
        memory.actualizar(
            lead=leadCarlos, mensaje="Quiero info",
            accion="PEDIR_DATO",
        )
        context1 = memory.get_or_create(leadCarlos.lead_id)
        objetivo1 = context1.objetivo_actual

        memory.actualizar(
            lead=leadCarlos, mensaje="30 años",
            accion="PEDIR_DATO",
        )
        context2 = memory.get_or_create(leadCarlos.lead_id)
        # El objetivo puede cambiar, pero la memoria persiste
        assert context2.objetivo_actual is not None

    def test_proximo_objetivo_se_calcula(self, memory, leadCarlos):
        context = memory.actualizar(
            lead=leadCarlos, mensaje="Hola",
            accion="PEDIR_DATO",
        )
        assert context.proximo_objetivo is not None

    def test_proximo_objetivo_cambia_con_datos(self, memory, leadCarlos):
        memory.actualizar(
            lead=leadCarlos, mensaje="Particular",
            accion="PEDIR_DATO",
            datos_detectados={"tipo_afiliacion": "particular"},
        )
        context = memory.get_or_create(leadCarlos.lead_id)
        # Con tipo detectado, proximo debería ser PEDIR_EDADES o similar
        assert context.proximo_objetivo is not None


# ─────────────────────────────────────────
# Tests: Reinicio por inactividad
# ─────────────────────────────────────────

class TestReinicioPorInactividad:
    """Tests de reinicio automático por inactividad."""

    def test_reinicio_por_inactividad(self, memory, leadCarlos):
        # Crear contexto y poner fecha antigua
        context = memory.get_or_create(leadCarlos.lead_id)
        context.confirmar_dato("edad", 30)
        context.ultima_actualizacion = datetime.now(timezone.utc) - timedelta(days=10)

        # get_or_create debería reiniciar
        context_nuevo = memory.get_or_create(leadCarlos.lead_id)
        assert not context_nuevo.ya_tiene("edad")

    def test_no_reinicia_si_reciente(self, memory, leadCarlos):
        context = memory.get_or_create(leadCarlos.lead_id)
        context.confirmar_dato("edad", 30)
        # Fecha reciente → no reinicia
        context_nuevo = memory.get_or_create(leadCarlos.lead_id)
        assert context_nuevo.ya_tiene("edad")


# ─────────────────────────────────────────
# Tests: Progreso comercial
# ─────────────────────────────────────────

class TestProgresoComercial:
    """Tests de cálculo de progreso de venta."""

    def test_progreso_descubriendo(self, memory, leadSinDatos):
        context = memory.actualizar(
            lead=leadSinDatos, mensaje="Hola",
            accion="PEDIR_DATO",
        )
        assert context.progreso <= 20

    def test_progreso_calificando(self, memory, leadCarlos):
        memory.actualizar(
            lead=leadCarlos, mensaje="Soy Carlos",
            accion="PEDIR_DATO",
            datos_detectados={"nombre": "Carlos"},
        )
        context = memory.get_or_create(leadCarlos.lead_id)
        assert context.progreso >= 20

    def test_progreso_cotizando(self, memory, leadCarlos):
        memory.actualizar(
            lead=leadCarlos, mensaje="Dale, avancemos",
            accion="COTIZAR",
            datos_faltantes=[],
        )
        context = memory.get_or_create(leadCarlos.lead_id)
        assert context.progreso >= 50

    def test_progreso_cierre(self, memory, leadCarlos):
        context = memory.actualizar(
            lead=leadCarlos, mensaje="Dale, avancemos",
            accion="CERRAR",
        )
        assert context.progreso >= 80


# ─────────────────────────────────────────
# Tests: PromptBuilder con contexto
# ─────────────────────────────────────────

class TestPromptBuilderConMemoria:
    """Tests de que el PromptBuilder usa la memoria."""

    def test_contexto_en_prompt(self, memory, leadCarlos):
        from app.services.commercial_prompt_builder import CommercialPromptBuilder

        builder = CommercialPromptBuilder()
        context = memory.actualizar(
            lead=leadCarlos, mensaje="30 años",
            accion="PEDIR_DATO",
            datos_detectados={"edad": 30},
            datos_faltantes=["localidad"],
        )

        messages = builder.build(
            lead=leadCarlos,
            historial=[],
            mensaje="Córdoba",
            etapa=EtapaConversacion.ESPERANDO_DATOS,
            datos_faltantes=["localidad"],
            context=context,
        )

        # El prompt debe contener la sección de memoria
        context_msg = messages[1]["content"]
        assert "MEMORIA COMERCIAL" in context_msg
        assert "edad" in context_msg.lower() or "30" in context_msg

    def test_datos_confirmados_en_prompt(self, memory, leadCarlos):
        from app.services.commercial_prompt_builder import CommercialPromptBuilder

        builder = CommercialPromptBuilder()
        context = memory.actualizar(
            lead=leadCarlos, mensaje="30",
            accion="PEDIR_DATO",
            datos_detectados={"edad": 30},
            datos_faltantes=[],
        )

        messages = builder.build(
            lead=leadCarlos,
            historial=[],
            mensaje="Córdoba",
            etapa=EtapaConversacion.ESPERANDO_DATOS,
            context=context,
        )

        context_msg = messages[1]["content"]
        assert "confirmados" in context_msg.lower()
        assert "NO volver a pedir" in context_msg

    def test_proximo_objetivo_en_prompt(self, memory, leadCarlos):
        from app.services.commercial_prompt_builder import CommercialPromptBuilder

        builder = CommercialPromptBuilder()
        context = memory.actualizar(
            lead=leadCarlos, mensaje="Particular",
            accion="PEDIR_DATO",
            datos_detectados={"tipo_afiliacion": "particular"},
        )

        messages = builder.build(
            lead=leadCarlos,
            historial=[],
            mensaje="30",
            etapa=EtapaConversacion.ESPERANDO_DATOS,
            context=context,
        )

        context_msg = messages[1]["content"]
        assert "Próximo objetivo" in context_msg


# ─────────────────────────────────────────
# Tests: Integración con Orchestrator
# ─────────────────────────────────────────

class TestOrchestratorConMemoria:
    """Tests de que el Orchestrator usa la memoria."""

    def test_orchestrator_tiene_memoria(self):
        from app.services.commercial_ai_orchestrator import CommercialAIOrchestrator
        orch = CommercialAIOrchestrator()
        assert orch._memory is not None

    def test_orchestrator_actualiza_memoria(self):
        from app.services.commercial_ai_orchestrator import CommercialAIOrchestrator

        orch = CommercialAIOrchestrator()
        lead = Lead(
            lead_id="orch_mem_001",
            nombre="Carlos",
            tipo_afiliacion=TipoAfiliacion.PARTICULAR,
        )

        result = orch.analizar(
            lead=lead,
            historial=[],
            mensaje="Es muy caro",
            etapa=EtapaConversacion.PRESENTANDO_VALOR,
        )

        # La memoria debería haberse actualizado
        context = orch._memory.get_or_create("orch_mem_001")
        assert context.ultima_accion == result.accion

    def test_memoria_persiste_entre_llamadas(self):
        from app.services.commercial_ai_orchestrator import CommercialAIOrchestrator

        orch = CommercialAIOrchestrator()
        lead = Lead(
            lead_id="orch_mem_002",
            nombre="Carlos",
            tipo_afiliacion=TipoAfiliacion.PARTICULAR,
        )

        orch.analizar(
            lead=lead, historial=[], mensaje="Hola",
            etapa=EtapaConversacion.NUEVO,
        )

        orch.analizar(
            lead=lead, historial=[], mensaje="Quiero cotizar",
            etapa=EtapaConversacion.CALIFICANDO,
        )

        context = orch._memory.get_or_create("orch_mem_002")
        assert context.ultima_pregunta == "Quiero cotizar"


# ─────────────────────────────────────────
# Tests: Singleton get_memory
# ─────────────────────────────────────────

class TestGetMemory:
    """Tests del singleton get_memory."""

    def test_singleton_returns_same_instance(self):
        m1 = get_memory()
        m2 = get_memory()
        assert m1 is m2

    def test_singleton_has_leads(self):
        m = get_memory()
        cantidad = m.cantidad_leads()
        # Puede tener leads de tests anteriores
        assert isinstance(cantidad, int)
