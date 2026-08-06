"""
Ganchos automáticos en grupos de Telegram.

Publica mensajes "gancho" educativos 4 veces al día en los horarios de
mayor actividad de Córdoba (08:30, 13:00, 18:30 y 21:30), alternando
entre distintos formatos (informativo, utilidad diaria, resolución de
problemas). Cada gancho invita a la interacción por privado, sin vender
directamente.

Los horarios se interpretan en la zona horaria de Córdoba
(America/Argentina/Cordoba).

El scheduler tolera que el servicio esté dormido (Render free tier): al
despertar envía el gancho más reciente cuyo horario ya pasó y que no haya
sido publicado hoy. El registro de lo enviado se persiste en la tabla
``grupo_hooks_enviados`` para no duplicar publicaciones entre reinicios.

Uso (en el lifespan de FastAPI):
    from app.telegram.group_hooks import GroupHookScheduler
    scheduler = GroupHookScheduler(token, group_chat_ids, horarios, habilitado)
    scheduler.iniciar()
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from app.telegram.grupos_db import _crear_factory, listar_grupos_activos

logger = logging.getLogger(__name__)

TZ_CORDOBA = "America/Argentina/Cordoba"

# ─────────────────────────────────────────
# Mensajes gancho
# ─────────────────────────────────────────

_GANCHO_INFORMATIVO = (
    "👋 ¡Hola a todos! Soy Sofía, el asistente de Servired. "
    "Muchos me preguntan si tenemos convenio con el Sanatorio Allende o el "
    "Hospital Privado. La respuesta es SÍ. 🤝\n\n"
    "Si alguien tiene dudas sobre cobertura en Córdoba capital o el interior, "
    "escríbanme en privado y los ayudo sin compromiso."
)

_GANCHO_UTILIDAD_DIARIA = (
    "🌡️ Buen día, comunidad. Recuerden que con Servired tienen acceso a "
    "cobertura en países limítrofes.\n\n"
    "Si hoy te levantaste con fiebre o malestar y no sabés si ir a una "
    "guardia, podés escribirme a mí."
)

_GANCHO_RESOLUCION = (
    "📢 Atención: Muchos usuarios me han consultado sobre cómo hacer el "
    "cambio de obra social a prepaga si trabajan en relación de dependencia "
    "o monotributo.\n\n"
    "Si están en esa situación y quieren saber si pueden derivar sus aportes "
    "a Servired, escríbanme por privado y les explico el paso a paso."
)

# Variantes para el turno nocturno (rotan entre días).
_GANCHOS_NOCTURNOS = [
    (
        "🩺 Dato útil: la mayoría de las consultas médicas que hacemos durante "
        "el año se pueden hacer en una misma prepaga sin pagar de más.\n\n"
        "Si te interesa saber qué cobertura tenés disponible según tu plan o "
        "situación laboral, escribime por privado."
    ),
    (
        "👨‍👩‍👧 ¿Sabías que con Servired podés incluir a tu familia en el mismo "
        "plan? Cónyuge e hijos pueden sumarse a tu cobertura.\n\n"
        "Si querés saber cuánto saldría la cobertura familiar para vos, "
        "escribime por privado y lo vemos."
    ),
    (
        "💊 Recordá que con Servired accedés a descuentos en farmacias "
        "adheridas de Córdoba e interior.\n\n"
        "Si querés saber si tu farmacia está adherida o cómo funciona, "
        "escribime por privado y te cuento."
    ),
]

# Cada horario tiene una lista de ganchos que rotan por día.
# (con un único elemento, el gancho es fijo; con varios, rota.)
_GANCHOS_POR_HORARIO: dict[str, list[str]] = {
    "08:30": [_GANCHO_INFORMATIVO],
    "13:00": [_GANCHO_UTILIDAD_DIARIA],
    "18:30": [_GANCHO_RESOLUCION],
    "21:30": _GANCHOS_NOCTURNOS,
}


def _firma(username: str) -> str:
    """Línea final opcional con el usuario del bot."""
    if not username:
        return ""
    return f"\n\nSofía — @{username}"


def elegir_gancho(horario: str, fecha: datetime) -> str:
    """Elige el gancho a publicar para un horario y fecha dados (rotativo)."""
    opciones = _GANCHOS_POR_HORARIO.get(horario)
    if not opciones:
        opciones = [_GANCHO_INFORMATIVO]
    indice = fecha.toordinal() % len(opciones)
    return opciones[indice]


class GroupHookScheduler:
    """
    Programa y publica los ganchos diarios en los grupos registrados.

    El loop revisa la hora cada 30 segundos. Cuando un horario ya pasó y
    todavía no fue publicado hoy, envía el más reciente de ellos una única
    vez (persistido en DB), aunque el proceso haya estado dormido durante
    horas.
    """

    def __init__(
        self,
        token: str,
        group_chat_ids: list[int] | tuple[int, ...] = (),
        horarios: list[str] | tuple[str, ...] = ("08:30", "13:00", "18:30", "21:30"),
        habilitado: bool = True,
        username: str = "",
        reloj: Optional[callable] = None,
        factory: Optional[callable] = None,
    ) -> None:
        self._token = token
        self._group_chat_ids = list(group_chat_ids or [])
        self._horarios = tuple(horarios or ())
        self._habilitado = habilitado
        self._username = username or ""
        self._reloj = reloj or (lambda: datetime.now(ZoneInfo(TZ_CORDOBA)))
        self._factory = factory
        self._task: Optional[asyncio.Task] = None
        self._enviados: dict[str, set[str]] = {}
        self._enviado_ultimo: Optional[dict] = None

    @property
    def habilitado(self) -> bool:
        return self._habilitado

    def iniciar(self) -> None:
        """Arranca el loop de ganchos en el event loop actual."""
        if not self._habilitado:
            logger.info("[HOOKS] Ganchos desactivados por configuración")
            return
        if not self._token:
            logger.warning("[HOOKS] Sin token — ganchos no iniciados")
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning("[HOOKS] No hay event loop corriendo — ganchos no iniciados")
            return
        self._task = loop.create_task(self._loop())
        logger.info("[HOOKS] Scheduler iniciado (horarios=%s)", ", ".join(self._horarios))

    async def detener(self) -> None:
        """Cancela el loop de ganchos."""
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
            logger.info("[HOOKS] Scheduler detenido")

    # ─────────────────────────────────────────
    # Loop principal
    # ─────────────────────────────────────────

    async def _loop(self) -> None:
        logger.info("[HOOKS] Loop de ganchos corriendo")
        while True:
            try:
                await self._ejecutar_si_corresponde()
            except Exception as exc:
                logger.warning("[HOOKS] Error en loop: %s", exc)
            await asyncio.sleep(30)

    async def _ejecutar_si_corresponde(self) -> None:
        """Envía el gancho más reciente cuyo horario ya pasó y no fue enviado."""
        if not self._habilitado:
            return
        ahora = self._reloj()
        fecha = ahora.strftime("%Y-%m-%d")
        enviados_hoy = self._enviados.setdefault(fecha, set())

        candidatos = [
            horario
            for horario in self._horarios
            if horario not in enviados_hoy
            and self._es_horario_pasado(horario, ahora)
            and not self._ya_enviado(fecha, horario)
        ]
        if not candidatos:
            return

        # Solo el más reciente: evita encadenar todos los ganchos atrasados
        # de golpe si el proceso estuvo dormido varias horas.
        horario = max(candidatos)
        texto = elegir_gancho(horario, ahora)
        await self._enviar_gancho(texto)
        enviados_hoy.add(horario)
        self._marcar_enviado(fecha, horario)
        self._enviado_ultimo = {"horario": horario, "texto": texto}

    def _es_horario_pasado(self, horario: str, ahora: datetime) -> bool:
        """True si el horario ya llegó (o pasó) en la fecha actual."""
        try:
            hora, minu = map(int, horario.split(":"))
        except ValueError:
            return False
        inicio = ahora.replace(hour=hora, minute=minu, second=0, microsecond=0)
        return ahora >= inicio

    # ─────────────────────────────────────────
    # Persistencia de envíos (evita duplicados entre reinicios)
    # ─────────────────────────────────────────

    def _sesion(self):
        """Session factory: la inyectada en tests o la de la app."""
        if self._factory is not None:
            return self._factory()
        return _crear_factory()()

    def _ya_enviado(self, fecha: str, horario: str) -> bool:
        try:
            from sqlalchemy import select

            from app.database.models import GrupoHookEnviadoDB

            db = self._sesion()
            try:
                fila = db.execute(
                    select(GrupoHookEnviadoDB).where(
                        GrupoHookEnviadoDB.fecha == fecha,
                        GrupoHookEnviadoDB.horario == horario,
                    )
                ).scalar_one_or_none()
                return fila is not None
            finally:
                db.close()
        except Exception as exc:
            logger.debug("[HOOKS] _ya_enviado falló (%s %s): %s", fecha, horario, exc)
            return False

    def _marcar_enviado(self, fecha: str, horario: str) -> None:
        try:
            from app.database.models import GrupoHookEnviadoDB

            db = self._sesion()
            try:
                db.add(GrupoHookEnviadoDB(fecha=fecha, horario=horario))
                db.commit()
            finally:
                db.close()
        except Exception as exc:
            logger.warning(
                "[HOOKS] No se pudo registrar envío %s %s: %s", fecha, horario, exc
            )

    # ─────────────────────────────────────────
    # Envío
    # ─────────────────────────────────────────

    def _grupos_destino(self) -> list[int]:
        """Chat_ids destino: env estáticos + grupos activos de la DB."""
        ids = set(self._group_chat_ids)
        try:
            ids.update(listar_grupos_activos())
        except Exception as exc:
            logger.debug("[HOOKS] Sin grupos de DB: %s", exc)
        return sorted(ids)

    async def _enviar_gancho(self, texto: str) -> None:
        from telegram import Bot

        chat_ids = self._grupos_destino()
        if not chat_ids:
            logger.info("[HOOKS] Sin grupos destino — gancho no enviado")
            return

        mensaje = f"{texto}{_firma(self._username)}"
        bot = Bot(token=self._token)
        for chat_id in chat_ids:
            try:
                await bot.send_message(
                    chat_id=chat_id,
                    text=mensaje,
                    disable_web_page_preview=True,
                )
                logger.info("[HOOKS] Gancho enviado a chat_id=%s", chat_id)
            except Exception as exc:
                logger.warning("[HOOKS] Error enviando a chat_id=%s: %s", chat_id, exc)
            await asyncio.sleep(1)
