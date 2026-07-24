"""
Handlers del bot de Telegram.

Cada handler es una función async que recibe (update, context)
y contiene únicamente la lógica de enrutamiento/respuesta.
La lógica de negocio vive en services/.
"""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Mensaje de bienvenida (Sprint 2 — respaldo fijo)
# ─────────────────────────────────────────────
WELCOME_MESSAGE = (
    "👋 ¡Hola! Soy Sofía, la asesora virtual de Servired.\n\n"
    "Estoy aquí para ayudarte a encontrar la mejor cobertura de salud.\n\n"
    "¿En qué puedo ayudarte?"
)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Responde a cualquier mensaje de texto con el saludo de bienvenida.

    Este es el handler base del Sprint 2.
    En futuros sprints se agregará lógica de análisis y routing.

    Args:
        update: Objeto Update de Telegram con la información del mensaje.
        context: Contexto de la conversación con datos de la aplicación.
    """
    if update.message is None or update.message.text is None:
        return

    user = update.effective_user
    user_info = f"{user.first_name} (id={user.id})" if user else "desconocido"
    logger.info("Mensaje recibido de %s: %s", user_info, update.message.text[:50])

    await update.message.reply_text(WELCOME_MESSAGE)
    logger.info("Respuesta de bienvenida enviada a %s", user_info)
