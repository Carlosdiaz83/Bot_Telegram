"""
Modelos ORM de SQLAlchemy para persistencia de Leads y Conversaciones.

Uso:
    from app.database.models import LeadDB, ConversationMessageDB
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    """Clase base para todos los modelos ORM."""
    pass


class LeadDB(Base):
    """
    Modelo persistente de Lead (cliente potencial).

    Almacena toda la información recopilada durante la conversación
    comercial, incluyendo datos personales, perfil SERVIRED y estado
    comercial.
    """

    __tablename__ = "leads"

    # ID
    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(Integer, unique=True, index=True, nullable=False)

    # Datos generales
    nombre = Column(String(200), nullable=True)
    telefono = Column(String(50), nullable=True)
    edad = Column(Integer, nullable=True)
    localidad = Column(String(200), nullable=True)

    # Datos SERVIRED — Situación laboral
    tipo_afiliacion = Column(String(50), nullable=True)
    tiene_aportes = Column(Boolean, nullable=True)
    tiene_recibo_sueldo = Column(Boolean, nullable=True)

    # Datos SERVIRED — Grupo familiar
    conyuge = Column(Boolean, default=False)
    hijos = Column(Boolean, default=False)
    cantidad_hijos = Column(Integer, default=0)
    cantidad_integrantes = Column(Integer, default=1)

    # Datos SERVIRED — Perfil
    interes_detectado = Column(String(50), nullable=True)
    necesidad_principal = Column(String(50), nullable=True)
    prioridad_cliente = Column(String(50), nullable=True)

    # Estado comercial
    estado_comercial = Column(String(50), default="nuevo")
    etapa_conversacion = Column(String(50), default="nuevo")
    perfil_servired = Column(String(100), nullable=True)

    # Fechas
    creado = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    actualizado = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relaciones
    mensajes = relationship(
        "ConversationMessageDB",
        back_populates="lead",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )

    def __repr__(self) -> str:
        return f"<LeadDB(id={self.id}, telegram_id={self.telegram_id}, nombre={self.nombre})>"


class ConversationMessageDB(Base):
    """
    Modelo persistente de mensaje de conversación.

    Almacena cada intercambio de mensajes entre el cliente y Sofía,
    incluyendo la etapa de conversación en la que ocurrió.
    """

    __tablename__ = "conversation_messages"

    # ID
    id = Column(Integer, primary_key=True, autoincrement=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=False, index=True)

    # Mensaje
    mensaje_cliente = Column(Text, nullable=False)
    respuesta_sofia = Column(Text, nullable=False)
    etapa = Column(String(50), nullable=False)

    # Metadata
    creado = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relación
    lead = relationship("LeadDB", back_populates="mensajes")

    def __repr__(self) -> str:
        return f"<ConversationMessageDB(id={self.id}, lead_id={self.lead_id}, etapa={self.etapa})>"
