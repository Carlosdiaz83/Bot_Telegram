"""
Tests Sprint 26 — Grupos de Telegram: escucha + ganchos automáticos.

Cubre:
    - Registro de grupos en DB (alta/baja del bot)
    - Detección de relevancia de mensajes de grupo
    - Respuestas con llamado a la acción basadas en conocimiento
    - Elección y rotación de ganchos por horario
    - Ventana de envío del scheduler (una vez por día)
    - Parsing de configuración (chat_ids y horarios)
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine

from app.config.settings import _parse_group_ids, _parse_horarios
from app.services.conversation_manager import ConversationManager
from app.telegram.group_hooks import (
    TZ_CORDOBA,
    GroupHookScheduler,
    _GANCHOS_POR_HORARIO,
    elegir_gancho,
)
from app.telegram.grupos_db import (
    desactivar_grupo,
    listar_grupos_activos,
    registrar_grupo,
)


# ─────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────

@pytest.fixture
def factory_grupos():
    """Session factory SQLite temporal para la tabla de grupos."""
    from app.database.database import crear_tablas, get_session_factory

    engine = create_engine("sqlite:///:memory:")
    crear_tablas(engine)
    return get_session_factory(engine)


@pytest.fixture
def manager():
    """ConversationManager sin DB ni IA (con prestaciones + knowledge)."""
    return ConversationManager(ai_service=None, database_url=None)


def _fecha(hora: str) -> datetime:
    hh, mm = map(int, hora.split(":"))
    return datetime(2026, 8, 3, hh, mm, 0, tzinfo=ZoneInfo(TZ_CORDOBA))


# ─────────────────────────────────────────
# Registro de grupos en DB
# ─────────────────────────────────────────

class TestGruposDB:
    def test_registrar_y_listar(self, factory_grupos):
        assert registrar_grupo(-100111, "Grupo A", factory=factory_grupos)
        assert registrar_grupo(-100222, "Grupo B", factory=factory_grupos)

        activos = listar_grupos_activos(factory=factory_grupos)
        assert -100111 in activos
        assert -100222 in activos

    def test_registrar_mismo_grupo_no_duplica(self, factory_grupos):
        registrar_grupo(-100333, "Grupo C", factory=factory_grupos)
        registrar_grupo(-100333, "Grupo C", factory=factory_grupos)

        activos = listar_grupos_activos(factory=factory_grupos)
        assert activos.count(-100333) == 1

    def test_desactivar_quita_del_listado(self, factory_grupos):
        registrar_grupo(-100444, "Grupo D", factory=factory_grupos)
        assert desactivar_grupo(-100444, factory=factory_grupos)

        assert -100444 not in listar_grupos_activos(factory=factory_grupos)

    def test_registrar_con_db_no_disponible_no_rompe(self):
        # Sin factory, usa la DB de la app (puede no existir) — no debe lanzar.
        assert isinstance(registrar_grupo(999999999, "x"), bool)


# ─────────────────────────────────────────
# Detección de relevancia
# ─────────────────────────────────────────

class TestRelevancia:
    def test_relevante_obra_social(self, manager):
        from app.telegram.group_listener import GroupListener

        listener = GroupListener(manager=manager)
        assert listener.es_relevante("¿Alguien sabe si conviene cambiar de obra social?")
        assert listener.es_relevante("tengo dudas con el monotributo")
        assert listener.es_relevante("¿cubren odontología?")
        assert listener.es_relevante("recomiendan una clínica en Córdoba")

    def test_no_relevante(self, manager):
        from app.telegram.group_listener import GroupListener

        listener = GroupListener(manager=manager)
        assert not listener.es_relevante("buenas noches gente, qué tal")
        assert not listener.es_relevante("vi un meme muy gracioso jaja")
        assert not listener.es_relevante("¿quién juega al fútbol el sábado?")

    def test_no_responde_mensajes_de_vendedores(self, manager):
        from app.telegram.group_listener import GroupListener

        listener = GroupListener(manager=manager)
        assert not listener.es_relevante("soy vendedor de servired, buen día")


# ─────────────────────────────────────────
# Respuestas con llamado a la acción
# ─────────────────────────────────────────

class TestRespuestas:
    def test_respuesta_odontologia(self, manager):
        from app.telegram.group_listener import GroupListener

        listener = GroupListener(manager=manager)
        respuesta = listener._generar_respuesta("¿cubren odontología?", "sofiabot")
        assert "odont" in respuesta.lower()
        assert "@sofiabot" in respuesta
        assert "privado" in respuesta

    def test_respuesta_derivacion_aportes(self, manager):
        from app.telegram.group_listener import GroupListener

        listener = GroupListener(manager=manager)
        respuesta = listener._generar_respuesta(
            "¿puedo derivar mis aportes de obra social a Servired?", ""
        )
        assert "derivar" in respuesta
        assert "privado" in respuesta

    def test_respuesta_sanatorio(self, manager):
        from app.telegram.group_listener import GroupListener

        listener = GroupListener(manager=manager)
        respuesta = listener._generar_respuesta(
            "¿tienen convenio con el sanatorio allende?", "sofiabot"
        )
        assert respuesta.strip()
        assert "privado" in respuesta

    def test_mensaje_irrelevante_no_genera_respuesta(self, manager):
        from app.telegram.group_listener import GroupListener

        listener = GroupListener(manager=manager)
        assert not listener.es_relevante("qué buen partido ayer")


# ─────────────────────────────────────────
# Elección y rotación de ganchos
# ─────────────────────────────────────────

class TestGanchos:
    def test_horarios_definidos(self):
        assert set(_GANCHOS_POR_HORARIO.keys()) == {"08:30", "13:00", "18:30", "21:30"}

    def test_informativo_fijo_en_08_30(self):
        texto = elegir_gancho("08:30", _fecha("08:30"))
        assert "Soy Sofía" in texto or "asistente de Servired" in texto
        assert "privado" in texto

    def test_utilidad_en_13_00(self):
        texto = elegir_gancho("13:00", _fecha("13:00"))
        assert "guardia" in texto

    def test_resolucion_en_18_30(self):
        texto = elegir_gancho("18:30", _fecha("18:30"))
        assert "obra social" in texto or "monotributo" in texto

    def test_nocturno_rota_entre_dias(self):
        d1 = elegir_gancho("21:30", _fecha("21:30"))
        d2 = elegir_gancho("21:30", _fecha("21:30").replace(day=4))
        d3 = elegir_gancho("21:30", _fecha("21:30").replace(day=5))
        assert d1 != d2 or d2 != d3


# ─────────────────────────────────────────
# Scheduler
# ─────────────────────────────────────────

class _SchedulerConRegistro(GroupHookScheduler):
    def __init__(self, *args, **kwargs):
        self.enviados: list[str] = []
        super().__init__(*args, **kwargs)

    async def _enviar_gancho(self, texto: str) -> None:
        self.enviados.append(texto)


class TestScheduler:
    def test_envia_dentro_de_la_ventana_una_vez(self):
        import asyncio

        sched = _SchedulerConRegistro(
            token="token",
            group_chat_ids=[-1001],
            habilitado=True,
            reloj=lambda: _fecha("08:45"),
        )
        asyncio.run(sched._ejecutar_si_corresponde())
        asyncio.run(sched._ejecutar_si_corresponde())

        assert len(sched.enviados) == 1
        assert "privado" in sched.enviados[0]

    def test_no_envia_fuera_de_la_ventana(self):
        import asyncio

        sched = _SchedulerConRegistro(
            token="token",
            group_chat_ids=[-1001],
            habilitado=True,
            reloj=lambda: _fecha("10:00"),
        )
        asyncio.run(sched._ejecutar_si_corresponde())
        assert sched.enviados == []

    def test_deshabilitado_no_envia(self):
        import asyncio

        sched = _SchedulerConRegistro(
            token="token",
            group_chat_ids=[-1001],
            habilitado=False,
            reloj=lambda: _fecha("08:45"),
        )
        asyncio.run(sched._ejecutar_si_corresponde())
        assert sched.enviados == []

    def test_en_ventana(self):
        sched = GroupHookScheduler(token="t", habilitado=True)
        assert sched._en_ventana("08:30", _fecha("08:45"))
        assert sched._en_ventana("08:30", _fecha("08:30"))
        assert not sched._en_ventana("08:30", _fecha("09:45"))
        assert not sched._en_ventana("08:30", _fecha("08:00"))

    def test_grupos_destino_incluye_db_y_env(self, factory_grupos):
        import asyncio
        from unittest.mock import patch

        registrar_grupo(-100999, "DB Group", factory=factory_grupos)
        sched = _SchedulerConRegistro(
            token="token",
            group_chat_ids=[-1001],
            habilitado=True,
            reloj=lambda: _fecha("08:45"),
        )
        with patch("app.telegram.group_hooks.listar_grupos_activos",
                   return_value=[-100999]):
            asyncio.run(sched._ejecutar_si_corresponde())
        assert len(sched.enviados) == 1


# ─────────────────────────────────────────
# Configuración
# ─────────────────────────────────────────

class TestConfig:
    def test_parse_group_ids(self):
        assert _parse_group_ids("") == ()
        assert _parse_group_ids("-1001, -1002") == (-1001, -1002)
        assert _parse_group_ids("abc,-1003") == (-1003,)

    def test_parse_horarios(self):
        assert _parse_horarios("") == ()
        assert _parse_horarios("13:00,08:30,18:30,21:30") == ("08:30", "13:00", "18:30", "21:30")
        assert _parse_horarios("malo,08:30") == ("08:30",)
