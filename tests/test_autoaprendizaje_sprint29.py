"""
Tests Sprint 29 — Ciclo de auto-mejora de Sofía.

Cubre:
    1. Memoria persistente (SofiaMemoryService + SofiaMemoryRepository):
       se guarda por chat y se puede re-leer.
    2. REGLA DE VENDEDOR: la memoria nunca se escribe ni se mezcla con
       las cotizaciones de un vendedor.
    3. Lecciones aprendidas (LessonsService): sembrado base, dedupe,
       toggle, votos, extracción desde errores de entrenamiento e
       inyección en el prompt.
    4. AutoTrainer: ciclo completo + scheduler que no repite dentro del
       intervalo y arranca si el último entrenamiento está obsoleto.
    5. Panel: rutas /lecciones y /evolucion responden.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.database import crear_tablas
from app.database.models import TrainingSessionDB
from app.database.repository import SofiaMemoryRepository
from app.models.lead import (
    EstadoComercial,
    GrupoFamiliar,
    InteresDetectado,
    Lead,
    NecesidadPrincipal,
    PrioridadCliente,
    TipoAfiliacion,
)
from app.services.conversation_manager import ConversationManager
from app.services.lessons_service import LessonsService
from app.services.memory_service import SofiaMemoryService
from app.services.session_manager import EtapaConversacion, UserSession


# ─────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────

@pytest.fixture
def engine(tmp_path):
    """Engine SQLite sobre archivo temporal (persiste entre sesiones)."""
    ruta = tmp_path / "sprint29.db"
    eng = create_engine(f"sqlite:///{ruta}")
    crear_tablas(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def db_factory(engine):
    """db_factory con sesiones sobre el mismo engine."""
    Session = sessionmaker(bind=engine)
    return Session


@pytest.fixture
def memoria_svc(db_factory):
    return SofiaMemoryService(db_factory)


@pytest.fixture
def lecciones_svc(db_factory):
    return LessonsService(db_factory)


def _lead(**kwargs) -> Lead:
    """Lead de dominio mínimo para los tests de memoria."""
    base = dict(
        lead_id="777",
        nombre="Carlos",
        edad=40,
        localidad="Córdoba",
        tipo_afiliacion=TipoAfiliacion.MONOTRIBUTO,
        grupo_familiar=GrupoFamiliar(solo=True),
        prioridad_cliente=PrioridadCliente.ECONOMICO,
        interes_detectado=InteresDetectado.AFILIACION,
        necesidad_principal=NecesidadPrincipal.COBERTURA_FAMILIAR,
        estado_comercial=EstadoComercial.NUEVO,
    )
    base.update(kwargs)
    return Lead(**base)


def _session(**kwargs) -> UserSession:
    s = UserSession(telegram_id=kwargs.get("telegram_id", 777))
    s.etapa = kwargs.get("etapa", EtapaConversacion.ESPERANDO_NOMBRE)
    s.es_vendedor = kwargs.get("es_vendedor", False)
    s._ultimo_mensaje = kwargs.get("ultimo_mensaje", "hola")
    return s


def _add_training(db, *, horas_atras: float = 0.0, errores=None):
    """Inserta una sesión de entrenamiento de ejemplo."""
    db.add(TrainingSessionDB(
        perfil_cliente="cliente_frio",
        score_total=40,
        errores_detectados=json.dumps(errores or []),
        recomendaciones=json.dumps([]),
        creado=datetime.now(timezone.utc) - timedelta(hours=horas_atras),
    ))
    db.commit()


# ─────────────────────────────────────────
# Memoria persistente
# ─────────────────────────────────────────

class TestMemoriaPersistente:
    def test_guardar_y_cargar(self, memoria_svc):
        memoria_svc.guardar_desde_sesion(777, _lead(), _session(ultimo_mensaje="es muy caro"))
        datos = memoria_svc.cargar(777)
        assert datos is not None
        assert datos["datos_clave"]["nombre"] == "Carlos"
        assert datos["datos_clave"]["localidad"] == "Córdoba"
        assert datos["datos_clave"]["tipo_afiliacion"] == "monotributo"
        assert datos["ultimo_tema"] == "cobertura_familiar"
        assert datos["ultima_etapa"] == "esperando_nombre"
        assert datos["cantidad_conversaciones"] >= 1

    def test_objeciones_detectadas(self, memoria_svc):
        memoria_svc.guardar_desde_sesion(1, _lead(), _session(ultimo_mensaje="no llego, es muy caro"))
        datos = memoria_svc.cargar(1)
        assert "precio" in datos["objeciones"]

    def test_objeciones_no_se_duplican(self, memoria_svc):
        for _ in range(3):
            memoria_svc.guardar_desde_sesion(2, _lead(), _session(ultimo_mensaje="es muy caro"))
        datos = memoria_svc.cargar(2)
        assert datos["objeciones"].count("precio") == 1

    def test_intereses_acumulados(self, memoria_svc):
        memoria_svc.guardar_desde_sesion(3, _lead(), _session())
        datos = memoria_svc.cargar(3)
        assert "afiliacion" in datos["intereses"]

    def test_resumen_para_llm(self, memoria_svc):
        memoria_svc.guardar_desde_sesion(4, _lead(), _session(ultimo_mensaje="es muy caro"))
        texto = memoria_svc.resumen_para_llm(4)
        assert "Carlos" in texto
        assert "precio" in texto
        assert "monotributo" in texto

    def test_resumen_vacio_sin_memoria(self, memoria_svc):
        assert memoria_svc.resumen_para_llm(99999) == ""

    def test_sin_datos_no_escribe(self, memoria_svc):
        memoria_svc.guardar_desde_sesion(5, None, _session())
        assert memoria_svc.cargar(5) is None

    def test_vendedor_no_escribe_memoria(self, memoria_svc):
        memoria_svc.guardar_desde_sesion(
            6, _lead(), _session(es_vendedor=True, ultimo_mensaje="es muy caro")
        )
        assert memoria_svc.cargar(6) is None


# ─────────────────────────────────────────
# Repositorio de memoria
# ─────────────────────────────────────────

class TestSofiaMemoryRepository:
    def test_crud(self, db_factory):
        db = db_factory()
        try:
            repo = SofiaMemoryRepository(db)
            repo.guardar(
                50,
                resumen="test",
                datos_clave={"nombre": "Ana"},
                objeciones=["precio"],
                preferencias={"prioridad": "precio"},
            )
            memoria = repo.buscar(50)
            assert memoria is not None
            assert memoria.resumen == "test"
            d = repo.to_dict(memoria)
            assert d["datos_clave"] == {"nombre": "Ana"}
            assert d["objeciones"] == ["precio"]
            assert d["preferencias"] == {"prioridad": "precio"}
            assert d["cantidad_conversaciones"] == 1
        finally:
            db.close()

    def test_incrementa_conversaciones(self, db_factory):
        db = db_factory()
        try:
            repo = SofiaMemoryRepository(db)
            repo.guardar(51, resumen="a")
            repo.guardar(51, resumen="b")
            d = repo.to_dict(repo.buscar(51))
            assert d["cantidad_conversaciones"] == 1
            repo.guardar(51, resumen="c", incrementar_conversacion=True)
            d = repo.to_dict(repo.buscar(51))
            assert d["cantidad_conversaciones"] == 2
        finally:
            db.close()


# ─────────────────────────────────────────
# Lecciones aprendidas
# ─────────────────────────────────────────

class TestLecciones:
    def test_sembrar_base(self, lecciones_svc):
        lecciones_svc.sembrar_base()
        lecciones_svc.sembrar_base()  # dedupe: no duplica
        lecciones = lecciones_svc.listar()
        assert len(lecciones) == 4
        assert all(l.fuente == "base" for l in lecciones)

    def test_agregar_manual(self, lecciones_svc):
        l = lecciones_svc.agregar(
            "Test", "texto unico de prueba", categoria="tono", fuente="humano"
        )
        assert l.id is not None
        assert lecciones_svc.obtener(l.id) is not None

    def test_dedupe_por_texto(self, lecciones_svc):
        a = lecciones_svc.agregar("X", "mismo texto")
        b = lecciones_svc.agregar("Y", "mismo texto")
        assert a.id == b.id
        assert len(lecciones_svc.listar()) == 1

    def test_toggle(self, lecciones_svc):
        l = lecciones_svc.agregar("T", "texto toggle")
        lecciones_svc.activar(l.id, False)
        assert lecciones_svc.obtener(l.id).activo is False
        assert lecciones_svc.listar(activo=True) == []

    def test_votar(self, lecciones_svc):
        l = lecciones_svc.agregar("V", "texto votos")
        lecciones_svc.votar(l.id, 1)
        lecciones_svc.votar(l.id, 1)
        lecciones_svc.votar(l.id, -1)
        assert lecciones_svc.obtener(l.id).votos == 1

    def test_bloque_para_prompt(self, lecciones_svc):
        lecciones_svc.sembrar_base()
        bloque = lecciones_svc.bloque_para_prompt(limit=3)
        assert "Lecciones aprendidas" in bloque
        assert bloque.count("- ") >= 1

    def test_aplicar_al_prompt_inserta_system(self, lecciones_svc):
        lecciones_svc.sembrar_base()
        prompt = [
            {"role": "system", "content": "sos Sofía"},
            {"role": "user", "content": "hola"},
        ]
        lecciones_svc.aplicar_al_prompt(prompt, limit=2)
        assert prompt[1]["role"] == "system"
        assert "Lecciones aprendidas" in prompt[1]["content"]
        assert prompt[0]["content"] == "sos Sofía"
        assert prompt[2]["role"] == "user"

    def test_aplicar_al_prompt_sin_lecciones(self, lecciones_svc):
        prompt = [{"role": "system", "content": "sos Sofía"}]
        lecciones_svc.aplicar_al_prompt(prompt)
        assert len(prompt) == 1  # no inyecta nada

    def test_aplicar_al_prompt_registra_usos(self, lecciones_svc):
        lecciones_svc.sembrar_base()
        prompt = [{"role": "system", "content": "x"}, {"role": "user", "content": "y"}]
        lecciones_svc.aplicar_al_prompt(prompt, limit=2)
        total_usos = sum(l.usos or 0 for l in lecciones_svc.listar())
        assert total_usos >= 2

    def test_extraer_desde_entrenamiento(self, db_factory):
        db = db_factory()
        try:
            _add_training(db, errores=[
                {"tipo": "cotizacion_sin_diagnostico"},
                {"tipo": "descuento_inmediato"},
                "cotizacion_sin_diagnostico",
            ])
        finally:
            db.close()

        svc = LessonsService(db_factory)
        nuevas = svc.extraer_desde_entrenamiento()
        assert nuevas == 2
        textos = {l.texto for l in svc.listar()}
        assert any("tipo de afiliación" in t for t in textos)
        assert any("descuentos" in t for t in textos)

    def test_extraer_no_duplica(self, db_factory):
        db = db_factory()
        try:
            _add_training(db, errores=["cotizacion_sin_diagnostico"])
        finally:
            db.close()
        svc = LessonsService(db_factory)
        svc.extraer_desde_entrenamiento()
        assert svc.extraer_desde_entrenamiento() == 0


# ─────────────────────────────────────────
# Integración: ConversationManager persiste memoria
# ─────────────────────────────────────────

class TestMemoriaDesdeConversacion:
    @pytest.fixture
    def manager(self, tmp_path):
        ruta = tmp_path / "conv29.db"
        return ConversationManager(
            ai_service=None, database_url=f"sqlite:///{ruta}"
        )

    def test_cliente_guarda_memoria(self, manager):
        manager.procesar_mensaje(301, "hola")
        manager.procesar_mensaje(301, "Carlos")
        manager.procesar_mensaje(301, "para mi")
        manager.procesar_mensaje(301, "monotributo")
        manager.procesar_mensaje(301, "Córdoba")

        mem = SofiaMemoryService(manager._db_factory)
        datos = mem.cargar(301)
        assert datos is not None
        assert datos["datos_clave"]["nombre"] == "Carlos"
        assert datos["datos_clave"]["localidad"] == "Córdoba"

    def test_vendedor_no_contamina_memoria(self, manager):
        manager.procesar_mensaje(302, "soy vendedor")
        manager.procesar_mensaje(302, "monotributo")
        manager.procesar_mensaje(302, "Juan")
        manager.procesar_mensaje(302, "45 años, de Córdoba")
        manager.procesar_mensaje(302, "categoría B")
        manager.procesar_mensaje(302, "solo")

        mem = SofiaMemoryService(manager._db_factory)
        assert mem.cargar(302) is None


# ─────────────────────────────────────────
# AutoTrainer y scheduler
# ─────────────────────────────────────────

class TestAutoTrainer:
    def test_ejecutar_ciclo(self, engine, tmp_path):
        from app.services.auto_trainer import AutoTrainer
        trainer = AutoTrainer(
            database_url=f"sqlite:///{tmp_path / 'train29.db'}",
            db_factory=sessionmaker(bind=engine),
        )
        resumen = trainer.ejecutar_ciclo()
        assert resumen["entrenados"] > 0
        assert isinstance(resumen["lecciones_nuevas"], int)
        assert "evolucion" in resumen
        assert resumen["ts"]

    def test_ultimo_entrenamiento_obsoleto(self, db_factory):
        from app.services.auto_trainer import AutoTrainerScheduler
        db = db_factory()
        try:
            _add_training(db, horas_atras=48)
        finally:
            db.close()
        sched = AutoTrainerScheduler(
            database_url="sqlite:///:memory:",
            stale_horas=20.0,
            intervalo_horas=24.0,
            check_segundos=0.1,
        )
        assert sched._debe_ejecutar() is True

    def test_no_reenvia_dentro_del_intervalo(self, db_factory):
        from app.services.auto_trainer import AutoTrainerScheduler
        db = db_factory()
        try:
            _add_training(db, horas_atras=0)
        finally:
            db.close()
        sched = AutoTrainerScheduler(
            database_url="sqlite:///:memory:",
            stale_horas=20.0,
            intervalo_horas=24.0,
            check_segundos=0.1,
        )
        sched._ultima_ejecucion = datetime.now(timezone.utc)
        assert sched._debe_ejecutar() is False

    def test_sin_entrenamientos_debe_ejecutar(self):
        from app.services.auto_trainer import AutoTrainerScheduler
        sched = AutoTrainerScheduler(database_url="sqlite:///:memory:")
        sched._trainer._ultimo_entrenamiento = lambda: None
        assert sched._debe_ejecutar() is True


# ─────────────────────────────────────────
# Panel: lecciones
# ─────────────────────────────────────────

class TestPanelLecciones:
    @pytest.fixture
    def panel(self, tmp_path):
        from fastapi.testclient import TestClient
        from app.panel.app import create_panel_app
        ruta = tmp_path / "panel29.db"
        app = create_panel_app(database_url=f"sqlite:///{ruta}")
        return TestClient(app)

    def test_get_lecciones(self, panel):
        r = panel.get("/lecciones")
        assert r.status_code == 200
        assert "Lecciones Aprendidas" in r.text

    def test_get_evolucion(self, panel):
        r = panel.get("/evolucion")
        assert r.status_code == 200

    def test_lecciones_con_filtro(self, panel):
        r = panel.get("/lecciones?categoria=flujo")
        assert r.status_code == 200
