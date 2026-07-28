"""
Commercial Memory — Sprint 21.5.

Memoria comercial persistente durante toda la conversación.

NO reconstruye contexto. NO deduce. RECUERDA.

Flujo:
    ConversationManager → Orchestrator.analizar()
    → memory.get_or_create(lead_id)
    → memory.actualizar(lead, mensaje, resultado)
    → PromptBuilder recibe context y NO pide datos confirmados.

Componentes:
    CommercialConversationContext: memoria de UNA conversación.
    CommercialMemory: store in-memory de todas las conversaciones.
    get_memory(): singleton accesible desde orchestrator y panel.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from app.models.lead import Lead, TipoAfiliacion

logger = logging.getLogger(__name__)


# ── Mapa de progreso por objetivo ──
_PROGRESO_POR_OBJETIVO: dict[str, int] = {
    "DESCUBRIENDO": 10,
    "CALIFICANDO": 30,
    "ESPERANDO_DATOS": 55,
    "COTIZANDO": 75,
    "PRESENTANDO_VALOR": 85,
    "OBJECIONES": 90,
    "CIERRE": 95,
    "POSTVENTA": 100,
}

# ── Mapa de nivel de interés ──
_NIVEL_INTERES_MAP: dict[str, int] = {
    "MUY_ALTO": 90,
    "ALTO": 70,
    "MEDIO": 50,
    "BAJO": 20,
}

# ── Mapeo inverso de nivel numérico a etiqueta ──
_ETIQUETA_INTERES: list[tuple[int, str]] = [
    (80, "MUY_ALTO"),
    (60, "ALTO"),
    (40, "MEDIO"),
    (0, "BAJO"),
]


@dataclass
class CommercialConversationContext:
    """
    Memoria comercial viva para UNA conversación.

    Persiste durante toda la conversación. Nunca se reconstruye desde cero.
    Solo evoluciona con cada interacción.
    """

    lead_id: str = ""

    # ── Objetivo comercial ──
    objetivo_actual: str | None = "DESCUBRIENDO"
    proximo_objetivo: str | None = None

    # ── Datos confirmados (una vez aquí, NO se vuelven a pedir) ──
    datos_confirmados: dict[str, Any] = field(default_factory=dict)

    # ── Datos faltantes para cotizar ──
    datos_faltantes: list[str] = field(default_factory=list)

    # ── Datos del cliente (extraídos y confirmados) ──
    tipo_afiliacion: str | None = None
    grupo_familiar: dict[str, Any] = field(default_factory=lambda: {
        "titular": True, "conyuge": False, "hijos": False, "cantidad": 1,
    })
    edades: list[int] = field(default_factory=list)
    localidad: str | None = None
    categoria_monotributo: str | None = None
    conceptos_obra_social: list[float] = field(default_factory=list)
    recibo_recibido: bool = False

    # ── Plan ──
    plan_recomendado: str | None = None
    cotizacion_realizada: bool = False

    # ── Objeciones ──
    objeciones_detectadas: list[str] = field(default_factory=list)
    ultima_objecion: str | None = None

    # ── Interés ──
    interes_detectado: str | None = None
    nivel_interes: int = 30
    temperatura_lead: str | None = None

    # ── Riesgo ──
    riesgo_perder_venta: str | None = "BAJO"

    # ── Última interacción ──
    ultima_accion: str | None = None
    ultima_respuesta: str | None = None
    ultima_pregunta: str | None = None
    ultima_actualizacion: datetime | None = None

    # ── Progreso (calculado) ──
    progreso: int = 0

    def confirmar_dato(self, campo: str, valor: Any) -> None:
        """
        Confirma un dato. Una vez confirmado, NO se vuelve a pedir.

        Args:
            campo: Nombre del campo (ej: "edad", "localidad").
            valor: Valor confirmado.
        """
        self.datos_confirmados[campo] = valor
        if campo in self.datos_faltantes:
            self.datos_faltantes.remove(campo)

    def calcular_progreso(self) -> int:
        """
        Calcula el progreso de la venta según el objetivo actual.

        Returns:
            Porcentaje de progreso (0-100).
        """
        if self.objetivo_actual in _PROGRESO_POR_OBJETIVO:
            base = _PROGRESO_POR_OBJETIVO[self.objetivo_actual]
        else:
            base = 10

        bonus = 0
        if self.tipo_afiliacion:
            bonus += 5
        if self.localidad:
            bonus += 3
        if self.edades:
            bonus += 3
        if self.cotizacion_realizada:
            bonus += 5
        if self.objeciones_detectadas:
            bonus += 2

        return min(base + bonus, 100)

    def ya_tiene(self, campo: str) -> bool:
        """
        Verifica si un dato ya fue confirmado.

        Args:
            campo: Nombre del campo a verificar.

        Returns:
            True si el campo está en datos_confirmados.
        """
        return campo in self.datos_confirmados

    def datos_completos_para_cotizar(self) -> bool:
        """
        Verifica si todos los datos necesarios para cotizar están confirmados.

        Returns:
            True si no hay datos faltantes.
        """
        return len(self.datos_faltantes) == 0

    def resumen(self) -> str:
        """Devuelve un resumen legible de la memoria."""
        lineas = [
            f"Objetivo: {self.objetivo_actual or 'N/A'}",
            f"Próximo: {self.proximo_objetivo or 'N/A'}",
            f"Progreso: {self.progreso}%",
            f"Datos confirmados: {len(self.datos_confirmados)}",
            f"Datos faltantes: {len(self.datos_faltantes)}",
            f"Objeciones: {len(self.objeciones_detectadas)}",
            f"Interés: {self.nivel_interes}/100 ({self.interes_detectado})",
            f"Riesgo: {self.riesgo_perder_venta}",
        ]
        return " | ".join(lineas)


class CommercialMemory:
    """
    Gestor de memoria comercial para todas las conversaciones.

    Store in-memory. Cada lead tiene su propio CommercialConversationContext.
    La memoria nunca se reconstruye desde cero — solo evoluciona.
    """

    def __init__(self, dias_inactividad: int = 7) -> None:
        """
        Inicializa el gestor de memoria.

        Args:
            dias_inactividad: Días de inactividad antes de reiniciar contexto.
        """
        self._store: dict[str, CommercialConversationContext] = {}
        self._dias_inactividad = dias_inactividad

    def get_or_create(self, lead_id: str) -> CommercialConversationContext:
        """
        Obtiene o crea el contexto para un lead.

        Si el contexto existe pero está inactivo por más de X días,
        se reinicia (manteniendo lead_id).

        Args:
            lead_id: Identificador del lead.

        Returns:
            CommercialConversationContext para el lead.
        """
        if lead_id in self._store:
            context = self._store[lead_id]
            if context.ultima_actualizacion:
                now = datetime.now(timezone.utc)
                ultima = context.ultima_actualizacion
                if ultima.tzinfo is None:
                    ultima = ultima.replace(tzinfo=timezone.utc)
                dias = (now - ultima).days
                if dias > self._dias_inactividad:
                    logger.info(
                        "[MEMORY] Lead %s inactivo %d días — reiniciando contexto",
                        lead_id, dias,
                    )
                    self.reiniciar(lead_id)
                    return self._store[lead_id]
            return context
        return self._crear(lead_id)

    def actualizar(
        self,
        lead: Lead,
        mensaje: str,
        accion: str,
        datos_detectados: dict[str, Any] | None = None,
        datos_faltantes: list[str] | None = None,
        respuesta: str | None = None,
    ) -> CommercialConversationContext:
        """
        Actualiza la memoria después de cada interacción.

        Args:
            lead: Lead con datos actuales del cliente.
            mensaje: Último mensaje del cliente.
            accion: Acción que se ejecutó (PEDIR_DATO, COTIZAR, etc.).
            datos_detectados: Datos nuevos extraídos del mensaje.
            datos_faltantes: Lista de datos que faltan.
            respuesta: Respuesta que se dio al cliente.

        Returns:
            Contexto actualizado.
        """
        context = self.get_or_create(lead.lead_id)

        # ── Actualizar datos detectados ──
        if datos_detectados:
            for campo, valor in datos_detectados.items():
                context.confirmar_dato(campo, valor)

        # ── Sincronizar datos del Lead → memoria ──
        self._sincronizar_lead(context, lead)

        # ── Actualizar datos faltantes ──
        if datos_faltantes is not None:
            context.datos_faltantes = [
                d for d in datos_faltantes
                if d not in context.datos_confirmados
            ]

        # ── Actualizar objetivo ──
        context.objetivo_actual = self._mapear_objetivo(lead, context)
        context.proximo_objetivo = self._determinar_proximo(context)

        # ── Detectar objeciones ──
        if accion == "MANEJAR_OBJECION":
            objecion = self._detectar_objecion(mensaje)
            if objecion and objecion not in context.objeciones_detectadas:
                context.objeciones_detectadas.append(objecion)
            context.ultima_objecion = objecion or context.ultima_objecion

        # ── Actualizar interés ──
        context.nivel_interes = self._calcular_interes(
            context, lead, accion, mensaje
        )
        context.interes_detectado = self._etiquetar_interes(context.nivel_interes)
        context.temperatura_lead = lead.temperatura_lead or context.temperatura_lead

        # ── Actualizar riesgo ──
        context.riesgo_perder_venta = self._calcular_riesgo(context, lead, accion)

        # ── Actualizar cotización ──
        if accion == "COTIZAR":
            context.cotizacion_realizada = True

        # ── Última interacción ──
        context.ultima_accion = accion
        context.ultima_respuesta = respuesta
        context.ultima_pregunta = mensaje
        context.ultima_actualizacion = datetime.now(timezone.utc)

        # ── Recalcular progreso ──
        context.progreso = context.calcular_progreso()

        logger.debug(
            "[MEMORY] Lead %s actualizado — objetivo=%s, faltantes=%d, "
            "interés=%d, riesgo=%s, progreso=%d%%",
            lead.lead_id, context.objetivo_actual,
            len(context.datos_faltantes), context.nivel_interes,
            context.riesgo_perder_venta, context.progreso,
        )

        return context

    def reiniciar(self, lead_id: str) -> CommercialConversationContext:
        """
        Reinicia el contexto pero mantiene el lead_id.

        Args:
            lead_id: Identificador del lead.

        Returns:
            Nuevo contexto limpio.
        """
        context = CommercialConversationContext(lead_id=lead_id)
        self._store[lead_id] = context
        return context

    def eliminar(self, lead_id: str) -> None:
        """Elimina el contexto de un lead."""
        self._store.pop(lead_id, None)

    def cantidad_leads(self) -> int:
        """Cantidad de leads con memoria activa."""
        return len(self._store)

    def _crear(self, lead_id: str) -> CommercialConversationContext:
        """Crea un nuevo contexto vacío."""
        context = CommercialConversationContext(
            lead_id=lead_id,
            ultima_actualizacion=datetime.now(timezone.utc),
        )
        self._store[lead_id] = context
        return context

    def _sincronizar_lead(
        self, context: CommercialConversationContext, lead: Lead
    ) -> None:
        """Sincroniza datos del Lead a la memoria (solo si no están confirmados)."""
        if lead.nombre and not context.ya_tiene("nombre"):
            context.confirmar_dato("nombre", lead.nombre)

        if lead.edad is not None and not context.ya_tiene("edad"):
            context.confirmar_dato("edad", lead.edad)
            if lead.edad not in context.edades:
                context.edades.append(lead.edad)

        if lead.localidad and not context.ya_tiene("localidad"):
            context.confirmar_dato("localidad", lead.localidad)
            context.localidad = lead.localidad

        if lead.tipo_afiliacion and not context.ya_tiene("tipo_afiliacion"):
            context.confirmar_dato("tipo_afiliacion", lead.tipo_afiliacion.value)
            context.tipo_afiliacion = lead.tipo_afiliacion.value

        if lead.categoria_monotributo and not context.ya_tiene("categoria_monotributo"):
            context.confirmar_dato(
                "categoria_monotributo", lead.categoria_monotributo
            )
            context.categoria_monotributo = lead.categoria_monotributo

        if lead.tiene_recibo_sueldo is not None:
            context.recibo_recibido = lead.tiene_recibo_sueldo
            if lead.tiene_recibo_sueldo and not context.ya_tiene("recibo"):
                context.confirmar_dato("recibo", True)

        if lead.conceptos_obra_social and not context.ya_tiene("conceptos_obra_social"):
            context.confirmar_dato(
                "conceptos_obra_social", lead.conceptos_obra_social
            )
            context.conceptos_obra_social = lead.conceptos_obra_social

        # Grupo familiar
        context.grupo_familiar = {
            "titular": lead.grupo_familiar.titular,
            "conyuge": lead.grupo_familiar.conyuge,
            "hijos": lead.grupo_familiar.hijos,
            "cantidad": lead.cantidad_integrantes,
        }
        if lead.cantidad_integrantes > 1 and not context.ya_tiene("grupo_familiar"):
            context.confirmar_dato("grupo_familiar", context.grupo_familiar)

    def _mapear_objetivo(
        self, lead: Lead, context: CommercialConversationContext
    ) -> str:
        """Mapea el estado del lead a un objetivo comercial legible."""
        if context.cotizacion_realizada:
            return "PRESENTANDO_VALOR"
        if context.objeciones_detectadas:
            return "OBJECIONES"
        if context.tipo_afiliacion and context.datos_completos_para_cotizar():
            return "COTIZANDO"
        if context.tipo_afiliacion:
            return "ESPERANDO_DATOS"
        if lead.nombre:
            return "CALIFICANDO"
        return "DESCUBRIENDO"

    def _determinar_proximo(
        self, context: CommercialConversationContext
    ) -> str | None:
        """Determina cuál es el siguiente paso comercial."""
        if context.cotizacion_realizada:
            if context.objeciones_detectadas:
                return "REBATIR_OBJECION"
            return "CERRAR"
        if context.tipo_afiliacion and context.datos_completos_para_cotizar():
            return "CALCULAR"
        if not context.tipo_afiliacion:
            return "PEDIR_TIPO_AFILIACION"
        if not context.edades:
            return "PEDIR_EDADES"
        if not context.localidad:
            return "PEDIR_LOCALIDAD"
        if context.tipo_afiliacion == "relacion_dependencia":
            if not context.recibo_recibido:
                return "PEDIR_RECIBO"
            if not context.conceptos_obra_social:
                return "PEDIR_CONCEPTOS_OS"
        if context.tipo_afiliacion == "monotributo":
            if not context.categoria_monotributo:
                return "PEDIR_CATEGORIA"
        return "COMPLETAR_DATOS"

    def _detectar_objecion(self, mensaje: str) -> str | None:
        """Detecta el tipo de objeción en el mensaje."""
        msg = mensaje.lower()
        if any(w in msg for w in ["caro", "costoso", "muy caro", "no llego", "pago mucho"]):
            return "precio"
        if any(w in msg for w in ["cartilla", "prestador", "médico", "hospital"]):
            return "cartilla"
        if any(w in msg for w in ["después", "mañana", "lo pienso", "necesito pensar"]):
            return "esperar"
        if any(w in msg for w in ["no conozco", "nunca escuché", "no me da confianza"]):
            return "confianza"
        if any(w in msg for w in ["no tengo tiempo", "ocupado", "después vemos"]):
            return "tiempo"
        return "general"

    def _calcular_interes(
        self,
        context: CommercialConversationContext,
        lead: Lead,
        accion: str,
        mensaje: str,
    ) -> int:
        """Calcula el nivel de interés (0-100)."""
        nivel = context.nivel_interes

        # Señales de interés alto
        if any(w in mensaje.lower() for w in [
            "quiero", "necesito", "cotizame", "avanzamos",
            "dale", "estoy dentro", "contratar",
        ]):
            nivel = min(nivel + 25, 100)

        # Señales de interés medio
        if any(w in mensaje.lower() for w in [
            "info", "información", "contame", "decime",
            "cuánto", "precio",
        ]):
            nivel = min(nivel + 10, 100)

        # Señales de bajo interés / objeción
        if accion == "MANEJAR_OBJECION":
            nivel = max(nivel - 10, 0)

        # Señales de muy alto interés
        if accion == "CERRAR":
            nivel = 100

        # Si el lead respondió con datos (edad, localidad, etc.)
        if context.ya_tiene("edad") or context.ya_tiene("localidad"):
            nivel = min(nivel + 5, 100)

        return nivel

    def _etiquetar_interes(self, nivel: int) -> str:
        """Convierte nivel numérico a etiqueta."""
        for umbral, etiqueta in _ETIQUETA_INTERES:
            if nivel >= umbral:
                return etiqueta
        return "BAJO"

    def _calcular_riesgo(
        self,
        context: CommercialConversationContext,
        lead: Lead,
        accion: str,
    ) -> str:
        """Calcula el riesgo de perder la venta."""
        if accion == "CERRAR":
            return "BAJO"
        if context.objeciones_detectadas:
            if len(context.objeciones_detectadas) >= 3:
                return "ALTO"
            return "MEDIO"
        if context.nivel_interes < 30:
            return "MEDIO"
        if context.ultima_actualizacion:
            now = datetime.now(timezone.utc)
            ultima = context.ultima_actualizacion
            if ultima.tzinfo is None:
                ultima = ultima.replace(tzinfo=timezone.utc)
            horas = (now - ultima).total_seconds() / 3600
            if horas > 48:
                return "ALTO"
            if horas > 24:
                return "MEDIO"
        return "BAJO"


# ── Singleton ──
_instance: CommercialMemory | None = None


def get_memory(dias_inactividad: int = 7) -> CommercialMemory:
    """
    Obtiene la instancia singleton de CommercialMemory.

    Args:
        dias_inactividad: Días antes de reiniciar contexto inactivo.

    Returns:
        Instancia compartida de CommercialMemory.
    """
    global _instance
    if _instance is None:
        _instance = CommercialMemory(dias_inactividad=dias_inactividad)
    return _instance
