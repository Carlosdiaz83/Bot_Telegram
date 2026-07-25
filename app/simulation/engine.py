"""
Motor de simulación de conversaciones comerciales.

Ejecuta conversaciones simuladas contra un ConversationManager
para evaluar el comportamiento de Sofía.

Uso:
    from app.simulation.engine import SimuladorConversacion
    from app.services.conversation_manager import ConversationManager
    sim = SimuladorConversacion(ConversationManager())
    resultado = sim.simular(perfil)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.simulation.profiles import ClienteProfile
from app.services.conversation_manager import ConversationManager

logger = logging.getLogger(__name__)


@dataclass
class IntercambioSimulacion:
    """
    Un intercambio de mensajes en la simulación.

    Attributes:
        mensaje_cliente: Mensaje enviado por el cliente virtual.
        respuesta_sofia: Respuesta generada por Sofía.
        numero: Número de intercambio (1, 2, 3...).
    """
    numero: int
    mensaje_cliente: str
    respuesta_sofia: str


@dataclass
class ResultadoSimulacion:
    """
    Resultado completo de una simulación.

    Attributes:
        perfil: Perfil del cliente utilizado.
        intercambios: Lista de intercambios (mensaje → respuesta).
        estado_final: Estado comercial final del lead.
        lead_final: Modelo Lead al finalizar.
        score_final: Score del lead al finalizar.
        temperatura_final: Temperatura del lead al finalizar.
        etapa_final: Etapa de conversación al finalizar.
        cantidad_mensajes: Total de mensajes intercambiados.
        exitosa: Si la conversación llegó a un buen resultado.
    """
    perfil: ClienteProfile
    intercambios: list[IntercambioSimulacion] = field(default_factory=list)
    estado_final: str = ""
    lead_final: object = None
    score_final: int = 0
    temperatura_final: str = ""
    etapa_final: str = ""
    cantidad_mensajes: int = 0
    exitosa: bool = False


class SimuladorConversacion:
    """
    Simulador de conversaciones comerciales.

    Ejecuta una secuencia de mensajes predefinidos contra un
    ConversationManager y registra cada intercambio.
    """

    def __init__(self, manager: ConversationManager) -> None:
        """
        Inicializa el simulador.

        Args:
            manager: ConversationManager a utilizar.
        """
        self._manager = manager
        self._contador_telegram_id = 90000

    def _generar_telegram_id(self) -> int:
        """Genera un telegram_id único para cada simulación."""
        self._contador_telegram_id += 1
        return self._contador_telegram_id

    def simular(self, perfil: ClienteProfile) -> ResultadoSimulacion:
        """
        Ejecuta una conversación completa con un perfil de cliente.

        Args:
            perfil: Perfil del cliente a simular.

        Returns:
            ResultadoSimulacion con todos los intercambios y el estado final.
        """
        logger.info("Iniciando simulación con perfil: %s", perfil.nombre)

        telegram_id = self._generar_telegram_id()
        resultado = ResultadoSimulacion(perfil=perfil)

        for i, mensaje in enumerate(perfil.mensajes, 1):
            logger.debug(
                "Simulación %s — mensaje %d/%d: %s",
                perfil.nombre,
                i,
                len(perfil.mensajes),
                mensaje[:50],
            )

            respuesta = self._manager.procesar_mensaje(telegram_id, mensaje)

            intercambio = IntercambioSimulacion(
                numero=i,
                mensaje_cliente=mensaje,
                respuesta_sofia=respuesta,
            )
            resultado.intercambios.append(intercambio)

        resultado.cantidad_mensajes = len(resultado.intercambios)

        # Obtener estado final del lead
        session = self._manager.session_manager.get(telegram_id)
        if session:
            lead = session.lead
            resultado.lead_final = lead
            resultado.estado_final = lead.estado_comercial.value
            resultado.score_final = lead.score
            resultado.temperatura_final = lead.temperatura_lead
            resultado.etapa_final = session.etapa.value
            resultado.exitosa = self._evaluar_exito(lead.estado_comercial.value)

        logger.info(
            "Simulación %s completada — estado: %s, score: %d, temperatura: %s",
            perfil.nombre,
            resultado.estado_final,
            resultado.score_final,
            resultado.temperatura_final,
        )

        return resultado

    def simular_multiples(self, perfiles: list[ClienteProfile]) -> list[ResultadoSimulacion]:
        """
        Ejecuta múltiples simulaciones.

        Args:
            perfiles: Lista de perfiles a simular.

        Returns:
            Lista de resultados.
        """
        resultados = []
        for perfil in perfiles:
            resultado = self.simular(perfil)
            resultados.append(resultado)
        return resultados

    @staticmethod
    def _evaluar_exito(estado_final: str) -> bool:
        """
        Evalúa si la conversación tuvo un resultado exitoso.

        Args:
            estado_final: Estado comercial al finalizar.

        Returns:
            True si el resultado es exitoso.
        """
        estados_exitosos = {"vendido", "seguimiento", "calificado"}
        return estado_final.lower() in estados_exitosos
