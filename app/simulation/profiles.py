"""
Perfiles de clientes para simulación comercial.

Cada perfil representa un tipo de cliente con su comportamiento
característico y mensajes predefinidos para simular la conversación.

Uso:
    from app.simulation.profiles import PERFILES_CLIENTES, obtener_perfil
    frio = PERFILES_CLIENTES["cliente_frio"]
    listar_perfil = obtener_perfil("cliente_busca_precio")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ClienteProfile:
    """
    Perfil de un cliente virtual para simulación.

    Attributes:
        nombre: Nombre del perfil (identificador).
        descripcion: Descripción del comportamiento.
        nombre_cliente: Nombre que el cliente dará en la conversación.
        edad: Edad del cliente (None si no la da).
        localidad: Localidad del cliente.
        tipo_afiliacion: Tipo de afiliación del cliente.
        grupo_familiar: Si tiene grupo familiar.
        mensajes: Lista de mensajes que el cliente enviará en orden.
        esperado: Resultado esperado de la conversación.
    """
    nombre: str
    descripcion: str
    nombre_cliente: str
    edad: Optional[int] = None
    localidad: Optional[str] = None
    tipo_afiliacion: Optional[str] = None
    grupo_familiar: Optional[str] = None
    mensajes: list[str] = field(default_factory=list)
    esperado: str = ""


# ─────────────────────────────────────────────
# Perfiles predefinidos
# ─────────────────────────────────────────────

PERFILES_CLIENTES: dict[str, ClienteProfile] = {
    "cliente_frio": ClienteProfile(
        nombre="cliente_frio",
        descripcion="Cliente que no da información fácilmente, respuestas cortas.",
        nombre_cliente="Martín",
        edad=None,
        localidad=None,
        tipo_afiliacion=None,
        grupo_familiar=None,
        mensajes=[
            "Hola",
            "Quiero saber de obras sociales",
            "No sé, algo barato",
            "Depende",
            "No sé si me conviene",
        ],
        esperado="El lead debería quedar en estado CALIFICANDO con datos mínimos.",
    ),

    "cliente_busca_precio": ClienteProfile(
        nombre="cliente_busca_precio",
        descripcion="Cliente que busca la opción más económica.",
        nombre_cliente="Laura",
        edad=28,
        localidad="Córdoba",
        tipo_afiliacion="particular",
        grupo_familiar="solo_titular",
        mensajes=[
            "Hola, busco algo barato para obra social",
            "Me llamo Laura",
            "No tengo obra social, busco algo económico",
            "Soy particular",
            "Sola, solo yo",
            "Tengo 28 años",
            "Soy de Córdoba",
            "¿Cuánto cuesta?",
        ],
        esperado="Lead con prioridad ECONOMICO, score bajo-medio, temperatura tibio.",
    ),

    "cliente_busca_cobertura_familiar": ClienteProfile(
        nombre="cliente_busca_cobertura_familiar",
        descripcion="Cliente que busca cobertura para toda la familia.",
        nombre_cliente="Carlos",
        edad=35,
        localidad="Rosario",
        tipo_afiliacion="relacion_dependencia",
        grupo_familiar="conyuge_hijos",
        mensajes=[
            "Hola, necesito cobertura para mi familia",
            "Me llamo Carlos",
            "Recibo de sueldo, empleado",
            "Tengo esposa y 2 hijos",
            "35 años",
            "De Rosario",
            "Quiero que todos estén cubiertos",
        ],
        esperado="Lead con necesidad COBERTURA_FAMILIAR, grupo familiar completo, score alto.",
    ),

    "cliente_monotributista": ClienteProfile(
        nombre="cliente_monotributista",
        descripcion="Monotributista que busca opciones para su situación.",
        nombre_cliente="Sofía M.",
        edad=42,
        localidad="Mendoza",
        tipo_afiliacion="monotributo",
        grupo_familiar="conyuge",
        mensajes=[
            "Hola, soy monotributista y quiero obra social",
            "Me llamo Sofía",
            "Monotributista, categoría B",
            "Tengo esposo",
            "42 años",
            "De Mendoza",
        ],
        esperado="Lead con tipo_afiliacion MONOTRIBUTO, argumento específico, score medio-alto.",
    ),

    "cliente_relacion_dependencia": ClienteProfile(
        nombre="cliente_relacion_dependencia",
        descripcion="Empleado en relación de dependencia buscando cobertura.",
        nombre_cliente="Pablo",
        edad=30,
        localidad="Buenos Aires",
        tipo_afiliacion="relacion_dependencia",
        grupo_familiar="solo_titular",
        mensajes=[
            "Hola, trabajo en relación de dependencia",
            "Me llamo Pablo",
            "Tengo recibo de sueldo",
            "Solo para mí",
            "30 años",
            "De Buenos Aires",
        ],
        esperado="Lead con tipo_afiliacion RELACION_DEPENDENCIA, tiene aportes, score medio.",
    ),

    "cliente_objecion_precio": ClienteProfile(
        nombre="cliente_objecion_precio",
        descripcion="Cliente que acepta al principio pero objeta por precio.",
        nombre_cliente="Ana",
        edad=38,
        localidad="Tucumán",
        tipo_afiliacion="particular",
        grupo_familiar="conyuge_hijos",
        mensajes=[
            "Hola, quiero saber de cobertura",
            "Me llamo Ana",
            "Busco algo para mi familia",
            "Tengo esposo y 1 hijo",
            "38 años",
            "De Tucumán",
            "Es muy caro, no llego",
            "Tengo que pensarlo",
        ],
        esperado="Lead con objeción PRECIO detectada, manejada, score medio.",
    ),

    "cliente_indeciso": ClienteProfile(
        nombre="cliente_indeciso",
        descripcion="Cliente que nunca se decide, siempre posterga.",
        nombre_cliente="Roberto",
        edad=50,
        localidad="La Plata",
        tipo_afiliacion="relacion_dependencia",
        grupo_familiar="conyuge",
        mensajes=[
            "Hola, quería saber",
            "Me llamo Roberto",
            "Recibo de sueldo",
            "Tengo esposa",
            "50 años",
            "De La Plata",
            "Tengo que pensarlo",
            "No sé, después veo",
            "Mañana hablamos",
        ],
        esperado="Lead con múltiples objeciones PROCRASTINACION, derivado a asesor o SEGUIMIENTO.",
    ),

    "cliente_listo_para_contratar": ClienteProfile(
        nombre="cliente_listo_para_contratar",
        descripcion="Cliente que da todos los datos y acepta avanzar.",
        nombre_cliente="María",
        edad=33,
        localidad="Santa Fe",
        tipo_afiliacion="monotributo",
        grupo_familiar="conyuge_hijos",
        mensajes=[
            "Hola, quiero afiliarme",
            "Me llamo María",
            "Soy monotributista categoría B",
            "Tengo esposo y 2 hijos",
            "33 años",
            "De Santa Fe",
            "Sí, quiero avanzar",
            "Dale, avancemos",
        ],
        esperado="Lead VENDIDO, score alto, temperatura caliente.",
    ),
}


def obtener_perfil(nombre: str) -> ClienteProfile | None:
    """
    Obtiene un perfil por nombre.

    Args:
        nombre: Identificador del perfil.

    Returns:
        ClienteProfile o None si no existe.
    """
    return PERFILES_CLIENTES.get(nombre)


def listar_perfiles() -> list[str]:
    """
    Lista los nombres de todos los perfiles disponibles.

    Returns:
        Lista de nombres de perfiles.
    """
    return list(PERFILES_CLIENTES.keys())
