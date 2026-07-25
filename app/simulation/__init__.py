"""
Simulador de conversaciones comerciales.

Permite simular interacciones con clientes virtuales
para evaluar la capacidad comercial de Sofía.

Uso:
    from app.simulation import SimuladorConversacion, PERFILES_CLIENTES
    from app.services.conversation_manager import ConversationManager
    sim = SimuladorConversacion(ConversationManager())
    resultado = sim.simular(PERFILES_CLIENTES["cliente_frio"])
"""

from app.simulation.profiles import (
    ClienteProfile,
    PERFILES_CLIENTES,
    obtener_perfil,
    listar_perfiles,
)
from app.simulation.engine import (
    SimuladorConversacion,
    ResultadoSimulacion,
    IntercambioSimulacion,
)

__all__ = [
    "ClienteProfile",
    "PERFILES_CLIENTES",
    "obtener_perfil",
    "listar_perfiles",
    "SimuladorConversacion",
    "ResultadoSimulacion",
    "IntercambioSimulacion",
]
