"""
Handlers del bot de Telegram.

Cada handler es una función async que recibe (update, context)
y contiene la lógica de enrutamiento/respuesta.

El ConversationManager orquesta la lógica comercial.
Incluye manejo robusto de errores para producción.
"""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from app.services.conversation_manager import ConversationManager

logger = logging.getLogger(__name__)

_manager: ConversationManager | None = None


def get_manager() -> ConversationManager:
    """Obtiene la instancia del ConversationManager (singleton)."""
    global _manager
    if _manager is None:
        _manager = ConversationManager()
    return _manager


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Maneja cualquier mensaje de texto del usuario.

    Procesa el mensaje a través del ConversationManager y responde
    con el mensaje generado por la lógica comercial.
    """
    if update.message is None or update.message.text is None:
        return

    user = update.effective_user
    if user is None:
        return

    telegram_id = user.id
    mensaje = update.message.text
    user_info = f"{user.first_name} (id={telegram_id})"

    logger.info("Mensaje recibido de %s: %s", user_info, mensaje[:50])

    try:
        manager = get_manager()
        respuesta = manager.procesar_mensaje(telegram_id, mensaje)
        await update.message.reply_text(respuesta)
        logger.info("Respuesta enviada a %s", user_info)
    except Exception as e:
        logger.error("Error procesando mensaje de %s: %s", user_info, str(e), exc_info=True)
        try:
            await update.message.reply_text(
                "Disculpá, tuve un problema técnico. Por favor, intentá de nuevo."
            )
        except Exception:
            logger.error("No se pudo enviar mensaje de error a %s", user_info)


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Maneja el comando /start.

    Reinicia la sesión del usuario y envía el saludo inicial.
    """
    if update.message is None or update.effective_user is None:
        return

    user = update.effective_user
    telegram_id = user.id

    logger.info("Comando /start recibido de %s", user.first_name)

    try:
        manager = get_manager()
        manager.session_manager.eliminar(telegram_id)
        respuesta = manager.procesar_mensaje(telegram_id, "Hola")
        await update.message.reply_text(respuesta)
        logger.info("Sesión iniciada para usuario %s", user.first_name)
    except Exception as e:
        logger.error("Error en /start para %s: %s", user.first_name, str(e), exc_info=True)
        try:
            await update.message.reply_text(
                "Hola! Soy Sofía, tu asesora comercial. ¿En qué puedo ayudarte?"
            )
        except Exception:
            logger.error("No se pudo enviar saludo de fallback a %s", user.first_name)
