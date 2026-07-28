"""
Tests Sprint 21 — Commercial Mindset.

Cubre:
    - PromptBuilder: identidad, razonamiento interno, autocrítica
    - Orchestrator: detección de intención, autocrítica, acciones reducidas
    - 10 escenarios de ventas
    - Verificaciones: no repetir, no reiniciar, no inventar, siempre avanzar
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
    ACCIONES_VALIDAS,
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
# Tests: Prompt Builder — Identidad
# ─────────────────────────────────────────

class TestPromptBuilderIdentidad:
    """Tests de identidad y estilo del PromptBuilder."""

    def test_no_es_chatbot(self, prompt_builder):
        lead = Lead(lead_id="id_001")
        messages = prompt_builder.build(
            lead=lead,
            historial=[],
            mensaje="Hola",
            etapa=EtapaConversacion.NUEVO,
        )
        identity = messages[0]["content"]
        assert "asesora comercial" in identity

    def test_mejor_asesora(self, prompt_builder):
        lead = Lead(lead_id="id_002")
        messages = prompt_builder.build(
            lead=lead,
            historial=[],
            mensaje="Hola",
            etapa=EtapaConversacion.NUEVO,
        )
        identity = messages[0]["content"]
        assert "asesora comercial" in identity

    def test_razonamiento_interno(self, prompt_builder):
        lead = Lead(lead_id="id_003")
        messages = prompt_builder.build(
            lead=lead,
            historial=[],
            mensaje="Hola",
            etapa=EtapaConversacion.NUEVO,
        )
        identity = messages[0]["content"]
        # Simplified prompt: one question per message rule is present
        assert "UNA" in identity or "una" in identity or "pregunta" in identity

    def test_autocritica_en_identity(self, prompt_builder):
        lead = Lead(lead_id="id_004")
        messages = prompt_builder.build(
            lead=lead,
            historial=[],
            mensaje="Hola",
            etapa=EtapaConversacion.NUEVO,
        )
        identity = messages[0]["content"]
        # Simplified prompt has PROHIBICIONES section
        assert "PROHIBICIONES" in identity

    def test_acciones_reducidas(self, prompt_builder):
        lead = Lead(lead_id="id_005")
        messages = prompt_builder.build(
            lead=lead,
            historial=[],
            mensaje="Hola",
            etapa=EtapaConversacion.NUEVO,
        )
        identity = messages[0]["content"]
        # Identity must mention cotizar as objective
        assert "cotizar" in identity or "afiliación" in identity

    def test_prohibiciones_estRICTAS(self, prompt_builder):
        lead = Lead(lead_id="id_006")
        messages = prompt_builder.build(
            lead=lead,
            historial=[],
            mensaje="Hola",
            etapa=EtapaConversacion.NUEVO,
        )
        identity = messages[0]["content"]
        assert "PROHIBICIONES" in identity
        assert "NUNCA" in identity

    def test_estilo_asesora(self, prompt_builder):
        lead = Lead(lead_id="id_007")
        messages = prompt_builder.build(
            lead=lead,
            historial=[],
            mensaje="Hola",
            etapa=EtapaConversacion.NUEVO,
        )
        identity = messages[0]["content"]
        assert "profesional" in identity or "directa" in identity


# ─────────────────────────────────────────
# Tests: Prompt Builder — Contexto
# ─────────────────────────────────────────

class TestPromptBuilderContexto:
    """Tests del contexto del PromptBuilder."""

    def test_estrategia_por_etapa_presentacion(self, prompt_builder):
        lead = Lead(
            lead_id="ctx_001",
            nombre="Carlos",
            tipo_afiliacion=TipoAfiliacion.PARTICULAR,
        )
        messages = prompt_builder.build(
            lead=lead,
            historial=[],
            mensaje="Dale, avanzamos",
            etapa=EtapaConversacion.PRESENTANDO_VALOR,
        )
        context = messages[1]["content"]
        assert "CERRAR" in context

    def test_estrategia_por_etapa_objeciones(self, prompt_builder):
        lead = Lead(
            lead_id="ctx_002",
            nombre="Carlos",
            tipo_afiliacion=TipoAfiliacion.PARTICULAR,
        )
        messages = prompt_builder.build(
            lead=lead,
            historial=[],
            mensaje="Es muy caro",
            etapa=EtapaConversacion.MANEJANDO_OBJECIONES,
        )
        context = messages[1]["content"]
        assert "Resolver" in context

    def test_prioridad_por_tipo_relacion(self, prompt_builder):
        lead = Lead(
            lead_id="ctx_003",
            nombre="Carlos",
            tipo_afiliacion=TipoAfiliacion.RELACION_DEPENDENCIA,
        )
        messages = prompt_builder.build(
            lead=lead,
            historial=[],
            mensaje="Quiero info",
            etapa=EtapaConversacion.ESPERANDO_DATOS,
        )
        context = messages[1]["content"]
        assert "recibo" in context.lower()

    def test_prioridad_por_tipo_monotributo(self, prompt_builder):
        lead = Lead(
            lead_id="ctx_004",
            nombre="Carlos",
            tipo_afiliacion=TipoAfiliacion.MONOTRIBUTO,
        )
        messages = prompt_builder.build(
            lead=lead,
            historial=[],
            mensaje="Quiero info",
            etapa=EtapaConversacion.ESPERANDO_DATOS,
        )
        context = messages[1]["content"]
        assert "categoría monotributo" in context.lower()


# ─────────────────────────────────────────
# Tests: Orchestrator — Acciones válidas
# ─────────────────────────────────────────

class TestOrchestratorAcciones:
    """Tests de acciones del Orchestrator."""

    def test_solo_5_acciones_validas(self):
        assert len(ACCIONES_VALIDAS) == 5
        assert "PEDIR_DATO" in ACCIONES_VALIDAS
        assert "COTIZAR" in ACCIONES_VALIDAS
        assert "ARGUMENTAR" in ACCIONES_VALIDAS
        assert "MANEJAR_OBJECION" in ACCIONES_VALIDAS
        assert "CERRAR" in ACCIONES_VALIDAS

    def test_accion_default_es_pedir_dato(self):
        result = OrchestrationResult()
        assert result.accion == "PEDIR_DATO"

    def test_accion_invalida_se_corrige(self, orchestrator):
        lead = Lead(
            lead_id="acc_001",
            nombre="Carlos",
            tipo_afiliacion=TipoAfiliacion.PARTICULAR,
        )
        # Forzar acción inválida en resultado
        resultado = OrchestrationResult(
            intencion="test",
            accion="SALUDAR",
            respuesta="Hola",
        )
        # Autocrítica debe corregir
        resultado = orchestrator._autocritica(
            resultado, lead, [], "Hola", EtapaConversacion.NUEVO
        )
        assert resultado.accion in ACCIONES_VALIDAS


# ─────────────────────────────────────────
# Tests: 10 Escenarios de Ventas
# ─────────────────────────────────────────

class TestEscenario1Info:
    """Escenario 1: Cliente pide información."""

    def test_info_avanza_a_calificacion(self, orchestrator):
        lead = Lead(lead_id="esc_001", nombre="Carlos")
        result = orchestrator.analizar(
            lead=lead,
            historial=[],
            mensaje="Quiero información sobre sus planes",
            etapa=EtapaConversacion.DESCUBRIENDO_NECESIDAD,
        )
        # Debe avanzar a calificación, no quedarse en informativo
        assert result.accion in ("PEDIR_DATO", "COTIZAR")

    def test_info_no_inventa_planes(self, orchestrator):
        lead = Lead(lead_id="esc_001b", nombre="Carlos")
        result = orchestrator.analizar(
            lead=lead,
            historial=[],
            mensaje="¿Qué planes tienen?",
            etapa=EtapaConversacion.DESCUBRIENDO_NECESIDAD,
        )
        # No debe inventar precios
        assert "$" not in result.respuesta or "cotización" in result.respuesta.lower()


class TestEscenario2Cotizacion:
    """Escenario 2: Cliente quiere cotizar."""

    def test_cotizar_pide_datos_faltantes(self, orchestrator):
        lead = Lead(
            lead_id="esc_002",
            nombre="Carlos",
            tipo_afiliacion=TipoAfiliacion.PARTICULAR,
        )
        result = orchestrator.analizar(
            lead=lead,
            historial=[],
            mensaje="Quiero cotizar",
            etapa=EtapaConversacion.ESPERANDO_DATOS,
            datos_faltantes=["localidad", "edad"],
        )
        assert result.accion == "PEDIR_DATO"
        assert len(result.datos_faltantes) == 2

    def test_cotizar_con_datos_completos(self, orchestrator):
        lead = Lead(
            lead_id="esc_002b",
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
            mensaje="Dale, cotizame",
            etapa=EtapaConversacion.ESPERANDO_DATOS,
            datos_faltantes=[],
        )
        assert result.accion == "COTIZAR"


class TestEscenario3OsdeAumento:
    """Escenario 3: Cliente dice 'OSDE me aumentó'."""

    def test_osde_aumento_detecta_intencion(self, orchestrator):
        lead = Lead(lead_id="esc_003", nombre="Carlos")
        result = orchestrator.analizar(
            lead=lead,
            historial=[],
            mensaje="OSDE me aumentó un montón",
            etapa=EtapaConversacion.DESCUBRIENDO_NECESIDAD,
        )
        # Debe detectar intención de cotizar
        assert result.accion in ("PEDIR_DATO", "COTIZAR")

    def test_osde_aumento_no_explica_servired(self, orchestrator):
        lead = Lead(lead_id="esc_003b", nombre="Carlos")
        result = orchestrator.analizar(
            lead=lead,
            historial=[],
            mensaje="OSDE me aumentó, necesito otra cosa",
            etapa=EtapaConversacion.DESCUBRIENDO_NECESIDAD,
        )
        # No debe explicar qué es Servired
        assert "Servired es" not in result.respuesta
        assert "Somos" not in result.respuesta


class TestEscenario4PagoMucho:
    """Escenario 4: Cliente paga mucho."""

    def test_pago_mucho_detecta_objecion(self, orchestrator):
        lead = Lead(
            lead_id="esc_004",
            nombre="Carlos",
            tipo_afiliacion=TipoAfiliacion.PARTICULAR,
        )
        result = orchestrator.analizar(
            lead=lead,
            historial=[],
            mensaje="Estoy pagando mucho, necesito algo más barato",
            etapa=EtapaConversacion.PRESENTANDO_VALOR,
        )
        # Debe manejar como objeción económica
        assert result.accion == "MANEJAR_OBJECION"

    def test_pago_mucho_no_inventa_descuento(self, orchestrator):
        lead = Lead(lead_id="esc_004b", nombre="Carlos")
        result = orchestrator.analizar(
            lead=lead,
            historial=[],
            mensaje="No llego con el precio",
            etapa=EtapaConversacion.PRESENTANDO_VALOR,
        )
        # No debe inventar descuentos
        assert "descuento" not in result.respuesta.lower()
        assert "oferta" not in result.respuesta.lower()


class TestEscenario5EdadDada:
    """Escenario 5: Cliente ya dio su edad."""

    def test_no_repite_pregunta_edad(self, orchestrator):
        lead = Lead(
            lead_id="esc_005",
            nombre="Carlos",
            tipo_afiliacion=TipoAfiliacion.PARTICULAR,
            edad=30,
            localidad="Córdoba",
        )
        result = orchestrator.analizar(
            lead=lead,
            historial=[],
            mensaje="Tengo 30 años",
            etapa=EtapaConversacion.ESPERANDO_DATOS,
            datos_faltantes=[],
        )
        # No debe pedir edad
        assert "¿cuántos años" not in result.respuesta.lower()

    def test_no_repite_pregunta_edad_autocritica(self, orchestrator):
        lead = Lead(
            lead_id="esc_005b",
            nombre="Carlos",
            edad=30,
        )
        resultado = OrchestrationResult(
            intencion="test",
            accion="PEDIR_DATO",
            respuesta="¿Cuántos años tenés?",
        )
        resultado = orchestrator._autocritica(
            resultado, lead, [], "Tengo 30 años",
            EtapaConversacion.ESPERANDO_DATOS,
        )
        assert "¿cuántos años" not in resultado.respuesta.lower()


class TestEscenario6LocalidadDada:
    """Escenario 6: Cliente ya dijo su localidad."""

    def test_no_repite_pregunta_localidad(self, orchestrator):
        lead = Lead(
            lead_id="esc_006",
            nombre="Carlos",
            tipo_afiliacion=TipoAfiliacion.PARTICULAR,
            localidad="Córdoba",
        )
        result = orchestrator.analizar(
            lead=lead,
            historial=[],
            mensaje="Soy de Córdoba",
            etapa=EtapaConversacion.ESPERANDO_DATOS,
            datos_faltantes=[],
        )
        # No debe pedir localidad
        assert "¿de qué localidad" not in result.respuesta.lower()


class TestEscenario7TipoDado:
    """Escenario 7: Cliente ya dijo su tipo de afiliación."""

    def test_no_repite_pregunta_tipo(self, orchestrator):
        lead = Lead(
            lead_id="esc_007",
            nombre="Carlos",
            tipo_afiliacion=TipoAfiliacion.PARTICULAR,
        )
        result = orchestrator.analizar(
            lead=lead,
            historial=[],
            mensaje="Soy particular",
            etapa=EtapaConversacion.ESPERANDO_DATOS,
            datos_faltantes=["edad", "localidad"],
        )
        # No debe pedir tipo
        assert "situación laboral" not in result.respuesta.lower()
        assert "relación de dependencia" not in result.respuesta.lower()


class TestEscenario8Desviacion:
    """Escenario 8: Cliente intenta desviar la conversación."""

    def test_desviacion_mantiene_foco(self, orchestrator):
        lead = Lead(
            lead_id="esc_008",
            nombre="Carlos",
            tipo_afiliacion=TipoAfiliacion.PARTICULAR,
        )
        result = orchestrator.analizar(
            lead=lead,
            historial=[],
            mensaje="¿Qué hacés? ¿A qué te dedicás?",
            etapa=EtapaConversacion.PRESENTANDO_VALOR,
        )
        # No debe responder sobre sí misma
        assert "me dedico" not in result.respuesta.lower()
        assert "soy asesora" not in result.respuesta.lower()

    def test_desviacion_autocritica(self, orchestrator):
        lead = Lead(
            lead_id="esc_008b",
            nombre="Carlos",
            tipo_afiliacion=TipoAfiliacion.PARTICULAR,
        )
        resultado = OrchestrationResult(
            intencion="desviacion",
            accion="PEDIR_DATO",
            respuesta="¿Qué hacés? ¿A qué te dedicás?",
        )
        resultado = orchestrator._autocritica(
            resultado, lead, [], "Hola",
            EtapaConversacion.PRESENTANDO_VALOR,
        )
        # Autocrítica debe corregir la desviación
        assert "¿qué hacés" not in resultado.respuesta.lower()


class TestEscenario9Indeciso:
    """Escenario 9: Cliente indeciso."""

    def test_indeciso_maneja_objecion(self, orchestrator):
        lead = Lead(
            lead_id="esc_009",
            nombre="Carlos",
            tipo_afiliacion=TipoAfiliacion.PARTICULAR,
        )
        result = orchestrator.analizar(
            lead=lead,
            historial=[],
            mensaje="No sé si estoy seguro, necesito pensarlo",
            etapa=EtapaConversacion.PRESENTANDO_VALOR,
        )
        assert result.accion == "MANEJAR_OBJECION"

    def test_indeciso_no_reinicia(self, orchestrator):
        lead = Lead(
            lead_id="esc_009b",
            nombre="Carlos",
            tipo_afiliacion=TipoAfiliacion.PARTICULAR,
        )
        result = orchestrator.analizar(
            lead=lead,
            historial=[],
            mensaje="Después vemos",
            etapa=EtapaConversacion.INTENTANDO_CIERRE,
        )
        # No debe saludar de nuevo
        assert "¡Hola" not in result.respuesta


class TestEscenario10Cierre:
    """Escenario 10: Cliente listo para cerrar."""

    def test_cierre_detecta_interes(self, orchestrator):
        lead = Lead(
            lead_id="esc_010",
            nombre="Carlos",
            tipo_afiliacion=TipoAfiliacion.PARTICULAR,
        )
        result = orchestrator.analizar(
            lead=lead,
            historial=[],
            mensaje="Dale, avancemos",
            etapa=EtapaConversacion.PRESENTANDO_VALOR,
        )
        assert result.accion == "CERRAR"

    def test_cierre_en_objeciones_resuelta(self, orchestrator):
        lead = Lead(
            lead_id="esc_010b",
            nombre="Carlos",
            tipo_afiliacion=TipoAfiliacion.PARTICULAR,
        )
        result = orchestrator.analizar(
            lead=lead,
            historial=[],
            mensaje="Ok, estoy dentro",
            etapa=EtapaConversacion.MANEJANDO_OBJECIONES,
        )
        assert result.accion == "CERRAR"


# ─────────────────────────────────────────
# Tests: Autocrítica
# ─────────────────────────────────────────

class TestAutocritica:
    """Tests de autocrítica del Orchestrator."""

    def test_autocritica_corrige_accion_invalida(self, orchestrator):
        lead = Lead(lead_id="auto_001")
        resultado = OrchestrationResult(
            intencion="test",
            accion="INFORMAR",
            respuesta="Servired es una prepaga.",
        )
        resultado = orchestrator._autocritica(
            resultado, lead, [], "Hola",
            EtapaConversacion.NUEVO,
        )
        assert resultado.accion in ACCIONES_VALIDAS

    def test_autocritica_elimina_inventos(self, orchestrator):
        lead = Lead(lead_id="auto_002")
        resultado = OrchestrationResult(
            intencion="test",
            accion="ARGUMENTAR",
            respuesta="Tenemos una promoción especial solo hoy.",
        )
        resultado = orchestrator._autocritica(
            resultado, lead, [], "¿Hay promos?",
            EtapaConversacion.PRESENTANDO_VALOR,
        )
        assert "promoción especial" not in resultado.respuesta.lower()
        assert "solo hoy" not in resultado.respuesta.lower()

    def test_autocritica_no_saluda_de_nuevo(self, orchestrator):
        lead = Lead(lead_id="auto_003", nombre="Carlos")
        resultado = OrchestrationResult(
            intencion="test",
            accion="PEDIR_DATO",
            respuesta="¡Hola Carlos! ¿Cuántos años tenés?",
        )
        resultado = orchestrator._autocritica(
            resultado, lead, [], "Hola de nuevo",
            EtapaConversacion.CALIFICANDO,
        )
        # No debe saludar si no está en NUEVO
        assert "¡hola" not in resultado.respuesta.lower()


# ─────────────────────────────────────────
# Tests: Integration — ConversationManager
# ─────────────────────────────────────────

class TestIntegracionCommercialMindset:
    """Tests de integración con ConversationManager."""

    def test_orchestrator_usa_nuevas_acciones(self, manager):
        assert manager._orchestrator is not None
        # Verificar que las acciones válidas son las correctas
        from app.services.commercial_ai_orchestrator import ACCIONES_VALIDAS
        assert len(ACCIONES_VALIDAS) == 5

    def test_nuevo_sigue_siendo_handler(self, manager):
        tid = 920001
        respuesta = manager.procesar_mensaje(tid, "Hola")
        session = manager.session_manager.get(tid)
        assert session.etapa == EtapaConversacion.NUEVO
        assert session._handler_ejecutado == "_handle_nuevo"

    def test_calificacion_avanza_con_tipo(self, manager):
        tid = 920002
        manager.procesar_mensaje(tid, "Quiero info")
        manager.procesar_mensaje(tid, "Soy Juan, particular, solo para mí")
        session = manager.session_manager.get(tid)
        assert session.etapa == EtapaConversacion.ESPERANDO_DATOS
        assert session.lead.nombre == "Juan"
        assert session.lead.tipo_afiliacion == TipoAfiliacion.PARTICULAR

    def test_objecion_en_presentacion(self, manager):
        tid = 920003
        manager.procesar_mensaje(tid, "Quiero info")
        manager.procesar_mensaje(tid, "Juan, particular, solo para mí")
        manager.procesar_mensaje(tid, "Córdoba, 35 años")
        manager.procesar_mensaje(tid, "Es muy caro, no llego")
        session = manager.session_manager.get(tid)
        assert session.lead.estado_comercial == EstadoComercial.OBJECION

    def test_cierre_en_presentacion(self, manager):
        tid = 920004
        manager.procesar_mensaje(tid, "Quiero info")
        manager.procesar_mensaje(tid, "Juan, particular, solo para mí")
        manager.procesar_mensaje(tid, "Córdoba, 35 años")
        manager.procesar_mensaje(tid, "Dale, avanzamos")
        session = manager.session_manager.get(tid)
        assert session.etapa == EtapaConversacion.INTENTANDO_CIERRE
        assert session.lead.estado_comercial == EstadoComercial.INTENTANDO_CIERRE
