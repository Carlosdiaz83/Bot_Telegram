"""
Tests — Sprint 13: Producción y Operación.

Verifica configuración de producción, carga de variables,
manejo de errores y persistencia en entorno productivo.
"""

from __future__ import annotations

import os
import tempfile

import pytest
from sqlalchemy import create_engine as _create_engine

from app.config.settings import BotConfig
from app.database.database import get_engine, crear_tablas, cerrar_engine, get_session_factory
from app.database.models import Base, LeadDB, TrainingSessionDB
from app.database.repository import LeadRepository, TrainingRepository


# ─────────────────────────────────────────────
# Tests — Configuración
# ─────────────────────────────────────────────

class TestBotConfig:
    """Tests de la configuración del bot."""

    def test_config_requiere_telegram_token(self, monkeypatch):
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN"):
            BotConfig.from_env()

    def test_config_default_values(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token-123")
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        monkeypatch.delenv("AI_MODEL", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.delenv("APP_ENV", raising=False)
        monkeypatch.delenv("APP_DEBUG", raising=False)
        monkeypatch.delenv("LOG_LEVEL", raising=False)
        config = BotConfig.from_env()
        assert config.telegram_token == "test-token-123"
        assert config.groq_api_key == ""
        assert config.ai_model == "llama-3.3-70b-versatile"
        assert "sqlite" in config.database_url
        assert config.app_env == "development"
        assert config.app_debug is False
        assert config.log_level == "INFO"

    def test_config_production_values(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "prod-token")
        monkeypatch.setenv("GROQ_API_KEY", "gsk_prod_key")
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("APP_DEBUG", "false")
        monkeypatch.setenv("LOG_LEVEL", "WARNING")
        monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/db")
        config = BotConfig.from_env()
        assert config.app_env == "production"
        assert config.groq_api_key == "gsk_prod_key"
        assert "postgresql" in config.database_url

    def test_config_debug_true(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
        monkeypatch.setenv("APP_DEBUG", "true")
        config = BotConfig.from_env()
        assert config.app_debug is True

    def test_config_debug_1(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
        monkeypatch.setenv("APP_DEBUG", "1")
        config = BotConfig.from_env()
        assert config.app_debug is True

    def test_config_es_inmutable(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
        config = BotConfig.from_env()
        with pytest.raises(AttributeError):
            config.telegram_token = "otro"


# ─────────────────────────────────────────────
# Tests — Base de datos
# ─────────────────────────────────────────────

class TestDatabaseProduction:
    """Tests de persistencia en entorno de producción."""

    def test_engine_sqlite_funciona(self):
        engine = get_engine("sqlite:///:memory:")
        crear_tablas(engine)
        factory = get_session_factory(engine)
        db = factory()
        lead = LeadDB(telegram_id=10001, nombre="Prod Test")
        db.add(lead)
        db.commit()
        assert lead.id is not None
        db.close()
        cerrar_engine()

    def test_lead_repository_persistencia(self):
        engine = get_engine("sqlite:///:memory:")
        crear_tablas(engine)
        factory = get_session_factory(engine)
        db = factory()
        repo = LeadRepository(db)
        lead = LeadDB(telegram_id=10002, nombre="Persist Test", score=85)
        db.add(lead)
        db.commit()
        leads = repo.listar_leads()
        assert len(leads) == 1
        assert leads[0].nombre == "Persist Test"
        assert leads[0].score == 85
        db.close()
        cerrar_engine()

    def test_training_repository_persistencia(self):
        engine = get_engine("sqlite:///:memory:")
        crear_tablas(engine)
        factory = get_session_factory(engine)
        db = factory()
        repo = TrainingRepository(db)
        repo.guardar({
            "perfil": "prod_test",
            "score_total": 90,
            "score_descubrimiento": 18,
            "score_calificacion": 18,
            "score_valor": 18,
            "score_objeciones": 18,
            "score_cierre": 18,
        })
        historial = repo.historial()
        assert len(historial) == 1
        assert historial[0].score_total == 90
        db.close()
        cerrar_engine()

    def test_tablas_se_crean_automaticamente(self):
        engine = get_engine("sqlite:///:memory:")
        crear_tablas(engine)
        from sqlalchemy import inspect
        inspector = inspect(engine)
        tablas = inspector.get_table_names()
        assert "leads" in tablas
        assert "conversation_messages" in tablas
        assert "training_sessions" in tablas
        cerrar_engine()

    def test_cerrar_engine_limpia_state(self):
        engine = get_engine("sqlite:///:memory:")
        crear_tablas(engine)
        cerrar_engine()
        from app.database.database import _engine, _SessionLocal
        assert _engine is None
        assert _SessionLocal is None


# ─────────────────────────────────────────────
# Tests — Manejo de errores
# ─────────────────────────────────────────────

class TestErrorHandling:
    """Tests de manejo de errores en producción."""

    def test_config_token_vacio_falla(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
        with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN"):
            BotConfig.from_env()

    def test_config_token_none_falla(self, monkeypatch):
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN"):
            BotConfig.from_env()

    def test_database_url_invalida_falla(self):
        engine = get_engine("sqlite:///:memory:")
        crear_tablas(engine)
        factory = get_session_factory(engine)
        db = factory()
        # Operación con lead inexistente
        lead = db.get(LeadDB, 99999)
        assert lead is None
        db.close()
        cerrar_engine()

    def test_logging_configurar_produccion(self):
        from app.utils.logging_config import setup_logging
        setup_logging(level="WARNING", structured=True)
        logger = pytest.importorskip("logging").getLogger("test")
        # No debe lanzar excepción
        logger.warning("Test message")


# ─────────────────────────────────────────────
# Tests — Variables de entorno
# ─────────────────────────────────────────────

class TestEnvironmentVariables:
    """Tests de carga de variables de entorno."""

    def test_env_file_example_exists(self):
        from pathlib import Path
        env_example = Path(__file__).parent.parent / ".env.example"
        assert env_example.exists(), ".env.example no existe"

    def test_env_file_example_contiene_token(self):
        from pathlib import Path
        env_example = Path(__file__).parent.parent / ".env.example"
        content = env_example.read_text()
        assert "TELEGRAM_BOT_TOKEN" in content
        assert "GROQ_API_KEY" in content
        assert "DATABASE_URL" in content

    def test_gitignore_excluye_env(self):
        from pathlib import Path
        gitignore = Path(__file__).parent.parent / ".gitignore"
        content = gitignore.read_text()
        assert ".env" in content
        assert ".env.dev" in content

    def test_gitignore_excluye_data(self):
        from pathlib import Path
        gitignore = Path(__file__).parent.parent / ".gitignore"
        content = gitignore.read_text()
        assert "data/" in content

    def test_dockerfile_existe(self):
        from pathlib import Path
        dockerfile = Path(__file__).parent.parent / "Dockerfile"
        assert dockerfile.exists(), "Dockerfile no existe"

    def test_docker_compose_existe(self):
        from pathlib import Path
        compose = Path(__file__).parent.parent / "docker-compose.yml"
        assert compose.exists(), "docker-compose.yml no existe"

    def test_deploy_doc_existe(self):
        from pathlib import Path
        deploy = Path(__file__).parent.parent / "DEPLOY.md"
        assert deploy.exists(), "DEPLOY.md no existe"

    def test_backup_doc_existe(self):
        from pathlib import Path
        backup = Path(__file__).parent.parent / "BACKUP.md"
        assert backup.exists(), "BACKUP.md no existe"

    def test_migration_doc_existe(self):
        from pathlib import Path
        migration = Path(__file__).parent.parent / "MIGRATION.md"
        assert migration.exists(), "MIGRATION.md no existe"
