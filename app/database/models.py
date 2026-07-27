"""
Modelos ORM de SQLAlchemy para persistencia de Leads, Conversaciones,
Sesiones de Entrenamiento y Base de Conocimiento SERVIRED.

Uso:
    from app.database.models import (
        LeadDB, ConversationMessageDB, TrainingSessionDB,
        ServiredKnowledgeDB,
    )
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
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

    # Scoring comercial
    score = Column(Integer, default=0)
    temperatura_lead = Column(String(20), nullable=True)

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


class ServiredKnowledgeDB(Base):
    """
    Base de conocimiento unificada SERVIRED.

    Almacena toda la información que Sofía usa para vender y asesorar:
    planes, precios, coberturas, beneficios, objeciones, cierres,
    argumentos comerciales e información documental.

    Una única fuente de verdad para la IA conversacional.
    """

    __tablename__ = "servired_knowledge"

    id = Column(Integer, primary_key=True, autoincrement=True)
    categoria = Column(
        String(50),
        nullable=False,
        index=True,
        comment="planes|precios|coberturas|beneficios|objeciones|cierres|argumentos|informacion",
    )
    titulo = Column(String(200), nullable=False, index=True)
    contenido = Column(Text, nullable=False)
    tags = Column(String(500), nullable=True, index=True, comment="CSV de tags para búsqueda")
    fuente = Column(String(200), nullable=True, comment="Archivo markdown original o URL")
    prioridad_comercial = Column(
        Integer,
        default=0,
        nullable=False,
        comment="Mayor número = mayor prioridad para retrieval",
    )
    activo = Column(Boolean, default=True, nullable=False, index=True)
    fecha_actualizacion = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<ServiredKnowledgeDB(id={self.id}, categoria='{self.categoria}', "
            f"titulo='{self.titulo}')>"
        )


class ServiredPriceDB(Base):
    """
    Tabla de precios SERVIRED por tipo de afiliación, plan, zona y edad.

    Almacena precios estructurados importados desde archivos Excel.
    Cada fila representa un precio específico para un组合 de:
    - Tipo de afiliación (particular, monotributo, relación de dependencia)
    - Plan (Medimax CO, Medimax, Medimax Gold, Gold, Plan Joven)
    - Zona (Córdoba, Interior)
    - Rango de edad del integrante
    """

    __tablename__ = "servired_prices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tipo_afiliacion = Column(
        String(50),
        nullable=False,
        index=True,
        comment="particular|monotributo|relacion_dependencia",
    )
    plan = Column(
        String(100),
        nullable=False,
        index=True,
        comment="medimax_co|medimax|medimax_gold|gold|plan_joven",
    )
    zona = Column(
        String(20),
        nullable=False,
        index=True,
        comment="cordoba|interior",
    )
    edad_desde = Column(Integer, default=0, nullable=False)
    edad_hasta = Column(Integer, default=99, nullable=False)
    precio = Column(Float, nullable=False)
    activo = Column(Boolean, default=True, nullable=False, index=True)
    fuente = Column(
        String(200),
        nullable=True,
        comment="Archivo Excel de origen",
    )
    fecha_actualizacion = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<ServiredPriceDB(id={self.id}, tipo='{self.tipo_afiliacion}', "
            f"plan='{self.plan}', zona='{self.zona}', "
            f"edad={self.edad_desde}-{self.edad_hasta}, "
            f"precio={self.precio})>"
        )


class TrainingSessionDB(Base):
    """
    Modelo persistente de sesión de entrenamiento.

    Almacena el resultado de cada ejecución del TrainingEngine
    para analizar la evolución comercial de Sofía.
    """

    __tablename__ = "training_sessions"

    # ID
    id = Column(Integer, primary_key=True, autoincrement=True)

    # Datos de la sesión
    perfil_cliente = Column(String(100), nullable=False, index=True)
    canal_simulacion = Column(String(50), default="simulador")

    # Scores por dimensión (0-20 cada uno)
    score_total = Column(Integer, default=0)
    score_descubrimiento = Column(Integer, default=0)
    score_calificacion = Column(Integer, default=0)
    score_valor = Column(Integer, default=0)
    score_objeciones = Column(Integer, default=0)
    score_cierre = Column(Integer, default=0)

    # Errores
    cantidad_errores = Column(Integer, default=0)
    errores_detectados = Column(Text, default="[]")

    # Recomendaciones
    recomendaciones = Column(Text, default="[]")

    # Metadata
    creado = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<TrainingSessionDB(id={self.id}, perfil={self.perfil_cliente}, "
            f"score={self.score_total})>"
        )
