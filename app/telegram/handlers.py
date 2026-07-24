"""
Handlers del bot de Telegram.

Cada handler es una función async que recibe (update, context)
y contiene la lógica de enrutamiento/respuesta.

El ConversationManager orquesta la lógica comercial.
"""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from app.services.conversation_manager import ConversationManager

logger = logging.getLogger(__name__)

# Instancia global del conversation manager (se inicializa al inicio)
_manager: ConversationManager | None = None


def get_manager() -> ConversationManager:
    """Obtiene la instancia del ConversationManager."""
    global _manager
    if _manager is None:
        _manager = ConversationManager()
    return _manager


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Maneja cualquier mensaje de texto del usuario.

    Procesa el mensaje a través del ConversationManager y responde
    con el mensaje generado por la lógica comercial.

    Args:
        update: Objeto Update de Telegram.
        context: Contexto de la conversación.
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

    manager = get_manager()
    respuesta = manager.procesar_mensaje(telegram_id, mensaje)

    await update.message.reply_text(respuesta)
    logger.info("Respuesta enviada a %s", user_info)


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Maneja el comando /start.

    Reinicia la sesión del usuario y envía el saludo inicial.

    Args:
        update: Objeto Update de Telegram.
        context: Contexto de la conversación.
    """
    if update.message is None or update.effective_user is None:
        return

    user = update.effective_user
    telegram_id = user.id

    manager = get_manager()
    # Eliminar sesión anterior si existe
    manager.session_manager.eliminar(telegram_id)

    respuesta = manager.procesar_mensaje(telegram_id, "Hola")

    await update.message.reply_text(respuesta)
    logger.info("Sesión iniciada para usuario %s", user.first_name)
