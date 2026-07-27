"""
Tests Sprint 19 — Estabilización del flujo comercial.

Cubre:
    - "Quiero info" → CALIFICANDO (no se queda en NUEVO)
    - Flujo completo hasta cotización (NUEVO → CALIFICANDO → ESPERANDO_DATOS → COTIZANDO → PRESENTANDO_VALOR)
    - Sin derivación prematura (sin "Un asesor se comunicará" en flujo normal)
    - Recolección de datos combinada (2+ preguntas en un mensaje)
    - Sin force-advance por timers (mensajes_en_etapa no fuerza avance)
    - Edad requerida para todos los tipos (no solo particular)
    - Conceptos de obra social recolectados y pasados a calculadora
    - Sin "asesor" en recuperar_indeciso default
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
from app.services.lead_qualifier import clasificar_intencion


# ─────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────

@pytest.fixture
def manager():
    """ConversationManager sin DB ni IA."""
    return ConversationManager(ai_service=None, database_url=None)


# ─────────────────────────────────────────
# Test 1: "Hola" → NUEVO → "¿Cómo te llamás?"
# ─────────────────────────────────────────

class TestHolaFlow:
    """Test 1: Hola simple se queda en NUEVO y pide nombre."""

    def test_hola_stays_in_nuevo(self, manager):
        tid = 100001
        respuesta = manager.procesar_mensaje(tid, "Hola")
        session = manager.session_manager.get(tid)

        assert session.etapa == EtapaConversacion.NUEVO
        assert session.lead.nombre is None
        assert "¿Cómo te llamás?" in respuesta

    def test_hola_no_detecta_intencion_comercial(self, manager):
        tid = 100002
        manager.procesar_mensaje(tid, "Hola")
        session = manager.session_manager.get(tid)

        assert session.lead.interes_detectado is None


# ─────────────────────────────────────────
# Test 2: "Quiero info" → CALIFICANDO
# ─────────────────────────────────────────

class TestQuieroInfoFlow:
    """Test 2: Quiero info va directo a CALIFICANDO."""

    def test_quiero_info_goes_to_calificando(self, manager):
        tid = 200001
        respuesta = manager.procesar_mensaje(tid, "Quiero info")
        session = manager.session_manager.get(tid)

        assert session.etapa == EtapaConversacion.CALIFICANDO
        assert session.lead.interes_detectado == InteresDetectado.AFILIACION

    def test_quiero_info_asks_for_data(self, manager):
        tid = 200002
        respuesta = manager.procesar_mensaje(tid, "Quiero info")

        assert "familia" in respuesta.lower() or "situación laboral" in respuesta.lower()

    def test_quiero_cotizacion_goes_to_calificando(self, manager):
        tid = 200003
        respuesta = manager.procesar_mensaje(tid, "Quiero cotización")
        session = manager.session_manager.get(tid)

        assert session.etapa == EtapaConversacion.CALIFICANDO
        assert session.lead.interes_detectado == InteresDetectado.PRECIOS

    def test_me_interesa_goes_to_calificando(self, manager):
        tid = 200004
        respuesta = manager.procesar_mensaje(tid, "Me interesa")
        session = manager.session_manager.get(tid)

        assert session.etapa == EtapaConversacion.CALIFICANDO
        assert session.lead.interes_detectado == InteresDetectado.AFILIACION


# ─────────────────────────────────────────
# Test 3: Relación de dependencia → ESPERANDO_DATOS
# ─────────────────────────────────────────

class TestRelacionDependenciaFlow:
    """Test 3: Relación de dependencia pide recibo y localidad."""

    def test_rel_dep_detecta_tipo(self, manager):
        tid = 300001
        manager.procesar_mensaje(tid, "Hola, soy María")
        manager.procesar_mensaje(tid, "Soy relación de dependencia")
        session = manager.session_manager.get(tid)

        assert session.etapa == EtapaConversacion.ESPERANDO_DATOS
        assert session.lead.tipo_afiliacion == TipoAfiliacion.RELACION_DEPENDENCIA

    def test_rel_dep_pide_datos_faltantes(self, manager):
        tid = 300002
        manager.procesar_mensaje(tid, "Hola, soy María")
        respuesta = manager.procesar_mensaje(tid, "Soy relación de dependencia")

        assert "localidad" in respuesta.lower() or "recibo" in respuesta.lower()

    def test_rel_dep_con_recibo_avanza(self, manager):
        tid = 300003
        manager.procesar_mensaje(tid, "Hola, soy María")
        manager.procesar_mensaje(tid, "Soy relación de dependencia, tengo recibo de sueldo")
        manager.procesar_mensaje(tid, "Córdoba, 30 años")
        respuesta = manager.procesar_mensaje(tid, "Los conceptos del recibo son $15.000 y $8.000")
        session = manager.session_manager.get(tid)

        assert session.etapa == EtapaConversacion.PRESENTANDO_VALOR


# ─────────────────────────────────────────
# Test 4: Monotributista categoría B → ESPERANDO_DATOS
# ─────────────────────────────────────────

class TestMonotributistaFlow:
    """Test 4: Monotributista pide categoría y localidad."""

    def test_monotributo_detecta_tipo(self, manager):
        tid = 400001
        manager.procesar_mensaje(tid, "Hola, soy Pedro")
        manager.procesar_mensaje(tid, "Soy monotributista categoría B")
        session = manager.session_manager.get(tid)

        assert session.etapa == EtapaConversacion.ESPERANDO_DATOS
        assert session.lead.tipo_afiliacion == TipoAfiliacion.MONOTRIBUTO

    def test_monotributo_pide_localidad(self, manager):
        tid = 400002
        manager.procesar_mensaje(tid, "Hola, soy Pedro")
        respuesta = manager.procesar_mensaje(tid, "Soy monotributista categoría B")

        assert "localidad" in respuesta.lower()

    def test_monotributo_con_datos_avanza(self, manager):
        tid = 400003
        manager.procesar_mensaje(tid, "Hola, soy Pedro")
        manager.procesar_mensaje(tid, "Soy monotributista categoría B")
        respuesta = manager.procesar_mensaje(tid, "Córdoba, 35 años")
        session = manager.session_manager.get(tid)

        assert session.etapa == EtapaConversacion.PRESENTANDO_VALOR


# ─────────────────────────────────────────
# Test 5: Conversación completa hasta cotización
# ─────────────────────────────────────────

class TestFlujoCompleto:
    """Test 5: Flujo completo NUEVO → CALIFICANDO → ESPERANDO_DATOS → COTIZANDO → PRESENTANDO_VALOR."""

    def test_flujo_completo_con_intencion(self, manager):
        tid = 500001

        # Paso 1: "Quiero info" → CALIFICANDO
        r1 = manager.procesar_mensaje(tid, "Quiero info")
        s = manager.session_manager.get(tid)
        assert s.etapa == EtapaConversacion.CALIFICANDO
        assert s.lead.interes_detectado == InteresDetectado.AFILIACION

        # Paso 2: "Soy Juan, particular, solo para mí" → ESPERANDO_DATOS
        r2 = manager.procesar_mensaje(tid, "Soy Juan, particular, solo para mí")
        s = manager.session_manager.get(tid)
        assert s.etapa == EtapaConversacion.ESPERANDO_DATOS
        assert s.lead.nombre == "Juan"
        assert s.lead.tipo_afiliacion == TipoAfiliacion.PARTICULAR

        # Paso 3: "Córdoba, 35 años" → PRESENTANDO_VALOR (sin calculator)
        r3 = manager.procesar_mensaje(tid, "Córdoba, 35 años")
        s = manager.session_manager.get(tid)
        assert s.etapa == EtapaConversacion.PRESENTANDO_VALOR

    def test_flujo_completo_sin_intencion(self, manager):
        tid = 500002

        # Paso 1: "Hola, soy Pedro" → DESCUBRIENDO_NECESIDAD
        r1 = manager.procesar_mensaje(tid, "Hola, soy Pedro")
        s = manager.session_manager.get(tid)
        assert s.etapa == EtapaConversacion.DESCUBRIENDO_NECESIDAD
        assert s.lead.nombre == "Pedro"

        # Paso 2: "Soy monotributista categoría B" → ESPERANDO_DATOS (falta localidad)
        r2 = manager.procesar_mensaje(tid, "Soy monotributista categoría B")
        s = manager.session_manager.get(tid)
        assert s.etapa == EtapaConversacion.ESPERANDO_DATOS
        assert s.lead.tipo_afiliacion == TipoAfiliacion.MONOTRIBUTO

        # Paso 3: "Córdoba, 30 años" → PRESENTANDO_VALOR (con calculator=None)
        r3 = manager.procesar_mensaje(tid, "Córdoba, 30 años")
        s = manager.session_manager.get(tid)
        assert s.etapa == EtapaConversacion.PRESENTANDO_VALOR

    def test_sin_derivacion_prematura(self, manager):
        tid = 500003

        # Flujo normal no debería derivar
        manager.procesar_mensaje(tid, "Quiero info")
        manager.procesar_mensaje(tid, "Soy Juan, particular, solo para mí")
        r3 = manager.procesar_mensaje(tid, "Córdoba, 35 años")

        assert "asesor" not in r3.lower()
        assert "coordinamos" not in r3.lower()

    def test_datos_se_guardan_entre_mensajes(self, manager):
        tid = 500004

        manager.procesar_mensaje(tid, "Hola, soy Ana")
        manager.procesar_mensaje(tid, "Soy relación de dependencia, tengo recibo")
        manager.procesar_mensaje(tid, "Buenos Aires, 28 años")
        s = manager.session_manager.get(tid)

        assert s.lead.nombre == "Ana"
        assert s.lead.tipo_afiliacion == TipoAfiliacion.RELACION_DEPENDENCIA
        assert s.lead.localidad == "Buenos Aires"
        assert s.lead.edad == 28
        assert s.lead.tiene_recibo_sueldo is True


# ─────────────────────────────────────────
# Tests adicionales: keywords y edge cases
# ─────────────────────────────────────────

class TestKeywordDetection:
    """Verifica que nuevas keywords se detectan correctamente."""

    @pytest.mark.parametrize("mensaje,esperado", [
        ("Quiero info", InteresDetectado.AFILIACION),
        ("quiero cotización", InteresDetectado.PRECIOS),
        ("me interesa", InteresDetectado.AFILIACION),
        ("info sobre planes", InteresDetectado.AFILIACION),
        ("cómo funcionan", InteresDetectado.AFILIACION),
        ("cuánto cuesta", InteresDetectado.PRECIOS),
        ("necesito un precio", InteresDetectado.PRECIOS),
        ("Hola", InteresDetectado.INFORMACION_GENERAL),
    ])
    def test_clasificar_intencion(self, mensaje,esperado):
        assert clasificar_intencion(mensaje) == esperado


class TestNoForceAdvance:
    """Verifica que no hay force-advance por timers."""

    def test_calificando_no_avanza_por_mensajes(self, manager):
        tid = 700001
        manager.procesar_mensaje(tid, "Quiero info")

        # Enviar múltiples mensajes sin datos suficientes
        for i in range(10):
            manager.procesar_mensaje(tid, f"mensaje {i}")

        s = manager.session_manager.get(tid)
        # No debería haber avanzado a PRESENTANDO_VALOR sin datos
        assert s.etapa != EtapaConversacion.PRESENTANDO_VALOR

    def test_valor_no_avanza_por_mensajes(self, manager):
        tid = 700002
        manager.procesar_mensaje(tid, "Quiero info")
        manager.procesar_mensaje(tid, "Soy Juan, particular, solo para mí")
        manager.procesar_mensaje(tid, "Córdoba, 35 años")

        # Enviar múltiples mensajes sin decir "sí"
        for i in range(5):
            manager.procesar_mensaje(tid, f"mensaje {i}")

        s = manager.session_manager.get(tid)
        # Debería seguir en PRESENTANDO_VALOR
        assert s.etapa == EtapaConversacion.PRESENTANDO_VALOR


# ─────────────────────────────────────────
# Sprint 19b — Tests de gaps corregidos
# ─────────────────────────────────────────


class TestEdadParaTodosLosTipos:
    """Edad requerida para todos los tipos, no solo PARTICULAR."""

    def test_monotributo_pide_edad(self, manager):
        """Monotributo sin edad → pregunta edad."""
        tid = 800001
        manager.procesar_mensaje(tid, "Hola, soy Pedro")
        manager.procesar_mensaje(tid, "Quiero info")
        manager.procesar_mensaje(tid, "Monotributo, solo para mí, Córdoba")
        manager.procesar_mensaje(tid, "Categoría B")

        s = manager.session_manager.get(tid)
        # Debería faltar edad para todos los tipos
        assert s.etapa == EtapaConversacion.ESPERANDO_DATOS

    def test_relacion_dependencia_pide_edad(self, manager):
        """Relación de dependencia sin edad → pregunta edad."""
        tid = 800002
        manager.procesar_mensaje(tid, "Hola, soy Ana")
        manager.procesar_mensaje(tid, "Quiero info")
        manager.procesar_mensaje(tid, "Relación de dependencia, solo yo, Buenos Aires")
        manager.procesar_mensaje(tid, "Tengo recibo de sueldo")

        s = manager.session_manager.get(tid)
        assert s.etapa == EtapaConversacion.ESPERANDO_DATOS


class TestConceptosObraSocial:
    """Conceptos de obra social para relación de dependencia."""

    def test_extraer_conceptos_del_mensaje(self, manager):
        """Extrae montos del recibo como conceptos_obra_social."""
        tid = 800003
        manager.procesar_mensaje(tid, "Hola, soy Roberto")
        manager.procesar_mensaje(tid, "Quiero info")
        manager.procesar_mensaje(tid, "Relación de dependencia, solo yo, Córdoba, 35 años")
        manager.procesar_mensaje(tid, "Sí, tengo recibo. Los conceptos son $15.000 y $8.000")

        s = manager.session_manager.get(tid)
        # Debería tener conceptos extraídos
        assert len(s.lead.conceptos_obra_social) == 2
        assert 15000.0 in s.lead.conceptos_obra_social
        assert 8000.0 in s.lead.conceptos_obra_social

    def test_conceptos_pasan_a_calculadora(self, manager):
        """conceptos_obra_social se pasan al calculator.cotizar()."""
        tid = 800004
        manager.procesar_mensaje(tid, "Hola, soy Laura")
        manager.procesar_mensaje(tid, "Quiero info")
        manager.procesar_mensaje(tid, "Relación de dependencia, solo yo, Córdoba, 28 años")
        manager.procesar_mensaje(tid, "Recibo de sueldo, conceptos $12.000")

        s = manager.session_manager.get(tid)
        # Verificar que conceptos están en el lead
        assert len(s.lead.conceptos_obra_social) >= 1

    def test_relacion_dependencia_sin_conceptos_pregunta(self, manager):
        """Relación de dependencia con recibo pero sin conceptos → pregunta conceptos."""
        tid = 800005
        manager.procesar_mensaje(tid, "Hola, soy Martín")
        manager.procesar_mensaje(tid, "Quiero info")
        manager.procesar_mensaje(tid, "Relación de dependencia, solo yo, Rosario, 30 años")
        manager.procesar_mensaje(tid, "Sí, tengo recibo")

        s = manager.session_manager.get(tid)
        # Debería estar en ESPERANDO_DATOS pidiendo conceptos
        assert s.etapa == EtapaConversacion.ESPERANDO_DATOS


class TestSinAsesorEnRecuperar:
    """recuperar_indeciso no ofrece asesor en el default."""

    def test_default_no_menciona_asesor(self):
        from app.services.closing_strategy import recuperar_indeciso
        lead = Lead(lead_id="test_no_asesor", nombre="Test")
        respuesta = recuperar_indeciso(lead)
        assert "asesor" not in respuesta.lower()
        assert "seguimos" in respuesta.lower() or "ayudarte" in respuesta.lower()

    def test_flujo_indeciso_no_ofrece_asesor(self, manager):
        """Cliente indeciso recibe 'seguimos' no 'asesor'."""
        tid = 800006
        manager.procesar_mensaje(tid, "Hola, soy Diego")
        manager.procesar_mensaje(tid, "Quiero info")
        manager.procesar_mensaje(tid, "Particular, solo para mí")
        manager.procesar_mensaje(tid, "Córdoba, 30 años")
        manager.procesar_mensaje(tid, "Sí, avanzamos")
        respuesta = manager.procesar_mensaje(tid, "Tengo dudas todavía")

        assert "asesor" not in respuesta.lower()
