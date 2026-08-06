"""
Escucha de grupos de Telegram.

El bot detecta mensajes relevantes (menciones o temas de salud / obra social),
responde brevemente en el grupo con información útil y un llamado a la acción
para que el prospecto lo contacte por privado.

También registra automáticamente los grupos donde el bot es agregado o
removido (update my_chat_member) en la tabla `grupos_telegram`.

Uso (registro en TelegramBot._register_handlers):
    from app.telegram.group_listener import GroupListener
    listener = GroupListener()
    application.add_handler(MessageHandler(filters.ChatType.GROUPS, listener.handle_group_message))
    application.add_handler(MyChatMemberHandler(listener.handle_my_chat_member))
"""

from __future__ import annotations

import logging
import time

from telegram import Update
from telegram.constants import ChatMemberStatus
from telegram.ext import ContextTypes

from app.telegram.grupos_db import desactivar_grupo, registrar_grupo

logger = logging.getLogger(__name__)

# Temas que importan a SERVIRED (salud / obra social / planes).
_PALABRAS_RELEVANTES: tuple[str, ...] = (
    "salud", "obra social", "obra_social", "prepaga", "servired",
    "medico", "medica", "médico", "médica",
    "clinica", "clínica", "hospital", "sanatorio", "guardia",
    "cobertura", "prestacion", "prestación", "cartilla",
    "farmacia", "medicamento", "remedio", "receta",
    "odontolog", "dental", "diente", "dientes", "ortodonc",
    "oculista", "oftalmolog", "optica", "óptica",
    "laboratorio", "analisis", "análisis", "estudios medicos",
    "internacion", "internación", "emergencia", "accidente",
    "embarazo", "parto", "maternidad", "psicolog", "psiquiatra",
    "deriv", "aporte", "aportes", "monotributo",
    "relacion de dependencia", "particular",
    "plan", "planes", "precio", "cuesta", "cuota", "afiliad",
)

# Mensajes que no ameritan respuesta aunque mencionen un tema.
_FRASES_IGNORAR: tuple[str, ...] = (
    "soy de servired", "trabajo en servired", "vendedor de servired",
    "vendo servired", "soy asesor de servired", "trabajo para servired",
)

# Segundos de espera entre respuestas automáticas por grupo.
_COOLDOWN_AUTO_SEG = 900   # 15 min
_COOLDOWN_MENCION_SEG = 120  # 2 min


class GroupListener:
    """Detecta mensajes relevantes en grupos y responde con un CTA."""

    def __init__(self, manager=None) -> None:
        self._manager = manager
        self._cooldown_auto: dict[int, float] = {}
        self._cooldown_mencion: dict[int, float] = {}
        self._grupos_registrados: set[int] = set()

    # ─────────────────────────────────────────
    # Dependencias
    # ─────────────────────────────────────────

    def _get_manager(self):
        """Obtiene el ConversationManager compartido (lazy)."""
        if self._manager is None:
            from app.telegram.handlers import get_manager

            self._manager = get_manager()
        return self._manager

    # ─────────────────────────────────────────
    # Relevancia
    # ─────────────────────────────────────────

    def es_relevante(self, texto: str) -> bool:
        """Detecta si un mensaje de grupo toca un tema de SERVIRED."""
        if not texto:
            return False
        t = texto.lower()
        if any(f in t for f in _FRASES_IGNORAR):
            return False
        return any(p in t for p in _PALABRAS_RELEVANTES)

    def _menciona_bot(self, texto: str, username: str) -> bool:
        if not username:
            return False
        return f"@{username.lower()}" in texto.lower()

    # ─────────────────────────────────────────
    # Respuestas
    # ─────────────────────────────────────────

    def _respuesta_conocimiento(self, texto: str) -> str:
        """Responde un tema concreto con conocimiento oficial de SERVIRED."""
        manager = self._get_manager()
        t = texto.lower()

        # 1. Preguntas específicas de prestaciones (cartilla/beneficios reales).
        try:
            resultado = manager._prestaciones.responder(texto)
            if resultado:
                respuesta, _categoria = resultado
                if respuesta:
                    return self._acortar(respuesta)
        except Exception as exc:
            logger.debug("[GRUPO] Prestaciones falló: %s", exc)

        # 2. Red médica / sanatorios / cartilla.
        if any(p in t for p in (
            "sanatorio", "hospital", "clinica", "clínica", "cartilla",
            "medico", "médico", "prestador", "allende", "privado",
            "red medica", "córdoba capital", "cordoba capital",
        )):
            try:
                red = manager.knowledge.obtener_red_medica()
                for linea in red.splitlines():
                    if "Córdoba" in linea or "Cordoba" in linea:
                        if "Sanatorio Allende" in linea:
                            limpia = linea.replace("Según plan:", "").strip()
                            return (
                                "Sí, tenemos convenio con clínicas y sanatorios "
                                "de Córdoba (Sanatorio Allende, Hospital Privado, "
                                f"Hospital Italiano, entre otros según el plan: {limpia})"
                            )
            except Exception as exc:
                logger.debug("[GRUPO] red_medica falló: %s", exc)

        # 3. Farmacias.
        if any(p in t for p in ("farmacia", "medicamento", "remedio", "receta")):
            return (
                "Contamos con una red de farmacias adheridas en Córdoba e "
                "interior con descuentos en medicamentos. ¿Querés conocer "
                "las farmacias más cercanas a tu zona?"
            )

        # 4. Odontología.
        if any(p in t for p in ("odontolog", "dental", "diente", "ortodonc")):
            return (
                "Sí, SERVIRED incluye cobertura odontológica (consultas, "
                "limpiezas y tratamientos) en todos los planes. Si te interesa, "
                "te paso los detalles por privado."
            )

        # 5. Emergencias / guardia.
        if any(p in t for p in ("emergencia", "guardia", "accidente", "urgencia")):
            return (
                "SERVIRED cubre emergencias las 24 hs los 7 días. Si tenés "
                "dudas sobre qué hacer ante una urgencia o dónde ir, "
                "escribime por privado y te oriento."
            )

        # 6. Derivación de aportes / obra social (relación de dependencia o monotributo).
        if any(p in t for p in ("deriv", "aporte", "cambio de obra", "obra social", "monotributo")):
            return (
                "Se puede derivar el aporte de obra social a SERVIRED tanto "
                "en relación de dependencia como siendo monotributista. "
                "El trámite es simple, pero depende de cada caso: escribime "
                "por privado y te explico el paso a paso sin compromiso."
            )

        # 7. Precios / cuotas.
        if any(p in t for p in ("precio", "cuesta", "cuota", "cuánto", "cuanto")):
            return (
                "Los valores dependen del plan, la edad y si es por aporte "
                "o particular. Si me escribís por privado, te armo una "
                "cotización personalizada sin compromiso."
            )

        return ""

    def _respuesta_generica(self, texto: str) -> str:
        """Respuesta genérica cuando el tema no tiene dato concreto."""
        return (
            "¡Buenas! Soy Sofía, la asistente de SERVIRED. Puedo ayudarte "
            "con dudas sobre cobertura, planes y afiliación."
        )

    def _acortar(self, texto: str, limite: int = 400) -> str:
        """Acorta una respuesta larga para mantenerla ágil en el grupo."""
        if len(texto) <= limite:
            return texto.strip()
        return texto.strip()[:limite].rsplit(" ", 1)[0] + "…"

    def _arma_cta(self, username: str) -> str:
        if not username:
            return (
                "\n\n👇 Si querés más información o una cotización sin "
                "compromiso, escribime por privado y te ayudo."
            )
        return (
            f"\n\n👇 Si querés más información o una cotización sin "
            f"compromiso, escribime por privado: @{username}"
        )

    def _generar_respuesta(self, texto: str, username: str) -> str:
        base = self._respuesta_conocimiento(texto) or self._respuesta_generica(texto)
        return f"{base}{self._arma_cta(username)}"

    # ─────────────────────────────────────────
    # Handlers de Telegram
    # ─────────────────────────────────────────

    async def handle_group_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Responde mensajes relevantes de grupos con un llamado a la acción."""
        chat = update.effective_chat
        if chat is None or chat.type not in ("group", "supergroup"):
            return

        # Auto-registro: cualquier mensaje escuchado confirma que el bot está
        # en el grupo. Así los ganchos se publican aunque nunca llegue el
        # update my_chat_member (p. ej. si el servicio dormía al agregarlo).
        if chat.id not in self._grupos_registrados:
            registrar_grupo(chat.id, chat.title or "")
            self._grupos_registrados.add(chat.id)

        message = update.message
        if message is None or not message.text:
            return

        user = message.from_user
        if user is None or user.is_bot:
            return

        texto = message.text
        bot = context.bot
        username = (bot.username or "").lower() if bot else ""

        mencionado = self._menciona_bot(texto, username)
        if message.reply_to_message and message.reply_to_message.from_user:
            mencionado = mencionado or (
                message.reply_to_message.from_user.id == bot.id
            )

        if not mencionado and not self.es_relevante(texto):
            return

        ahora = time.time()
        if mencionado:
            ultima = self._cooldown_mencion.get(chat.id, 0)
            if ahora - ultima < _COOLDOWN_MENCION_SEG:
                return
        else:
            ultima = self._cooldown_auto.get(chat.id, 0)
            if ahora - ultima < _COOLDOWN_AUTO_SEG:
                return

        respuesta = self._generar_respuesta(texto, username)
        if mencionado:
            self._cooldown_mencion[chat.id] = ahora
        else:
            self._cooldown_auto[chat.id] = ahora

        try:
            await message.reply_text(respuesta, disable_web_page_preview=True)
            logger.info(
                "[GRUPO] Respondido chat_id=%s (mention=%s) a %s: %s…",
                chat.id, mencionado, user.first_name, respuesta[:60],
            )
        except Exception as exc:
            logger.warning(
                "[GRUPO] No se pudo responder en chat_id=%s: %s",
                chat.id, exc,
            )

    async def handle_my_chat_member(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Registra/desactiva grupos cuando el bot es agregado o removido."""
        mcm = update.my_chat_member
        if mcm is None:
            return

        chat = mcm.chat
        if chat is None or chat.type not in ("group", "supergroup"):
            return

        nuevo = mcm.new_chat_member.status
        if nuevo in (
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.RESTRICTED,
        ):
            registrar_grupo(chat.id, chat.title or "")
        elif nuevo in (ChatMemberStatus.LEFT, ChatMemberStatus.KICKED):
            desactivar_grupo(chat.id)
