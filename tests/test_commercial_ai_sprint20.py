"""
Tests Sprint 20 — Commercial AI Orchestrator.

Cubre:
    - Orchestrator: razonamiento basado en reglas (sin IA)
    - Prompt Builder: construcción de prompts
    - Detección de intención (calcular, argumentar, objeción, cierre)
    - Selección correcta de acciones
    - Sin preguntas repetidas
    - Sin saludos repetidos
    - Uso de historial para contexto
    - Extracción de datos faltantes
    - Integración con ConversationManager
    - Flujo completo con orchestrator
"""

from __future__ import annotations

import pytest

from app.models.lead import (
    EstadoComercial,
    InteresDetectado,
    Lead,
    TipoAfiliacion,
)
from app.services.session_manager import (
    EtapaConversacion,
    SessionManager,
    UserSession,
)
from app.services.conversation_manager import ConversationManager
from app.services.commercial_ai_orchestrator import (
    CommercialAIOrchestrator,
    OrchestrationResult,
)
from app.services.commercial_prompt_builder import CommercialPromptBuilder


# ─────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────

@pytest.fixture
def manager():
    """ConversationManager sin DB ni IA."""
    return ConversationManager(ai_service=None, database_url=None)


@pytest.fixture
def orchestrator():
    """Orchestrator sin IA ni knowledge."""
    return CommercialAIOrchestrator(
        ai_service=None,
        knowledge_engine=None,
        knowledge_service=None,
    )


@pytest.fixture
def prompt_builder():
    """Prompt Builder."""
    return CommercialPromptBuilder()


# ─────────────────────────────────────────
# Tests: Prompt Builder
# ─────────────────────────────────────────

class TestPromptBuilder:
    """Tests del CommercialPromptBuilder."""

    def test_build_returns_list_of_messages(self, prompt_builder):
        lead = Lead(lead_id="pb_001", nombre="Carlos", tipo_afiliacion=TipoAfiliacion.PARTICULAR)

        messages = prompt_builder.build(
            lead=lead,
            historial=[],
            mensaje="Hola",
            etapa=EtapaConversacion.NUEVO,
            knowledge="",
            datos_faltantes=["localidad"],
        )

        assert isinstance(messages, list)
        assert len(messages) >= 3

    def test_system_messages_are_system_role(self, prompt_builder):
        lead = Lead(lead_id="pb_002")
        messages = prompt_builder.build(
            lead=lead,
            historial=[],
            mensaje="Hola",
            etapa=EtapaConversacion.NUEVO,
        )

        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "system"

    def test_user_message_is_last(self, prompt_builder):
        lead = Lead(lead_id="pb_003")
        messages = prompt_builder.build(
            lead=lead,
            historial=[{"role": "user", "content": "Anterior"}],
            mensaje="Actual",
            etapa=EtapaConversacion.CALIFICANDO,
        )

        assert messages[-1]["role"] == "user"
        assert messages[-1]["content"] == "Actual"

    def test_historial_included(self, prompt_builder):
        lead = Lead(lead_id="pb_004")
        messages = prompt_builder.build(
            lead=lead,
            historial=[
                {"role": "user", "content": "Hola"},
                {"role": "assistant", "content": "Hola!"},
            ],
            mensaje="Quiero info",
            etapa=EtapaConversacion.CALIFICANDO,
        )

        user_messages = [m for m in messages if m["role"] == "user"]
        assert len(user_messages) == 2

    def test_datos_faltantes_in_context(self, prompt_builder):
        lead = Lead(lead_id="pb_005", localidad="Córdoba")
        messages = prompt_builder.build(
            lead=lead,
            historial=[],
            mensaje="Hola",
            etapa=EtapaConversacion.ESPERANDO_DATOS,
            datos_faltantes=["edad"],
        )

        context = messages[1]["content"]
        assert "edad" in context.lower()

    def test_knowledge_in_context(self, prompt_builder):
        lead = Lead(lead_id="pb_006")
        messages = prompt_builder.build(
            lead=lead,
            historial=[],
            mensaje="¿Qué planes tienen?",
            etapa=EtapaConversacion.CALIFICANDO,
            knowledge="Planes Medimax, Gold, CO",
        )

        context = messages[1]["content"]
        assert "Medimax" in context

    def test_etapa_instructions_present(self, prompt_builder):
        lead = Lead(lead_id="pb_007", tipo_afiliacion=TipoAfiliacion.PARTICULAR)

        messages = prompt_builder.build(
            lead=lead,
            historial=[],
            mensaje="Hola",
            etapa=EtapaConversacion.CALIFICANDO,
        )

        context = messages[1]["content"]
        assert "INSTRUCCIONES" in context

    def test_lead_data_formatted(self, prompt_builder):
        lead = Lead(lead_id="pb_008", nombre="Pedro", edad=30, localidad="Córdoba")

        messages = prompt_builder.build(
            lead=lead,
            historial=[],
            mensaje="Hola",
            etapa=EtapaConversacion.NUEVO,
        )

        context = messages[1]["content"]
        assert "Pedro" in context
        assert "30" in context
        assert "Córdoba" in context


# ─────────────────────────────────────────
# Tests: Orchestrator (reglas)
# ─────────────────────────────────────────

class TestOrchestratorReglas:
    """Tests del CommercialAIOrchestrator con razonamiento basado en reglas."""

    def test_nuevo_contacto_sin_nombre(self, orchestrator):
        lead = Lead(lead_id="orch_001")
        result = orchestrator.analizar(
            lead=lead,
            historial=[],
            mensaje="Hola",
            etapa=EtapaConversacion.NUEVO,
        )

        assert result.accion == "SALUDAR"
        assert "¿Cómo te llamás?" in result.respuesta

    def test_nuevo_contacto_con_nombre(self, orchestrator):
        lead = Lead(lead_id="orch_002", nombre="Carlos")
        result = orchestrator.analizar(
            lead=lead,
            historial=[],
            mensaje="Hola",
            etapa=EtapaConversacion.NUEVO,
        )

        assert result.accion == "SALUDAR"
        assert "Carlos" in result.respuesta

    def test_datos_faltantes_pide_dato(self, orchestrator):
        lead = Lead(lead_id="orch_003", nombre="Carlos")
        result = orchestrator.analizar(
            lead=lead,
            historial=[],
            mensaje="Quiero cotizar",
            etapa=EtapaConversacion.ESPERANDO_DATOS,
            datos_faltantes=["localidad", "edad"],
        )

        assert result.accion == "PEDIR_DATO"
        assert result.datos_faltantes == ["localidad", "edad"]

    def test_objecion_detectada(self, orchestrator):
        lead = Lead(
            lead_id="orch_004",
            nombre="Carlos",
            tipo_afiliacion=TipoAfiliacion.PARTICULAR,
        )
        result = orchestrator.analizar(
            lead=lead,
            historial=[],
            mensaje="Es muy caro, no llego",
            etapa=EtapaConversacion.PRESENTANDO_VALOR,
        )

        assert result.accion == "MANEJAR_OBJECION"

    def test_cierre_detectado(self, orchestrator):
        lead = Lead(
            lead_id="orch_005",
            nombre="Carlos",
            tipo_afiliacion=TipoAfiliacion.PARTICULAR,
        )
        result = orchestrator.analizar(
            lead=lead,
            historial=[],
            mensaje="Dale, avanzamos",
            etapa=EtapaConversacion.PRESENTANDO_VALOR,
        )

        assert result.accion == "CERRAR"

    def test_datos_completos_calcular(self, orchestrator):
        lead = Lead(
            lead_id="orch_006",
            nombre="Carlos",
            tipo_afiliacion=TipoAfiliacion.PARTICULAR,
            localidad="Córdoba",
            edad=30,
        )
        lead.grupo_familiar.conyuge = False
        lead.grupo_familiar.hijos = False

        result = orchestrator.analizar(
            lead=lead,
            historial=[],
            mensaje="Contame los precios",
            etapa=EtapaConversacion.COTIZANDO,
            datos_faltantes=[],
        )

        assert result.accion == "CALCULAR"

    def test_default_informar(self, orchestrator):
        lead = Lead(lead_id="orch_007", nombre="Carlos")
        result = orchestrator.analizar(
            lead=lead,
            historial=[],
            mensaje="¿Qué es Servired?",
            etapa=EtapaConversacion.DESCUBRIENDO_NECESIDAD,
        )

        assert result.accion == "INFORMAR"

    def test_respuesta_no_vacia(self, orchestrator):
        lead = Lead(lead_id="orch_008", nombre="Carlos")
        result = orchestrator.analizar(
            lead=lead,
            historial=[],
            mensaje="Hola",
            etapa=EtapaConversacion.NUEVO,
        )

        assert result.respuesta
        assert len(result.respuesta) > 0


# ─────────────────────────────────────────
# Tests: Orchestrator — Sin preguntas repetidas
# ─────────────────────────────────────────

class TestSinPreguntasRepetidas:
    """Tests para verificar que el Orchestrator no repite preguntas."""

    def test_no_repite_pregunta_nombre(self, orchestrator):
        lead = Lead(lead_id="rep_001", nombre="Carlos")
        result = orchestrator.analizar(
            lead=lead,
            historial=[{"role": "user", "content": "Carlos"}],
            mensaje="Hola, soy Carlos",
            etapa=EtapaConversacion.NUEVO,
        )

        assert "¿Cómo te llamás?" not in result.respuesta

    def test_no_repite_pregunta_tipo_afiliacion(self, orchestrator):
        lead = Lead(
            lead_id="rep_002",
            nombre="Carlos",
            tipo_afiliacion=TipoAfiliacion.PARTICULAR,
        )
        result = orchestrator.analizar(
            lead=lead,
            historial=[{"role": "user", "content": "Soy particular"}],
            mensaje="Ya te dije que soy particular",
            etapa=EtapaConversacion.CALIFICANDO,
        )

        assert "¿Cómo es tu situación laboral" not in result.respuesta


# ─────────────────────────────────────────
# Tests: Orchestrator — Sin saludos repetidos
# ─────────────────────────────────────────

class TestSinSaludosRepetidos:
    """Tests para verificar que el Orchestrator no repite saludos."""

    def test_no_repite_saludo(self, orchestrator):
        lead = Lead(lead_id="sal_001", nombre="Carlos")
        result = orchestrator.analizar(
            lead=lead,
            historial=[
                {"role": "assistant", "content": "¡Hola Carlos! Soy Sofía"},
            ],
            mensaje="Hola de nuevo",
            etapa=EtapaConversacion.CALIFICANDO,
        )

        # No debe saludar de nuevo si ya se saludó
        assert not (result.accion == "SALUDAR" and "Hola" in result.respuesta)


# ─────────────────────────────────────────
# Tests: Orchestrator — Uso de historial
# ─────────────────────────────────────────

class TestUsoHistorial:
    """Tests para verificar que el Orchestrator usa el historial."""

    def test_historial_incluido_en_prompt(self, orchestrator):
        lead = Lead(
            lead_id="hist_001",
            nombre="Carlos",
            tipo_afiliacion=TipoAfiliacion.PARTICULAR,
            localidad="Córdoba",
            edad=30,
        )

        historial = [
            {"role": "user", "content": "Hola, soy Carlos"},
            {"role": "assistant", "content": "¡Hola Carlos! ¿Cómo te puedo ayudar?"},
            {"role": "user", "content": "Soy particular, solo para mí"},
            {"role": "assistant", "content": "Perfecto, ¿de qué localidad sos?"},
        ]

        result = orchestrator.analizar(
            lead=lead,
            historial=historial,
            mensaje="Córdoba, 30 años",
            etapa=EtapaConversacion.ESPERANDO_DATOS,
        )

        assert result.respuesta


# ─────────────────────────────────────────
# Tests: Orchestrator — Extracción datos faltantes
# ─────────────────────────────────────────

class TestExtraccionDatosFaltantes:
    """Tests para verificar que el Orchestrator maneja datos faltantes correctamente."""

    def test_un_solo_dato_faltante(self, orchestrator):
        lead = Lead(
            lead_id="falt_001",
            nombre="Carlos",
            tipo_afiliacion=TipoAfiliacion.PARTICULAR,
            localidad="Córdoba",
        )

        result = orchestrator.analizar(
            lead=lead,
            historial=[],
            mensaje="Córdoba",
            etapa=EtapaConversacion.ESPERANDO_DATOS,
            datos_faltantes=["edad"],
        )

        assert result.accion == "PEDIR_DATO"
        assert "edad" in result.datos_faltantes

    def testMultiplesDatosFaltantes(self, orchestrator):
        lead = Lead(
            lead_id="falt_002",
            nombre="Carlos",
            tipo_afiliacion=TipoAfiliacion.MONOTRIBUTO,
        )

        result = orchestrator.analizar(
            lead=lead,
            historial=[],
            mensaje="Quiero cotizar",
            etapa=EtapaConversacion.ESPERANDO_DATOS,
            datos_faltantes=["localidad", "edad", "categoría de monotributo"],
        )

        assert result.accion == "PEDIR_DATO"
        assert len(result.datos_faltantes) == 3


# ─────────────────────────────────────────
# Tests: Integration — ConversationManager + Orchestrator
# ─────────────────────────────────────────

class TestIntegracionOrchestrator:
    """Tests de integración: ConversationManager usa el Orchestrator."""

    def test_orchestrator_created(self, manager):
        assert manager._orchestrator is not None
        assert isinstance(manager._orchestrator, CommercialAIOrchestrator)

    def test_nuevo_usa_handler_tradicional(self, manager):
        tid = 900001
        respuesta = manager.procesar_mensaje(tid, "Hola")
        session = manager.session_manager.get(tid)

        assert session.etapa == EtapaConversacion.NUEVO
        assert session._handler_ejecutado == "_handle_nuevo"
        assert "¿Cómo te llamás?" in respuesta

    def test_returning_usa_handler_tradicional(self, manager):
        tid = 900002
        manager.procesar_mensaje(tid, "Hola")
        manager.procesar_mensaje(tid, "Carlos")
        manager.procesar_mensaje(tid, "Quiero info")
        manager.procesar_mensaje(tid, "Particular")
        manager.procesar_mensaje(tid, "Córdoba, 30 años")
        session_before = manager.session_manager.get(tid)
        etapa_before = session_before.etapa

        # Same manager instance — session persists in memory
        respuesta = manager.procesar_mensaje(tid, "Hola de nuevo")
        session = manager.session_manager.get(tid)

        # Session should NOT be reset to NUEVO
        assert session.etapa == etapa_before
        assert session._handler_ejecutado != "_handle_nuevo"

    def test_orchestrator_runs_for_non_nuevo(self, manager):
        tid = 900003
        manager.procesar_mensaje(tid, "Quiero info")
        respuesta = manager.procesar_mensaje(tid, "Es muy caro")
        session = manager.session_manager.get(tid)

        assert session.etapa == EtapaConversacion.MANEJANDO_OBJECIONES
        assert session.lead.estado_comercial == EstadoComercial.OBJECION


# ─────────────────────────────────────────
# Tests: Integration — Flujo completo con Orchestrator
# ─────────────────────────────────────────

class TestFlujoCompletoOrchestrator:
    """Tests de flujo completo usando el Orchestrator."""

    def test_flujo_completo_calificar(self, manager):
        tid = 910001

        r1 = manager.procesar_mensaje(tid, "Quiero cotización")
        s = manager.session_manager.get(tid)
        assert s.etapa == EtapaConversacion.CALIFICANDO

    def test_flujo_completo_esperando_datos(self, manager):
        tid = 910002

        manager.procesar_mensaje(tid, "Quiero info")
        r2 = manager.procesar_mensaje(tid, "Soy Juan, particular, solo para mí")
        s = manager.session_manager.get(tid)
        assert s.etapa == EtapaConversacion.ESPERANDO_DATOS
        assert s.lead.nombre == "Juan"
        assert s.lead.tipo_afiliacion == TipoAfiliacion.PARTICULAR

    def test_flujo_completo_hasta_cotizar(self, manager):
        tid = 910003

        manager.procesar_mensaje(tid, "Quiero info")
        manager.procesar_mensaje(tid, "Soy Juan, particular, solo para mí")
        r3 = manager.procesar_mensaje(tid, "Córdoba, 35 años")
        s = manager.session_manager.get(tid)
        assert s.etapa == EtapaConversacion.PRESENTANDO_VALOR

    def test_objecion_en_presentacion(self, manager):
        tid = 910004

        manager.procesar_mensaje(tid, "Quiero info")
        manager.procesar_mensaje(tid, "Soy Juan, particular, solo para mí")
        manager.procesar_mensaje(tid, "Córdoba, 35 años")

        respuesta_objecion = manager.procesar_mensaje(tid, "Es muy caro, no llego")
        s = manager.session_manager.get(tid)
        # Orchestrator logs the objection, handler executes the state change
        assert s.lead.estado_comercial == EstadoComercial.OBJECION

    def test_cierre_en_presentacion(self, manager):
        tid = 910005

        manager.procesar_mensaje(tid, "Quiero info")
        manager.procesar_mensaje(tid, "Soy Juan, particular, solo para mí")
        manager.procesar_mensaje(tid, "Córdoba, 35 años")

        respuesta_cierre = manager.procesar_mensaje(tid, "Dale, avanzamos")
        s = manager.session_manager.get(tid)
        assert s.etapa == EtapaConversacion.INTENTANDO_CIERRE
        assert s.lead.estado_comercial == EstadoComercial.INTENTANDO_CIERRE


# ─────────────────────────────────────────
# Tests: OrchestrationResult
# ─────────────────────────────────────────

class TestOrchestrationResult:
    """Tests del dataclass OrchestrationResult."""

    def test_default_values(self):
        result = OrchestrationResult()
        assert result.intencion == ""
        assert result.datos_detectados == {}
        assert result.datos_faltantes == []
        assert result.accion == "INFORMAR"
        assert result.argumento == ""
        assert result.tono == "friendly"
        assert result.respuesta == ""

    def test_custom_values(self):
        result = OrchestrationResult(
            intencion="interes_detectado",
            datos_detectados={"nombre": "Carlos"},
            datos_faltantes=["localidad"],
            accion="PEDIR_DATO",
            argumento="urgente",
            tono="empathetic",
            respuesta="¿De qué localidad sos?",
        )
        assert result.intencion == "interes_detectado"
        assert result.datos_detectados["nombre"] == "Carlos"
        assert result.datos_faltantes == ["localidad"]
        assert result.accion == "PEDIR_DATO"
        assert result.argumento == "urgente"
        assert result.tono == "empathetic"
        assert result.respuesta == "¿De qué localidad sos?"
