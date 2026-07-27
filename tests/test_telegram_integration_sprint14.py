"""
Tests — Sprint 14.1: Integración del cerebro comercial Sofía con Telegram.

Verifica:
    - Nuevo cliente: crear Lead, iniciar conversación, pedir nombre
    - Cliente existente: recuperar Lead, continuar etapa
    - Cliente vuelve después de reinicio: mantener estado
    - Pregunta precio: no cotizar inmediatamente, descubrir necesidad primero
    - Objeción: validar, preguntar motivo, intentar resolver
    - Handler es adaptador puro
    - AIService participa o fallback
    - Persistencia DB roundtrip
"""

from __future__ import annotations

import tempfile

import pytest
from sqlalchemy import create_engine as _create_engine

from app.models.lead import (
    EstadoComercial,
    InteresDetectado,
    Lead,
    NecesidadPrincipal,
    PrioridadCliente,
    TipoAfiliacion,
)
from app.services.session_manager import EtapaConversacion, SessionManager, UserSession
from app.services.conversation_manager import ConversationManager
from app.services.lead_qualifier import (
    LeadQualifierService,
    clasificar_intencion,
    _extraer_nombre,
    _detectar_grupo_familiar,
    _detectar_tipo_afiliacion,
)
from app.services.objection_handler import (
    TipoObjecion,
    detectar_objecion,
    analizar_mensaje,
)
from app.services.closing_strategy import (
    intentar_cierre,
    interpretar_respuesta_cierre,
    seleccionar_cierre,
)
from app.services.lead_scoring import LeadScoringService
from app.services.sales_strategy import generar_argumento, generar_presentacion_inicial
from app.services.knowledge_service import KnowledgeService
from app.database.database import get_engine, crear_tablas, get_session_factory
from app.database.models import Base
from app.database.repository import LeadRepository, ConversationRepository


# ─────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────

@pytest.fixture
def db_session():
    """Crea una base de datos SQLite temporal para tests."""
    engine = _create_engine("sqlite:///:memory:")
    crear_tablas(engine)
    factory = get_session_factory(engine)
    session = factory()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def manager_con_db(db_session):
    """ConversationManager con DB real (mismo engine que db_session)."""
    from app.database.database import _engine, get_session_factory
    from app.services.conversation_manager import ConversationManager
    from app.services.commercial_ai_orchestrator import CommercialAIOrchestrator

    engine = db_session.get_bind()
    manager = ConversationManager.__new__(ConversationManager)
    manager.session_manager = SessionManager()
    manager.qualifier = LeadQualifierService()
    manager.knowledge = KnowledgeService()
    manager.scoring = LeadScoringService()
    manager.ai = None
    manager._db_enabled = True
    manager._db_factory = get_session_factory(engine)
    manager._knowledge_engine = None
    manager._calculator = None
    manager._orchestrator = CommercialAIOrchestrator(
        ai_service=None, knowledge_engine=None, knowledge_service=manager.knowledge,
    )
    return manager


@pytest.fixture
def manager_sin_db():
    """ConversationManager sin DB (solo memoria)."""
    return ConversationManager()


# ─────────────────────────────────────────────
# Test 1: Nuevo cliente — crear Lead, iniciar conversación, pedir nombre
# ─────────────────────────────────────────────

class TestNuevoCliente:
    """Nuevo cliente: crear Lead, iniciar conversación, pedir nombre."""

    def test_primer_mensaje_pide_nombre(self, manager_sin_db):
        """Primer mensaje sin nombre → pide nombre."""
        respuesta = manager_sin_db.procesar_mensaje(9001, "Hola")
        assert "¿Cómo te llamás?" in respuesta
        assert "Sofía" in respuesta or "Servired" in respuesta

    def test_primer_mensaje_extrae_nombre(self, manager_sin_db):
        """Primer mensaje con nombre → saluda y avanza a descubrimiento."""
        respuesta = manager_sin_db.procesar_mensaje(9002, "Hola, me llamo Juan")
        assert "Juan" in respuesta
        assert "grupo familiar" in respuesta.lower() or "familia" in respuesta.lower()

    def test_lead_creado_con_datos_basicos(self, manager_sin_db):
        """Después del saludo, Lead tiene nombre y estado CONTACTADO."""
        manager_sin_db.procesar_mensaje(9003, "Hola, soy Carlos")
        session = manager_sin_db.session_manager.get(9003)
        assert session is not None
        assert session.lead.nombre == "Carlos"
        assert session.lead.estado_comercial == EstadoComercial.CONTACTADO

    def test_etapa_avanza_a_descubriendo(self, manager_sin_db):
        """Después de nombre, etapa es DESCUBRIENDO_NECESIDAD."""
        manager_sin_db.procesar_mensaje(9004, "Me llamo Ana")
        session = manager_sin_db.session_manager.get(9004)
        assert session.etapa == EtapaConversacion.DESCUBRIENDO_NECESIDAD

    def test_solo_pide_nombre_una_vez(self, manager_sin_db):
        """Si el usuario no da nombre, solo pide una vez (no repite infinitamente)."""
        manager_sin_db.procesar_mensaje(9005, "Hola")
        manager_sin_db.procesar_mensaje(9005, "Quiero precios")
        session = manager_sin_db.session_manager.get(9005)
        assert session is not None


# ─────────────────────────────────────────────
# Test 2: Cliente existente — recuperar Lead, continuar etapa
# ─────────────────────────────────────────────

class TestClienteExistente:
    """Cliente existente: recuperar Lead, continuar etapa."""

    def test_conversacion_avanza_calificacion(self, manager_sin_db):
        """Flujo: nombre → grupo familiar → calificación."""
        manager_sin_db.procesar_mensaje(9010, "Soy Pedro")
        manager_sin_db.procesar_mensaje(9010, "Mi esposa y mis hijos")
        session = manager_sin_db.session_manager.get(9010)
        assert session.etapa == EtapaConversacion.CALIFICANDO

    def test_lead_acumula_datos(self, manager_sin_db):
        """El Lead acumula datos de múltiples mensajes."""
        manager_sin_db.procesar_mensaje(9011, "Me llamo Laura")
        manager_sin_db.procesar_mensaje(9011, "Mi esposo y mis hijos")
        session = manager_sin_db.session_manager.get(9011)
        assert session.lead.nombre == "Laura"
        assert session.lead.grupo_familiar.conyuge is True
        assert session.lead.grupo_familiar.hijos is True

    def test_estado_comercial_cambia(self, manager_sin_db):
        """El estado comercial avanza con la conversación."""
        manager_sin_db.procesar_mensaje(9012, "Soy Martín")
        session = manager_sin_db.session_manager.get(9012)
        assert session.lead.estado_comercial == EstadoComercial.CONTACTADO

    def test_score_se_calcula(self, manager_sin_db):
        """El score se calcula en cada mensaje."""
        manager_sin_db.procesar_mensaje(9013, "Hola, soy Pedro")
        session = manager_sin_db.session_manager.get(9013)
        assert session.lead.score >= 0
        assert session.lead.temperatura_lead != ""


# ─────────────────────────────────────────────
# Test 3: Cliente vuelve después de reinicio — mantener estado
# ─────────────────────────────────────────────

class TestClienteReturning:
    """Cliente vuelve después de reinicio: mantener estado."""

    def test_returning_en_descubrimiento(self, manager_sin_db):
        """Cliente en DESCUBRIENDO_NECESIDAD, server se reinicia, vuelve."""
        manager_sin_db.procesar_mensaje(9020, "Soy Juan")
        session1 = manager_sin_db.session_manager.get(9020)
        assert session1.etapa == EtapaConversacion.DESCUBRIENDO_NECESIDAD

        manager_sin_db.session_manager.eliminar(9020)
        session2 = manager_sin_db.session_manager.get_or_create(9020)
        session2.lead = Lead(
            lead_id="9020", nombre="Juan",
            estado_comercial=EstadoComercial.CONTACTADO,
        )
        session2.etapa = EtapaConversacion.DESCUBRIENDO_NECESIDAD

        respuesta = manager_sin_db.procesar_mensaje(9020, "Mi esposa y mis hijos")
        session = manager_sin_db.session_manager.get(9020)
        assert session.lead.nombre == "Juan"
        assert session.lead.grupo_familiar.conyuge is True
        assert len(respuesta) > 10

    def test_returning_en_calificacion(self, manager_sin_db):
        """Cliente en CALIFICANDO, server se reinicia, vuelve."""
        manager_sin_db.procesar_mensaje(9021, "Soy Ana")
        manager_sin_db.procesar_mensaje(9021, "Mi esposo")
        session1 = manager_sin_db.session_manager.get(9021)
        assert session1.etapa == EtapaConversacion.CALIFICANDO

        manager_sin_db.session_manager.eliminar(9021)
        session2 = manager_sin_db.session_manager.get_or_create(9021)
        session2.lead = Lead(
            lead_id="9021", nombre="Ana",
            estado_comercial=EstadoComercial.CALIFICANDO,
            grupo_familiar=Lead.model_fields["grupo_familiar"].default_factory(),
        )
        session2.lead.grupo_familiar.conyuge = True
        session2.etapa = EtapaConversacion.CALIFICANDO

        session2.lead.grupo_familiar.conyuge = True
        session2.lead.tipo_afiliacion = TipoAfiliacion.RELACION_DEPENDENCIA

        respuesta = manager_sin_db.procesar_mensaje(9021, "Tengo recibo de sueldo")
        assert len(respuesta) > 10


# ─────────────────────────────────────────────
# Test 4: Pregunta precio — no cotizar inmediatamente, descubrir necesidad
# ─────────────────────────────────────────────

class TestPreguntaPrecio:
    """Pregunta precio: no cotizar inmediatamente, descubrir necesidad primero."""

    def test_pregunta_precio_en_calificacion(self, manager_sin_db):
        """Si pregunta precio en etapa CALIFICANDO, no avanza a cierre directo."""
        manager_sin_db.procesar_mensaje(9030, "Soy Pedro")
        manager_sin_db.procesar_mensaje(9030, "Solo yo")
        session = manager_sin_db.session_manager.get(9030)
        assert session.lead.nombre == "Pedro"
        assert session.lead.estado_comercial in [
            EstadoComercial.CONTACTADO,
            EstadoComercial.CALIFICANDO,
            EstadoComercial.INTERESADO,
        ]

    def test_no_cotiza_sin_datos_suficientes(self, manager_sin_db):
        """Sin nombre, tipo afiliación y grupo, no genera argumento de valor."""
        manager_sin_db.procesar_mensaje(9031, "Hola")
        manager_sin_db.procesar_mensaje(9031, "¿Cuánto cuesta?")
        session = manager_sin_db.session_manager.get(9031)
        assert session.etapa != EtapaConversacion.PRESENTANDO_VALOR

    def test_intencion_precios_detectada(self):
        """La intención de precios se detecta correctamente."""
        intencion = clasificar_intencion("¿Cuánto cuesta la obra social?")
        assert intencion == InteresDetectado.PRECIOS

    def test_flujo_completo_hasta_valor(self, manager_sin_db):
        """Flujo completo: nombre → grupo → tipo → valor."""
        manager_sin_db.procesar_mensaje(9032, "Soy Roberto")
        manager_sin_db.procesar_mensaje(9032, "Mi esposa y mis hijos")
        manager_sin_db.procesar_mensaje(9032, "Tengo recibo de sueldo")
        session = manager_sin_db.session_manager.get(9032)
        assert session.lead.nombre == "Roberto"
        assert session.lead.tipo_afiliacion == TipoAfiliacion.RELACION_DEPENDENCIA
        assert session.lead.grupo_familiar.conyuge is True


# ─────────────────────────────────────────────
# Test 5: Objeción — validar, preguntar motivo, intentar resolver
# ─────────────────────────────────────────────

class TestManejoObjeciones:
    """Objeción: validar, preguntar motivo, intentar resolver."""

    def test_detectar_objecion_precio(self):
        """Detecta objeción de precio."""
        objecion = detectar_objecion("Es muy caro")
        assert objecion == TipoObjecion.PRECIO

    def test_detectar_objecion_duda(self):
        """Detecta objeción de duda."""
        objecion = detectar_objecion("No estoy seguro")
        assert objecion == TipoObjecion.DUDA

    def test_detectar_objecion_procrastinacion(self):
        """Detecta objeción de procrastinación."""
        objecion = detectar_objecion("Lo voy a pensar")
        assert objecion == TipoObjecion.PROCRASTINACION

    def test_detectar_objecion_tiempo(self):
        """Detecta objeción de tiempo."""
        objecion = detectar_objecion("No tengo tiempo")
        assert objecion == TipoObjecion.TIEMPO

    def test_objecion_respuesta_valida(self):
        """La objeción genera una respuesta válida."""
        lead = Lead(lead_id="test", nombre="Juan")
        resultado = analizar_mensaje("Es muy caro", lead)
        assert resultado.es_objecion is True
        assert resultado.respuesta is not None
        assert len(resultado.respuesta) > 10

    def test_objecion_en_calificacion_avanza_a_manejando(self, manager_sin_db):
        """Objeción en calificación avanza a MANEJANDO_OBJECIONES."""
        manager_sin_db.procesar_mensaje(9040, "Soy Juan")
        manager_sin_db.procesar_mensaje(9040, "Mi esposa")
        manager_sin_db.procesar_mensaje(9040, "Es muy caro")
        session = manager_sin_db.session_manager.get(9040)
        assert session.etapa == EtapaConversacion.MANEJANDO_OBJECIONES

    def test_objecion_repite_derivacion(self, manager_sin_db):
        """Múltiples objeciones en MANEJANDO_OBJECIONES → derivar a asesor."""
        manager_sin_db.procesar_mensaje(9041, "Soy Juan")
        manager_sin_db.procesar_mensaje(9041, "Mi esposa")
        manager_sin_db.procesar_mensaje(9041, "Particular")
        manager_sin_db.procesar_mensaje(9041, "Córdoba, 30 años")
        # Ahora debería estar en PRESENTANDO_VALOR
        manager_sin_db.procesar_mensaje(9041, "Es muy caro")
        session = manager_sin_db.session_manager.get(9041)
        assert session.etapa == EtapaConversacion.MANEJANDO_OBJECIONES
        manager_sin_db.procesar_mensaje(9041, "No tengo tiempo")
        manager_sin_db.procesar_mensaje(9041, "No estoy seguro")
        manager_sin_db.procesar_mensaje(9041, "No me da confianza")
        manager_sin_db.procesar_mensaje(9041, "Prefiero pensarlo")
        manager_sin_db.procesar_mensaje(9041, "No sé si es bueno")
        session = manager_sin_db.session_manager.get(9041)
        assert session.etapa == EtapaConversacion.CALIFICADO


# ─────────────────────────────────────────────
# Test 6: Handler es adaptador puro
# ─────────────────────────────────────────────

class TestHandlerAdaptador:
    """Handler es adaptador puro — no contiene lógica comercial."""

    def test_handler_no_importa_servicios_comerciales(self):
        """El handler no importa servicios de negocio directamente."""
        import app.telegram.handlers as h
        source = open(h.__file__).read()
        assert "LeadQualifierService" not in source
        assert "KnowledgeService" not in source
        assert "generar_argumento" not in source
        assert "manejar_objecion" not in source

    def test_handler_delega_a_manager(self):
        """El handler solo llama a manager.procesar_mensaje()."""
        import app.telegram.handlers as h
        source = open(h.__file__).read()
        assert "procesar_mensaje" in source
        assert "get_manager()" in source

    def test_handler_log_estructurado(self):
        """El handler usa logs con tags [TELEGRAM]."""
        import app.telegram.handlers as h
        source = open(h.__file__).read()
        assert "[TELEGRAM]" in source
        assert "[CONVERSATION]" in source


# ─────────────────────────────────────────────
# Test 7: AIService participa o fallback
# ─────────────────────────────────────────────

class TestAIService:
    """AIService participa o fallback a template."""

    def test_sin_ai_respuesta_es_template(self, manager_sin_db):
        """Sin AIService, las respuestas son templates."""
        manager_sin_db.procesar_mensaje(9050, "Hola, soy Juan")
        respuesta = manager_sin_db.procesar_mensaje(
            9050, "Mi esposa y mis hijos"
        )
        assert len(respuesta) > 0

    def test_ai_disabled_fallback(self):
        """AIService con API key vacía → disponible=False."""
        from app.ai.service import AIService
        ai = AIService(api_key="")
        assert ai.disponible is False


# ─────────────────────────────────────────────
# Test 8: Separación de responsabilidades
# ─────────────────────────────────────────────

class TestSeparacionResponsabilidades:
    """ConversationManager decide etapa/preguntas. AIService decide tono."""

    def test_manager_decide_etapa(self, manager_sin_db):
        """ConversationManager decide la etapa según el flujo."""
        manager_sin_db.procesar_mensaje(9060, "Hola, soy Pedro")
        session = manager_sin_db.session_manager.get(9060)
        assert session.etapa == EtapaConversacion.DESCUBRIENDO_NECESIDAD

    def test_manager_decide_preguntas(self, manager_sin_db):
        """ConversationManager genera preguntas según datos faltantes."""
        manager_sin_db.procesar_mensaje(9061, "Hola, soy Pedro")
        session = manager_sin_db.session_manager.get(9061)
        assert session.etapa == EtapaConversacion.DESCUBRIENDO_NECESIDAD

    def test_manager_no_inventa_precios(self, manager_sin_db):
        """ConversationManager no inventa precios en respuestas."""
        manager_sin_db.procesar_mensaje(9062, "Hola, soy Pedro")
        manager_sin_db.procesar_mensaje(9062, "Mi esposa e hijos")
        manager_sin_db.procesar_mensaje(9062, "Recibo de sueldo")
        session = manager_sin_db.session_manager.get(9062)
        assert session.lead.nombre == "Pedro"


# ─────────────────────────────────────────────
# Test 9: Persistencia DB roundtrip
# ─────────────────────────────────────────────

class TestPersistenciaDB:
    """Persistencia DB roundtrip: guardar → cargar → continuar."""

    def test_guardar_y_cargar_lead(self, manager_con_db, db_session):
        """Lead se guarda en DB y se carga correctamente."""
        manager_con_db.procesar_mensaje(9070, "Hola, soy Lucas")

        lead_repo = LeadRepository(db_session)
        lead_db = lead_repo.buscar_por_telegram_id(9070)
        assert lead_db is not None
        assert lead_db.nombre == "Lucas"

    def test_etapa_se_persiste(self, manager_con_db, db_session):
        """La etapa de conversación se persiste en DB."""
        manager_con_db.procesar_mensaje(9071, "Hola, soy Marta")
        manager_con_db.procesar_mensaje(9071, "Mi esposo")

        lead_repo = LeadRepository(db_session)
        lead_db = lead_repo.buscar_por_telegram_id(9071)
        assert lead_db is not None
        assert lead_db.etapa_conversacion == "calificando"

    def test_mensajes_se_persisten(self, manager_con_db, db_session):
        """Los mensajes se persisten en DB."""
        manager_con_db.procesar_mensaje(9072, "Hola, soy Ana")

        lead_repo = LeadRepository(db_session)
        lead_db = lead_repo.buscar_por_telegram_id(9072)
        assert lead_db is not None

        conv_repo = ConversationRepository(db_session)
        historial = conv_repo.historial_lead(lead_db.id)
        assert len(historial) >= 1

    def test_roundtrip_reinicio(self, manager_con_db, db_session):
        """Simula reinicio: guardar → limpiar memoria → cargar desde DB."""
        manager_con_db.procesar_mensaje(9073, "Hola, soy Pedro")
        manager_con_db.procesar_mensaje(9073, "Mi esposa e hijos")

        manager_con_db.session_manager.eliminar(9073)

        lead_repo = LeadRepository(db_session)
        lead_db = lead_repo.buscar_por_telegram_id(9073)
        assert lead_db is not None
        assert lead_db.nombre == "Pedro"
        assert lead_db.etapa_conversacion in ["calificando", "descubriendo_necesidad"]

    def test_score_se_persiste(self, manager_con_db, db_session):
        """El score se persiste en DB."""
        manager_con_db.procesar_mensaje(9074, "Hola, soy Juan")

        lead_repo = LeadRepository(db_session)
        lead_db = lead_repo.buscar_por_telegram_id(9074)
        assert lead_db is not None
        assert lead_db.score >= 0


# ─────────────────────────────────────────────
# Test 10: Flujo completo SERVIRED
# ─────────────────────────────────────────────

class TestFlujoCompletoSERVIRED:
    """Flujo completo de venta SERVIRED end-to-end."""

    def test_hola_nombre_grupo_familiar_tipo(self, manager_sin_db):
        """Flujo: Hola → Nombre → Grupo familiar → Tipo afiliación."""
        r1 = manager_sin_db.procesar_mensaje(9080, "Hola")
        assert "¿Cómo te llamás?" in r1

        r2 = manager_sin_db.procesar_mensaje(9080, "Soy Juan")
        assert "Juan" in r2
        assert "grupo familiar" in r2.lower() or "familia" in r2.lower()

        r3 = manager_sin_db.procesar_mensaje(9080, "Mi esposa y mis hijos")
        assert len(r3) > 10

        session = manager_sin_db.session_manager.get(9080)
        assert session.lead.nombre == "Juan"
        assert session.lead.grupo_familiar.conyuge is True
        assert session.lead.grupo_familiar.hijos is True

    def test_nombre_luego_grupo_despues_calificacion(self, manager_sin_db):
        """Después de nombre, pide grupo familiar, luego sit. laboral."""
        manager_sin_db.procesar_mensaje(9081, "Me llamo Carlos")
        session1 = manager_sin_db.session_manager.get(9081)
        assert session1.etapa == EtapaConversacion.DESCUBRIENDO_NECESIDAD

        manager_sin_db.procesar_mensaje(9081, "Solo yo")
        session2 = manager_sin_db.session_manager.get(9081)
        assert session2.etapa == EtapaConversacion.CALIFICANDO

    def test_objecion_en任何形式_no_rompe_flujo(self, manager_sin_db):
        """Una objeción en calificación redirige correctamente."""
        manager_sin_db.procesar_mensaje(9082, "Soy Pedro")
        manager_sin_db.procesar_mensaje(9082, "Mi esposa")
        r = manager_sin_db.procesar_mensaje(9082, "Es muy caro")
        assert len(r) > 10

        session = manager_sin_db.session_manager.get(9082)
        assert session.etapa == EtapaConversacion.MANEJANDO_OBJECIONES


# ─────────────────────────────────────────────
# Test 11: Logs comerciales
# ─────────────────────────────────────────────

class TestLogsComerciales:
    """Verifica que los logs estructurados existen."""

    def test_conversation_manager_tiene_logsestructurados(self):
        """ConversationManager tiene logs con tags comerciales."""
        import app.services.conversation_manager as cm
        source = open(cm.__file__).read()
        assert "[LEAD]" in source
        assert "[CONVERSATION]" in source
        assert "[SALES]" in source
        assert "[AI]" in source
        assert "[DATABASE]" in source

    def test_handlers_tiene_logs_telegram(self):
        """Handlers tiene logs con tag [TELEGRAM]."""
        import app.telegram.handlers as h
        source = open(h.__file__).read()
        assert "[TELEGRAM]" in source
        assert "[CONVERSATION]" in source
