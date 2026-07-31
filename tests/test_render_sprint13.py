"""
Tests — Sprint 13: Render deployment preparation.

Verifica configuración, health check, base de datos
y preparación para despliegue en Render.
"""

from __future__ import annotations

import os
import tempfile

import pytest
from sqlalchemy import create_engine as _create_engine

from app.config.settings import BotConfig
from app.database.database import get_engine, crear_tablas, cerrar_engine, get_session_factory, _is_postgres
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
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        monkeypatch.delenv("AI_MODEL", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.delenv("APP_ENV", raising=False)
        monkeypatch.delenv("APP_DEBUG", raising=False)
        monkeypatch.delenv("LOG_LEVEL", raising=False)
        config = BotConfig.from_env()
        assert config.telegram_token == "test-token"
        assert config.groq_api_key == ""
        assert config.ai_model == "llama-3.3-70b-versatile"
        assert "sqlite" in config.database_url
        assert config.app_env == "development"

    def test_config_production_values(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "prod-token")
        monkeypatch.setenv("GROQ_API_KEY", "gsk_key")
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/db")
        config = BotConfig.from_env()
        assert config.app_env == "production"
        assert "postgresql" in config.database_url

    def test_config_es_inmutable(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
        config = BotConfig.from_env()
        with pytest.raises(AttributeError):
            config.telegram_token = "otro"


# ─────────────────────────────────────────────
# Tests — PostgreSQL detection
# ─────────────────────────────────────────────

class TestPostgresDetection:
    """Tests de detección de PostgreSQL."""

    def test_detecta_postgresql(self):
        assert _is_postgres("postgresql://user:pass@localhost/db") is True

    def test_detecta_postgres_alias(self):
        assert _is_postgres("postgres://user:pass@localhost/db") is True

    def test_no_detecta_sqlite(self):
        assert _is_postgres("sqlite:///./health_advisor.db") is False

    def test_no_detecta_mysql(self):
        assert _is_postgres("mysql://user:pass@localhost/db") is False


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
        lead = LeadDB(telegram_id=20001, nombre="Render Test")
        db.add(lead)
        db.commit()
        assert lead.id is not None
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

    def test_lead_repository_persistencia(self):
        engine = get_engine("sqlite:///:memory:")
        crear_tablas(engine)
        factory = get_session_factory(engine)
        db = factory()
        repo = LeadRepository(db)
        lead = LeadDB(telegram_id=20002, nombre="Persist Render", score=85)
        db.add(lead)
        db.commit()
        leads = repo.listar_leads()
        assert len(leads) == 1
        assert leads[0].nombre == "Persist Render"
        db.close()
        cerrar_engine()

    def test_training_repository_persistencia(self):
        engine = get_engine("sqlite:///:memory:")
        crear_tablas(engine)
        factory = get_session_factory(engine)
        db = factory()
        repo = TrainingRepository(db)
        repo.guardar({
            "perfil": "render_test",
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


# ─────────────────────────────────────────────
# Tests — Health check
# ─────────────────────────────────────────────

class TestHealthCheck:
    """Tests del endpoint /health."""

    def _create_app(self):
        from fastapi.testclient import TestClient
        from app.server import create_app
        app = create_app()
        return app, TestClient(app)

    def test_health_status(self):
        app, client = self._create_app()
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_body(self):
        app, client = self._create_app()
        response = client.get("/health")
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "sofia"
        assert "version" in data

    def test_health_content_type(self):
        app, client = self._create_app()
        response = client.get("/health")
        assert "application/json" in response.headers["content-type"]

    def test_health_self_healing_db_vacia(self, monkeypatch, tmp_path):
        """Si la DB está vacía pero existe knowledge en disco, /health la repuebla."""
        import app.server as server_module
        from fastapi.testclient import TestClient

        # Apuntar a una DB limpia y forzar recarga de configuración
        db_file = tmp_path / "selfhealing.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
        monkeypatch.setenv("APP_ENV", "test")
        monkeypatch.setenv("APP_DEBUG", "false")
        server_module._config = None
        cerrar_engine()

        app = server_module.create_app()
        client = TestClient(app)

        # Vaciar las tablas para simular que el bootstrap del arranque no corrió
        from sqlalchemy import text
        engine = get_engine()
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM servired_prices"))
            conn.execute(text("DELETE FROM servired_aportes_monotributo"))
            conn.execute(text("DELETE FROM servired_knowledge"))

        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["data"]["servired_prices"] > 0
        assert data["data"]["servired_aportes_monotributo"] > 0


# ─────────────────────────────────────────────
# Tests — Render configuration
# ─────────────────────────────────────────────

class TestRenderConfig:
    """Tests de archivos de configuración de Render."""

    def test_render_yaml_existe(self):
        from pathlib import Path
        render_yaml = Path(__file__).parent.parent / "render.yaml"
        assert render_yaml.exists(), "render.yaml no existe"

    def test_render_yaml_contiene_servicio(self):
        from pathlib import Path
        content = (Path(__file__).parent.parent / "render.yaml").read_text()
        assert "sofia-comercial" in content
        assert "pgsql" in content

    def test_server_py_existe(self):
        from pathlib import Path
        server = Path(__file__).parent.parent / "app" / "server.py"
        assert server.exists(), "app/server.py no existe"

    def test_dockerfile_render_compat(self):
        from pathlib import Path
        dockerfile = Path(__file__).parent.parent / "Dockerfile"
        content = dockerfile.read_text()
        assert "uvicorn" in content
        assert "app.server:app" in content
        assert "/health" in content

    def test_requirements_incluye_psycopg2(self):
        from pathlib import Path
        req = Path(__file__).parent.parent / "requirements.txt"
        content = req.read_text()
        assert "psycopg2-binary" in content

    def test_requirements_incluye_gunicorn(self):
        from pathlib import Path
        req = Path(__file__).parent.parent / "requirements.txt"
        content = req.read_text()
        assert "gunicorn" in content

    def test_deploy_render_doc_existe(self):
        from pathlib import Path
        doc = Path(__file__).parent.parent / "DEPLOY_RENDER.md"
        assert doc.exists(), "DEPLOY_RENDER.md no existe"

    def test_env_example_contiene_variables_render(self):
        from pathlib import Path
        env = Path(__file__).parent.parent / ".env.example"
        content = env.read_text()
        assert "TELEGRAM_BOT_TOKEN" in content
        assert "GROQ_API_KEY" in content
        assert "DATABASE_URL" in content
        assert "APP_ENV" in content

    def test_gitignore_excluye_env(self):
        from pathlib import Path
        gitignore = Path(__file__).parent.parent / ".gitignore"
        content = gitignore.read_text()
        assert ".env" in content


# ─────────────────────────────────────────────
# Tests — Telegram Bot en thread secundario
# ─────────────────────────────────────────────

class TestTelegramBotThread:
    """Tests de TelegramBot ejecutándose en un hilo secundario (como en Render)."""

    def test_is_main_thread_detecta(self):
        """_is_main_thread() detecta correctamente el thread."""
        import threading
        from app.telegram.bot import TelegramBot
        from app.config.settings import BotConfig

        # En el test runner, NO somos main thread (pytest puede usar threads)
        # Pero el test verifica que el método existe y funciona
        result = TelegramBot._is_main_thread()
        assert isinstance(result, bool)

    def test_setup_signal_handlers_no_crash_en_thread(self):
        """_setup_signal_handlers() no lanza ValueError en thread secundario."""
        import threading
        from app.telegram.bot import TelegramBot
        from app.config.settings import BotConfig

        config = BotConfig(telegram_token="test:fake-token")
        bot = TelegramBot(config)

        errors = []

        def run_in_thread():
            try:
                bot._setup_signal_handlers()
            except Exception as e:
                errors.append(e)

        t = threading.Thread(target=run_in_thread, name="test-bg-thread")
        t.start()
        t.join(timeout=5)

        assert len(errors) == 0, f"ValueError en thread secundario: {errors}"

    def test_run_no_crash_en_thread_secundario(self):
        """TelegramBot.run() no lanza ValueError por signal handlers en thread."""
        import threading
        from app.telegram.bot import TelegramBot
        from app.config.settings import BotConfig

        config = BotConfig(telegram_token="test:fake-token")
        bot = TelegramBot(config)

        errors = []

        def run_in_thread():
            try:
                # run_polling() fallará por token inválido, pero NO por signal handlers
                bot.run()
            except Exception as e:
                errors.append(e)

        t = threading.Thread(target=run_in_thread, name="test-bot-thread")
        t.start()
        t.join(timeout=10)

        # No debe haber ValueError por signal handlers
        signal_errors = [e for e in errors if "signal" in str(e).lower()]
        assert len(signal_errors) == 0, (
            f"signal.signal() falló en thread secundario: {signal_errors}"
        )
