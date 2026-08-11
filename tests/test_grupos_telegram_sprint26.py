"""
Tests Sprint 26 — Grupos de Telegram: escucha + ganchos automáticos.

Cubre:
    - Registro de grupos en DB (alta/baja del bot)
    - Auto-registro del grupo ante cualquier mensaje escuchado
    - Detección de relevancia de mensajes de grupo
    - Respuestas con llamado a la acción basadas en conocimiento
    - Elección y rotación de ganchos por horario
    - Catch-up del scheduler (envía el gancho atrasado al despertar)
    - Persistencia de envíos (no duplica entre reinicios)
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
    _GANCHO_INVITACION,
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

    def test_registrar_con_db_no_disponible_no_rompe(self, monkeypatch):
        # La DB no está disponible: no debe lanzar y debe devolver False.
        # No se toca la DB real de la app (evita contaminar health_advisor.db).
        import app.telegram.grupos_db as gdb

        def _boom():
            raise RuntimeError("db no disponible")

        monkeypatch.setattr(gdb, "_crear_factory", _boom)
        assert registrar_grupo(999999999, "x") is False


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
        # 2026-08-04 es índice par → se publica el gancho educativo.
        texto = elegir_gancho("08:30", _fecha("08:30").replace(day=4))
        assert "Soy Sofía" in texto or "asistente de Servired" in texto
        assert "privado" in texto

    def test_utilidad_en_13_00(self):
        texto = elegir_gancho("13:00", _fecha("13:00").replace(day=4))
        assert "guardia" in texto

    def test_resolucion_en_18_30(self):
        texto = elegir_gancho("18:30", _fecha("18:30").replace(day=4))
        assert "obra social" in texto or "monotributo" in texto

    def test_nocturno_rota_entre_dias(self):
        d1 = elegir_gancho("21:30", _fecha("21:30").replace(day=4))
        d2 = elegir_gancho("21:30", _fecha("21:30").replace(day=5))
        d3 = elegir_gancho("21:30", _fecha("21:30").replace(day=6))
        assert d1 != d2 or d2 != d3

    def test_invitacion_rota_en_todos_los_horarios(self):
        # 2026-08-03 es índice impar → en TODOS los horarios sale la invitación.
        for hora in ("08:30", "13:00", "18:30", "21:30"):
            texto = elegir_gancho(hora, _fecha(hora))
            assert "¿Querés que responda consultas de cobertura" in texto
            assert "serviredasesorbot" in texto
            assert "startgroup=members" in texto

    def test_invitacion_incluye_link_agregar(self):
        assert "https://t.me/serviredasesorbot?startgroup=members" in _GANCHO_INVITACION

    def test_dias_educativos_no_envian_invitacion(self):
        # 2026-08-04 es índice par → mensajes educativos, sin invitación.
        for hora in ("08:30", "13:00", "18:30"):
            texto = elegir_gancho(hora, _fecha(hora).replace(day=4))
            assert "startgroup=members" not in texto


# ─────────────────────────────────────────
# Scheduler
# ─────────────────────────────────────────

class _SchedulerConRegistro(GroupHookScheduler):
    def __init__(self, *args, **kwargs):
        self.enviados: list[str] = []
        super().__init__(*args, **kwargs)

    async def _enviar_gancho(self, texto: str) -> bool:
        self.enviados.append(texto)
        return True


class TestScheduler:
    def test_envia_el_gancho_pasado_una_vez(self, factory_grupos):
        import asyncio

        sched = _SchedulerConRegistro(
            token="token",
            group_chat_ids=[-1001],
            habilitado=True,
            reloj=lambda: _fecha("08:45").replace(day=4),
            factory=factory_grupos,
        )
        asyncio.run(sched._ejecutar_si_corresponde())
        asyncio.run(sched._ejecutar_si_corresponde())

        assert len(sched.enviados) == 1
        assert "privado" in sched.enviados[0]

    def test_no_envia_antes_del_primer_horario(self, factory_grupos):
        import asyncio

        sched = _SchedulerConRegistro(
            token="token",
            group_chat_ids=[-1001],
            habilitado=True,
            reloj=lambda: _fecha("08:00"),
            factory=factory_grupos,
        )
        asyncio.run(sched._ejecutar_si_corresponde())
        assert sched.enviados == []

    def test_envia_atrasado_al_despertar(self, factory_grupos):
        """Si el proceso estuvo dormido, envía el gancho cuyo horario pasó."""
        import asyncio

        sched = _SchedulerConRegistro(
            token="token",
            group_chat_ids=[-1001],
            habilitado=True,
            reloj=lambda: _fecha("10:00").replace(day=4),
            factory=factory_grupos,
        )
        asyncio.run(sched._ejecutar_si_corresponde())
        assert len(sched.enviados) == 1
        assert "Soy Sofía" in sched.enviados[0] or "asistente de Servired" in sched.enviados[0]

    def test_solo_envia_el_mas_reciente(self, factory_grupos):
        """Con varios horarios atrasados, solo publica el último (sin spam)."""
        import asyncio

        sched = _SchedulerConRegistro(
            token="token",
            group_chat_ids=[-1001],
            habilitado=True,
            reloj=lambda: _fecha("16:00").replace(day=4),
            factory=factory_grupos,
        )
        asyncio.run(sched._ejecutar_si_corresponde())
        assert len(sched.enviados) == 1
        assert "guardia" in sched.enviados[0]

    def test_deshabilitado_no_envia(self, factory_grupos):
        import asyncio

        sched = _SchedulerConRegistro(
            token="token",
            group_chat_ids=[-1001],
            habilitado=False,
            reloj=lambda: _fecha("08:45"),
            factory=factory_grupos,
        )
        asyncio.run(sched._ejecutar_si_corresponde())
        assert sched.enviados == []

    def test_es_horario_pasado(self):
        sched = GroupHookScheduler(token="t", habilitado=True)
        assert sched._es_horario_pasado("08:30", _fecha("08:45"))
        assert sched._es_horario_pasado("08:30", _fecha("08:30"))
        assert sched._es_horario_pasado("08:30", _fecha("09:45"))
        assert not sched._es_horario_pasado("08:30", _fecha("08:00"))

    def test_grupos_destino_incluye_db_y_env(self, factory_grupos):
        import asyncio
        from unittest.mock import patch

        registrar_grupo(-100999, "DB Group", factory=factory_grupos)
        sched = _SchedulerConRegistro(
            token="token",
            group_chat_ids=[-1001],
            habilitado=True,
            reloj=lambda: _fecha("08:45"),
            factory=factory_grupos,
        )
        with patch("app.telegram.group_hooks.listar_grupos_activos",
                   return_value=[-100999]):
            asyncio.run(sched._ejecutar_si_corresponde())
        assert len(sched.enviados) == 1

    def test_persistencia_evita_reenvio_entre_reinicios(self, factory_grupos):
        """El envío persiste en DB: un proceso nuevo no repite el gancho."""
        import asyncio

        sched1 = _SchedulerConRegistro(
            token="token",
            group_chat_ids=[-1001],
            habilitado=True,
            reloj=lambda: _fecha("08:45"),
            factory=factory_grupos,
        )
        asyncio.run(sched1._ejecutar_si_corresponde())
        assert len(sched1.enviados) == 1

        sched2 = _SchedulerConRegistro(
            token="token",
            group_chat_ids=[-1001],
            habilitado=True,
            reloj=lambda: _fecha("09:00"),
            factory=factory_grupos,
        )
        asyncio.run(sched2._ejecutar_si_corresponde())
        assert sched2.enviados == []


# ─────────────────────────────────────────
# Auto-registro de grupos al escuchar mensajes
# ─────────────────────────────────────────

class TestAutoRegistro:
    def _fake_update(self, chat_id: int, texto: str, chat_type: str = "group"):
        from types import SimpleNamespace

        chat = SimpleNamespace(id=chat_id, type=chat_type, title="Grupo Test")
        user = SimpleNamespace(is_bot=False, first_name="Juan")
        message = SimpleNamespace(text=texto, from_user=user, reply_to_message=None)
        return SimpleNamespace(effective_chat=chat, message=message, my_chat_member=None)

    def _listener(self, monkeypatch, factory_grupos):
        import app.telegram.group_listener as gl_mod
        from app.telegram.group_listener import GroupListener

        registros = []

        def fake_registrar(chat_id, titulo="", factory=None):
            registros.append((chat_id, titulo))
            return registrar_grupo(chat_id, titulo, factory=factory_grupos)

        monkeypatch.setattr(gl_mod, "registrar_grupo", fake_registrar)
        listener = GroupListener(manager=None)
        return listener, registros

    def test_registra_grupo_con_mensaje_irrelevante(self, monkeypatch, factory_grupos):
        import asyncio
        from types import SimpleNamespace

        listener, registros = self._listener(monkeypatch, factory_grupos)
        update = self._fake_update(-100777, "buen día gente")
        context = SimpleNamespace(bot=SimpleNamespace(username="sofiabot", id=1))

        asyncio.run(listener.handle_group_message(update, context))
        assert registros == [(-100777, "Grupo Test")]

    def test_registra_una_sola_vez_por_grupo(self, monkeypatch, factory_grupos):
        import asyncio
        from types import SimpleNamespace

        listener, registros = self._listener(monkeypatch, factory_grupos)
        context = SimpleNamespace(bot=SimpleNamespace(username="sofiabot", id=1))

        asyncio.run(listener.handle_group_message(
            self._fake_update(-100777, "¿quién juega hoy?"), context))
        asyncio.run(listener.handle_group_message(
            self._fake_update(-100777, "¿alguien vio el partido?"), context))
        assert len(registros) == 1


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
