"""
Gestión de sesiones de usuario por Telegram.

Mantiene el estado de cada conversación en memoria.
Preparado para reemplazo futuro por base de datos.

Uso:
    from app.services.session_manager import SessionManager, EtapaConversacion
    manager = SessionManager()
    session = manager.get_or_create(telegram_id=123456)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from enum import Enum

from app.models.lead import Lead

logger = logging.getLogger(__name__)


class EtapaConversacion(str, Enum):
    """Etapas del flujo comercial."""
    NUEVO = "nuevo"
    DESCUBRIENDO_NECESIDAD = "descubriendo_necesidad"
    CALIFICANDO = "calificando"
    PRESENTANDO_VALOR = "presentando_valor"
    MANEJANDO_OBJECIONES = "manejando_objeciones"
    INTENTANDO_CIERRE = "intentando_cierre"
    CALIFICADO = "calificado"
    DERIVADO = "derivado"


class ResultadoCierre(str, Enum):
    """Resultado del intento de cierre."""
    ACEPTO = "acepto"
    PENDIENTE = "pendiente"
    RECHAZO = "rechazó"
    NECESITA_ASESOR = "necesita_asesor"


class UserSession:
    """
    Sesión de un usuario Telegram.

    Attributes:
        telegram_id: ID del usuario en Telegram.
        lead: Modelo Lead con datos del cliente.
        etapa: Etapa actual de la conversación.
        ultima_interaccion: Timestamp de la última interacción.
        intento_de_cierre: Si ya se intentó cerrar la venta.
        resultado_cierre: Resultado del intento de cierre.
        mensajes_en_etapa: Contador de mensajes en la etapa actual.
    """

    def __init__(self, telegram_id: int) -> None:
        self.telegram_id = telegram_id
        self.lead = Lead(lead_id=str(telegram_id))
        self.etapa = EtapaConversacion.NUEVO
        self.ultima_interaccion: datetime = datetime.now(timezone.utc)
        self.intento_de_cierre: bool = False
        self.resultado_cierre: ResultadoCierre | None = None
        self.mensajes_en_etapa: int = 0
        self.en_cotizacion: bool = False

    def actualizar_interaccion(self) -> None:
        """Registra la hora de la última interacción."""
        self.ultima_interaccion = datetime.now(timezone.utc)

    def avanzar_etapa(self, nueva_etapa: EtapaConversacion) -> None:
        """
        Avanza a la siguiente etapa de la conversación.

        Args:
            nueva_etapa: Etapa a la que avanzar.
        """
        etapa_anterior = self.etapa
        self.etapa = nueva_etapa
        self.mensajes_en_etapa = 0
        logger.debug(
            "Sesión %s: etapa %s → %s",
            self.telegram_id,
            etapa_anterior.value,
            nueva_etapa.value,
        )


class SessionManager:
    """
    Gestor de sesiones de usuario en memoria.

    Almacena sesiones en un dict en memoria.
    Preparado para reemplazo futuro por base de datos.
    """

    def __init__(self) -> None:
        self._sesiones: dict[int, UserSession] = {}

    def get_or_create(self, telegram_id: int) -> UserSession:
        """
        Obtiene la sesión de un usuario o la crea si no existe.

        Args:
            telegram_id: ID del usuario en Telegram.

        Returns:
            Sesión del usuario.
        """
        if telegram_id not in self._sesiones:
            self._sesiones[telegram_id] = UserSession(telegram_id)
            logger.info("Nueva sesión creada para usuario %s", telegram_id)

        session = self._sesiones[telegram_id]
        session.actualizar_interaccion()
        return session

    def get(self, telegram_id: int) -> UserSession | None:
        """
        Obtiene la sesión de un usuario sin crear una nueva.

        Args:
            telegram_id: ID del usuario en Telegram.

        Returns:
            Sesión del usuario o None si no existe.
        """
        return self._sesiones.get(telegram_id)

    def eliminar(self, telegram_id: int) -> None:
        """Elimina la sesión de un usuario."""
        if telegram_id in self._sesiones:
            del self._sesiones[telegram_id]
            logger.info("Sesión eliminada para usuario %s", telegram_id)

    @property
    def total_sesiones(self) -> int:
        """Cantidad total de sesiones activas."""
        return len(self._sesiones)
