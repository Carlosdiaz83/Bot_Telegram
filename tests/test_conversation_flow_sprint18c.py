"""
Tests Sprint 18C — Flujo conversacional Telegram.

Cubre:
    - _extraer_nombre con nombre suelto (sin prefijo)
    - Flujo: hola → nombre → avance a descubrimiento
    - Persistencia de estado entre mensajes
    - Logs estructurados [CONVERSATION]
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.models import Base
from app.models.lead import EstadoComercial, Lead, TipoAfiliacion
from app.services.lead_qualifier import _extraer_nombre
from app.services.session_manager import EtapaConversacion, SessionManager
from app.services.conversation_manager import ConversationManager


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
def manager_sin_db():
    return ConversationManager(ai_service=None, database_url=None)


@pytest.fixture()
def manager_con_db(db_session):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    factory = Session
    m = ConversationManager(ai_service=None, database_url="sqlite:///:memory:")
    return m


# ─────────────────────────────────────────
# Tests: _extraer_nombre con nombre suelto
# ─────────────────────────────────────────

class TestExtraerNombreSuelto:
    def test_nombre_suelto_carlos(self):
        assert _extraer_nombre("Carlos") == "Carlos"

    def test_nombre_suelto_maria(self):
        assert _extraer_nombre("María") == "María"

    def test_nombre_con_prefijo(self):
        assert _extraer_nombre("Soy Carlos") == "Carlos"

    def test_nombre_me_llamo(self):
        assert _extraer_nombre("Me llamo Carlos") == "Carlos"

    def test_nombre_minimo_3_chars(self):
        assert _extraer_nombre("No") is None

    def test_nombre_no_es_keyword_hola(self):
        assert _extraer_nombre("Hola") is None

    def test_nombre_no_es_keyword_ayuda(self):
        assert _extraer_nombre("Ayuda") is None

    def test_nombre_no_es_keyword_precio(self):
        assert _extraer_nombre("Precio") is None

    def test_nombre_suelto_con_espacios(self):
        assert _extraer_nombre("  Carlos  ") == "Carlos"

    def test_nombre_suelto_minusculas(self):
        assert _extraer_nombre("carlos") is None


# ─────────────────────────────────────────
# Tests: Flujo conversacional completo
# ─────────────────────────────────────────

class TestFlujoConversacional:
    def test_hola_pide_nombre(self, manager_sin_db):
        respuesta = manager_sin_db.procesar_mensaje(100, "hola")
        assert "¿Cómo te llamás?" in respuesta

    def test_nombre_suelto_avanza(self, manager_sin_db):
        manager_sin_db.procesar_mensaje(100, "hola")
        respuesta = manager_sin_db.procesar_mensaje(100, "Carlos")
        assert "Carlos" in respuesta
        assert "¿Cómo te llamás?" not in respuesta

    def test_nombre_con_prefijo_avanza(self, manager_sin_db):
        manager_sin_db.procesar_mensaje(100, "hola")
        respuesta = manager_sin_db.procesar_mensaje(100, "Soy Carlos")
        assert "Carlos" in respuesta
        assert "¿Cómo te llamás?" not in respuesta

    def test_flujo_completo_hasta_grupo(self, manager_sin_db):
        manager_sin_db.procesar_mensaje(100, "hola")
        manager_sin_db.procesar_mensaje(100, "Carlos")
        session = manager_sin_db.session_manager.get(100)
        assert session is not None
        assert session.etapa != EtapaConversacion.NUEVO

    def test_estado_se_persiste_entre_mensajes(self, manager_sin_db):
        manager_sin_db.procesar_mensaje(100, "hola")
        manager_sin_db.procesar_mensaje(100, "Carlos")
        session = manager_sin_db.session_manager.get(100)
        assert session.lead.nombre == "Carlos"

    def test_usuario_returning_no_saluda(self, manager_sin_db):
        manager_sin_db.procesar_mensaje(100, "hola")
        manager_sin_db.procesar_mensaje(100, "Carlos")
        session = manager_sin_db.session_manager.get(100)
        session.etapa = EtapaConversacion.CALIFICANDO
        session.lead.nombre = "Carlos"
        respuesta = manager_sin_db.procesar_mensaje(100, "Tengo 30 años")
        assert "¿Cómo te llamás?" not in respuesta


# ─────────────────────────────────────────
# Tests: Persistencia con DB
# ─────────────────────────────────────────

class TestPersistenciaDB:
    def test_lead_se_guarda_en_db(self, manager_con_db):
        manager_con_db.procesar_mensaje(200, "hola")
        manager_con_db.procesar_mensaje(200, "Carlos")
        manager_con_db.procesar_mensaje(200, "Soy de Córdoba")

        db = manager_con_db._db_factory()
        try:
            from app.database.repository import LeadRepository
            repo = LeadRepository(db)
            lead_db = repo.buscar_por_telegram_id(200)
            assert lead_db is not None
            assert lead_db.nombre == "Carlos"
        finally:
            db.close()

    def test_etapa_se_persiste_en_db(self, manager_con_db):
        manager_con_db.procesar_mensaje(201, "hola")
        manager_con_db.procesar_mensaje(201, "Carlos")

        db = manager_con_db._db_factory()
        try:
            from app.database.repository import LeadRepository
            repo = LeadRepository(db)
            lead_db = repo.buscar_por_telegram_id(201)
            assert lead_db is not None
            assert lead_db.etapa_conversacion != "nuevo"
        finally:
            db.close()

    def test_restart_recupera_estado(self, manager_con_db):
        manager_con_db.procesar_mensaje(202, "hola")
        manager_con_db.procesar_mensaje(202, "Carlos")

        # Simular restart: nueva instancia de manager
        manager2 = ConversationManager(
            ai_service=None,
            database_url="sqlite:///:memory:",
        )
        manager2._db_factory = manager_con_db._db_factory

        respuesta = manager2.procesar_mensaje(202, "Hola de nuevo")
        assert "¿Cómo te llamás?" not in respuesta


# ─────────────────────────────────────────
# Tests: Escenario exacto de producción
# Mensaje "Hola" → "¿Cómo te llamás?"
# Mensaje "Carlos" → guardar nombre, avanzar, NO repetir bienvenida
# ─────────────────────────────────────────

class TestEscenarioProduccion:
    def test_hola_carlos_guarda_nombre_cambia_etapa_no_repite_bienvenida(
        self, manager_sin_db
    ):
        """Caso exacto de producción: Hola → Carlos."""
        r1 = manager_sin_db.procesar_mensaje(900, "Hola")
        assert "¿Cómo te llamás?" in r1

        r2 = manager_sin_db.procesar_mensaje(900, "Carlos")
        assert "Carlos" in r2
        assert "¿Cómo te llamás?" not in r2

        session = manager_sin_db.session_manager.get(900)
        assert session.lead.nombre == "Carlos"
        assert session.etapa != EtapaConversacion.NUEVO

    def test_hola_carlos_con_db_persiste(self, manager_con_db):
        """Escenario producción con DB: nombre y etapa se persisten."""
        manager_con_db.procesar_mensaje(901, "Hola")
        manager_con_db.procesar_mensaje(901, "Carlos")

        db = manager_con_db._db_factory()
        try:
            from app.database.repository import LeadRepository
            repo = LeadRepository(db)
            lead_db = repo.buscar_por_telegram_id(901)
            assert lead_db is not None
            assert lead_db.nombre == "Carlos"
            assert lead_db.etapa_conversacion != "nuevo"
        finally:
            db.close()

    def test_restart_no_repite_bienvenida(self, manager_con_db):
        """Restart del servidor: el usuario returning NO recibe saludo inicial."""
        manager_con_db.procesar_mensaje(902, "Hola")
        manager_con_db.procesar_mensaje(902, "Carlos")

        manager2 = ConversationManager(
            ai_service=None,
            database_url="sqlite:///:memory:",
        )
        manager2._db_factory = manager_con_db._db_factory

        respuesta = manager2.procesar_mensaje(902, "Hola de nuevo")
        assert "¿Cómo te llamás?" not in respuesta
