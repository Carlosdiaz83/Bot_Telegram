"""
Handlers del bot de Telegram.

Cada handler es una función async que recibe (update, context)
y actúa como adaptador puro entre Telegram y el motor comercial.

NO contiene lógica comercial — delega todo a ConversationManager.

Flujo:
    Mensaje Telegram → Handler (adaptador) → ConversationManager → Respuesta
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

_manager = None

_CARPETA_RECIBOS = Path("data") / "recibos"


def get_manager():
    """Obtiene o crea la instancia del ConversationManager (singleton)."""
    global _manager
    if _manager is None:
        from app.services.conversation_manager import ConversationManager
        from app.config.settings import BotConfig

        try:
            config = BotConfig.from_env()
            db_url = config.database_url
            api_key = config.groq_api_key
        except Exception:
            db_url = None
            api_key = ""

        ai_service = None
        if api_key:
            try:
                from app.ai.service import AIService
                ai_service = AIService(api_key=api_key)
                logger.info("[TELEGRAM] AIService habilitado")
            except Exception as e:
                logger.warning("[TELEGRAM] No se pudo crear AIService: %s", e)

        _manager = ConversationManager(
            ai_service=ai_service,
            database_url=db_url,
        )
        logger.info(
            "[TELEGRAM] ConversationManager creado (db=%s, ai=%s)",
            "enabled" if db_url else "disabled",
            "enabled" if ai_service else "disabled",
        )
    return _manager


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Maneja cualquier mensaje de texto del usuario.

    Adaptador puro: recibe mensaje, delega a ConversationManager, responde.
    """
    if update.message is None or update.message.text is None:
        return

    user = update.effective_user
    if user is None:
        return

    telegram_id = user.id
    mensaje = update.message.text
    nombre = user.first_name or "unknown"

    logger.info(
        "[TELEGRAM] Mensaje recibido — user=%s (id=%d): %s",
        nombre, telegram_id, mensaje[:80],
    )

    try:
        manager = get_manager()

        logger.info("[FLOW] HANDLER_ENTER — user=%s (id=%d), mensaje='%s'", nombre, telegram_id, mensaje[:80])
        respuesta = manager.procesar_mensaje(telegram_id, mensaje)
        logger.info("[FLOW] HANDLER_EXIT — user=%s (id=%d), respuesta='%s'", nombre, telegram_id, respuesta[:80])

        await update.message.reply_text(respuesta)
        logger.info("[TELEGRAM] Respuesta enviada a %s (id=%d)", nombre, telegram_id)

        # Archivos adjuntos de respaldo (cartillas oficiales en PDF)
        adjuntos = getattr(respuesta, "archivos_adjuntos", None) or []
        for ruta_archivo in adjuntos:
            try:
                archivo = Path(ruta_archivo)
                if not archivo.is_file():
                    logger.warning(
                        "[TELEGRAM] Adjunto no encontrado para %s (id=%d): %s",
                        nombre, telegram_id, ruta_archivo,
                    )
                    continue
                with open(archivo, "rb") as fh:
                    await update.message.reply_document(
                        document=fh,
                        filename=archivo.name,
                    )
                logger.info(
                    "[TELEGRAM] Adjunto enviado a %s (id=%d): %s",
                    nombre, telegram_id, archivo.name,
                )
            except Exception as e:
                logger.error(
                    "[TELEGRAM] Error enviando adjunto a %s (id=%d): %s",
                    nombre, telegram_id, str(e),
                    exc_info=True,
                )

    except Exception as e:
        logger.error(
            "[TELEGRAM] Error procesando mensaje de %s (id=%d): %s",
            nombre, telegram_id, str(e),
            exc_info=True,
        )
        try:
            await update.message.reply_text(
                "Disculpá, tuve un problema técnico. Por favor, intentá de nuevo."
            )
        except Exception:
            logger.error("[TELEGRAM] No se pudo enviar mensaje de error a %s", nombre, exc_info=True)


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Maneja archivos enviados por el usuario (recibo de sueldo en PDF).

    Descarga el archivo a disco, delega el procesamiento a
    ConversationManager y responde retomando el flujo de datos.
    """
    if update.message is None or update.effective_user is None:
        return
    if update.message.document is None:
        return

    user = update.effective_user
    telegram_id = user.id
    nombre = user.first_name or "unknown"
    documento = update.message.document
    nombre_archivo = documento.file_name or "recibo"
    extension = Path(nombre_archivo).suffix.lower()

    if extension not in {".pdf", ".jpg", ".jpeg", ".png", ".webp"}:
        await update.message.reply_text(
            "Ese formato no lo puedo leer. Enviame el recibo de sueldo "
            "como PDF o foto (jpg/png), por favor."
        )
        return

    try:
        _CARPETA_RECIBOS.mkdir(parents=True, exist_ok=True)
        ruta = _CARPETA_RECIBOS / (
            f"{telegram_id}_{int(time.time())}{extension}"
        )

        logger.info(
            "[TELEGRAM] Documento recibido — user=%s (id=%d): %s",
            nombre, telegram_id, nombre_archivo,
        )

        archivo = await documento.get_file()
        await archivo.download_to_drive(custom_path=ruta)

        manager = get_manager()
        respuesta = manager.procesar_documento(
            telegram_id, str(ruta), nombre_archivo=nombre_archivo
        )

        await update.message.reply_text(respuesta)
        logger.info(
            "[TELEGRAM] Recibo procesado — user=%s (id=%d), ruta=%s",
            nombre, telegram_id, ruta,
        )

    except Exception as e:
        logger.error(
            "[TELEGRAM] Error procesando documento de %s (id=%d): %s",
            nombre, telegram_id, str(e),
            exc_info=True,
        )
        try:
            await update.message.reply_text(
                "Disculpá, tuve un problema al leer el recibo. "
                "¿Podés enviarlo de nuevo o escribirme su importe?"
            )
        except Exception:
            logger.error(
                "[TELEGRAM] No se pudo responder error de documento a %s",
                nombre, exc_info=True,
            )


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Maneja fotos enviadas por el usuario (recibo de sueldo en imagen).

    Usa la foto de mayor resolución, la descarga a disco y delega el
    procesamiento a ConversationManager.
    """
    if update.message is None or update.effective_user is None:
        return
    if not update.message.photo:
        return

    user = update.effective_user
    telegram_id = user.id
    nombre = user.first_name or "unknown"
    foto = update.message.photo[-1]  # mayor resolución

    try:
        _CARPETA_RECIBOS.mkdir(parents=True, exist_ok=True)
        ruta = _CARPETA_RECIBOS / f"{telegram_id}_{int(time.time())}.jpg"

        logger.info(
            "[TELEGRAM] Foto recibida — user=%s (id=%d)",
            nombre, telegram_id,
        )

        archivo = await foto.get_file()
        await archivo.download_to_drive(custom_path=ruta)

        manager = get_manager()
        respuesta = manager.procesar_documento(
            telegram_id, str(ruta), nombre_archivo=ruta.name
        )

        await update.message.reply_text(respuesta)
        logger.info(
            "[TELEGRAM] Foto procesada — user=%s (id=%d), ruta=%s",
            nombre, telegram_id, ruta,
        )

    except Exception as e:
        logger.error(
            "[TELEGRAM] Error procesando foto de %s (id=%d): %s",
            nombre, telegram_id, str(e),
            exc_info=True,
        )
        try:
            await update.message.reply_text(
                "Disculpá, tuve un problema al leer la foto del recibo. "
                "¿Podés enviarla de nuevo o escribirme su importe?"
            )
        except Exception:
            logger.error(
                "[TELEGRAM] No se pudo responder error de foto a %s",
                nombre, exc_info=True,
            )


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Maneja el comando /start.

    Reinicia la sesión del usuario y envía el saludo inicial.
    """
    if update.message is None or update.effective_user is None:
        return

    user = update.effective_user
    telegram_id = user.id
    nombre = user.first_name or "unknown"

    logger.info("[TELEGRAM] Comando /start recibido de %s (id=%d)", nombre, telegram_id)

    try:
        manager = get_manager()
        manager.session_manager.eliminar(telegram_id)
        logger.info("[CONVERSATION] Sesión eliminada para user=%s (id=%d)", nombre, telegram_id)

        respuesta = manager.procesar_mensaje(telegram_id, "Hola")
        await update.message.reply_text(respuesta)
        logger.info("[TELEGRAM] Sesión iniciada para user=%s (id=%d)", nombre, telegram_id)

    except Exception as e:
        logger.error(
            "[TELEGRAM] Error en /start para %s (id=%d): %s",
            nombre, telegram_id, str(e),
            exc_info=True,
        )
        try:
            await update.message.reply_text(
                "Hola! Soy Sofía, tu asesora comercial de Servired. ¿En qué puedo ayudarte?"
            )
        except Exception:
            logger.error("[TELEGRAM] No se pudo enviar saludo de fallback a %s", nombre)
