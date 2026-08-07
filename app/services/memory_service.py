"""
Memoria persistente de Sofía (Sprint 29).

Permite que Sofía "aprenda" a lo largo de TODAS las conversaciones
con cada usuario: guarda un resumen persistente con datos clave,
objeciones, intereses y preferencias en la base de datos.

REGLA DE VENDEDOR: el flujo "soy vendedor" nunca escribe en la memoria
del usuario (cada cotización es un lead distinto y no debe mezclarse
con la memoria personal del vendedor). Tampoco se inyecta la memoria
persistente en una sesión de vendedor: el ciclo de cotización arranca
en limpio.

Uso:
    from app.services.memory_service import SofiaMemoryService
    mem = SofiaMemoryService(db_factory)
    resumen = mem.cargar(chat_id)          # dict o None
    mem.guardar_desde_sesion(chat_id, lead, session)
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

_OBJECIONES_PALABRAS: dict[str, list[str]] = {
    "precio": ["caro", "costoso", "muy caro", "no llego", "pago mucho", "precio alto"],
    "cartilla": ["cartilla", "prestador", "médico", "hospital", "cobertura"],
    "esperar": ["después", "mañana", "lo pienso", "necesito pensar", "más adelante"],
    "confianza": ["no conozco", "nunca escuché", "no me da confianza", "desconfío"],
    "tiempo": ["no tengo tiempo", "ocupado", "después vemos"],
}


def _detectar_objecion(mensaje: str) -> Optional[str]:
    """Detecta el tipo de objeción en un mensaje del usuario."""
    msg = (mensaje or "").lower()
    for tipo, palabras in _OBJECIONES_PALABRAS.items():
        if any(p in msg for p in palabras):
            return tipo
    return None


class SofiaMemoryService:
    """
    Servicio de memoria persistente por chat.

    Args:
        db_factory: Callable que devuelve una sesión de SQLAlchemy.
    """

    def __init__(self, db_factory: Optional[Callable[[], Any]] = None) -> None:
        self._db_factory = db_factory
        self._repo = None

    def _obtener_repo(self):
        """Crea el repositorio con una sesión nueva (por operación)."""
        from app.database.repository import SofiaMemoryRepository

        if self._db_factory is None:
            from app.database.database import get_session_factory, get_engine
            self._db_factory = get_session_factory(get_engine())

        db = self._db_factory()
        return SofiaMemoryRepository(db), db

    # ── Lectura ──

    def cargar(self, chat_id: int) -> Optional[dict]:
        """Carga la memoria persistente de un chat. None si no existe."""
        try:
            repo, db = self._obtener_repo()
            try:
                memoria = repo.buscar(chat_id)
                if memoria is None:
                    return None
                return repo.to_dict(memoria)
            finally:
                db.close()
        except Exception as e:
            logger.warning("[MEMORY] Error cargando memoria %s: %s", chat_id, e)
            return None

    def resumen_para_llm(self, chat_id: int, max_objeciones: int = 3) -> str:
        """
        Devuelve un bloque de texto legible con lo que Sofía recuerda
        del usuario, para inyectarlo en el prompt del LLM.

        Returns:
            Texto en español, o "" si no hay memoria.
        """
        memoria = self.cargar(chat_id)
        if not memoria:
            return ""

        partes: list[str] = []
        datos = memoria.get("datos_clave") or {}
        nombre = datos.get("nombre")
        if nombre:
            partes.append(f"Sofía recuerda al usuario: {nombre}")
        if datos.get("localidad"):
            partes.append(f"Localidad: {datos['localidad']}")
        if datos.get("tipo_afiliacion"):
            partes.append(f"Su situación laboral: {datos['tipo_afiliacion']}")
        if datos.get("grupo_familiar"):
            partes.append(f"Grupo familiar: {datos['grupo_familiar']}")

        objeciones = memoria.get("objeciones") or []
        if objeciones:
            unicas = list(dict.fromkeys(objeciones))[:max_objeciones]
            partes.append(f"Objeciones que ya planteó: {', '.join(unicas)}")

        preferencias = memoria.get("preferencias") or {}
        if preferencias.get("plan_preferido"):
            partes.append(f"Le interesó el plan: {preferencias['plan_preferido']}")
        if preferencias.get("prioridad"):
            partes.append(f"Su prioridad: {preferencias['prioridad']}")

        resumen = memoria.get("resumen")
        if resumen and len(partes) <= 1:
            partes.append(resumen)

        if not partes:
            return ""
        return "Recuerdos de este usuario:\n- " + "\n- ".join(partes)

    # ── Escritura ──

    def guardar_desde_sesion(
        self,
        chat_id: int,
        lead: Any,
        session: Any = None,
    ) -> None:
        """
        Persiste lo aprendido en esta conversación.

        Respeta el modo vendedor: si session.es_vendedor es True,
        NO se escribe (la memoria del vendedor no se mezcla con la
        del cliente que está cotizando).

        Args:
            chat_id: Telegram id del usuario.
            lead: Lead de dominio con datos del usuario.
            session: UserSession (opcional) para saber si es vendedor.
        """
        if session is not None and getattr(session, "es_vendedor", False):
            return

        if lead is None:
            return

        try:
            repo, db = self._obtener_repo()
            try:
                memoria = repo.buscar(chat_id)
                objeciones = (
                    (repo.to_dict(memoria).get("objeciones") or [])
                    if memoria
                    else []
                )
                intereses = (
                    (repo.to_dict(memoria).get("intereses") or [])
                    if memoria
                    else []
                )
                preferencias = (
                    (repo.to_dict(memoria).get("preferencias") or {})
                    if memoria
                    else {}
                )
                resumen_previo = memoria.resumen if memoria else None

                # Datos clave
                datos = {
                    "nombre": getattr(lead, "nombre", None),
                    "edad": getattr(lead, "edad", None),
                    "localidad": getattr(lead, "localidad", None),
                    "tipo_afiliacion": (
                        getattr(lead, "tipo_afiliacion", None).value
                        if getattr(lead, "tipo_afiliacion", None)
                        else None
                    ),
                    "grupo_familiar": (
                        f"conyuge={lead.grupo_familiar.conyuge}, "
                        f"hijos={lead.grupo_familiar.hijos}"
                        if getattr(lead, "grupo_familiar", None)
                        else None
                    ),
                }

                # Objeciones detectadas en el último mensaje
                ultimo_mensaje = getattr(session, "_ultimo_mensaje", "") or ""
                objecion = _detectar_objecion(ultimo_mensaje)
                if objecion and objecion not in objeciones:
                    objeciones.append(objecion)

                # Intereses detectados
                if getattr(lead, "interes_detectado", None):
                    etiqueta = lead.interes_detectado.value
                    if etiqueta and etiqueta not in intereses:
                        intereses.append(etiqueta)

                # Preferencias
                if getattr(lead, "plan_preferido", None):
                    preferencias["plan_preferido"] = lead.plan_preferido
                if getattr(lead, "prioridad_cliente", None):
                    preferencias["prioridad"] = lead.prioridad_cliente.value

                # Resumen evolutivo: lo último que pasó
                etapa = getattr(session, "etapa", None)
                resumen = resumen_previo or ""
                if etapa is not None and getattr(lead, "nombre", None):
                    nombre = lead.nombre
                    if lead.estado_comercial and lead.estado_comercial.value:
                        resumen = (
                            f"Última interacción con {nombre}: "
                            f"etapa {etapa.value}, estado {lead.estado_comercial.value}."
                        )

                repo.guardar(
                    chat_id,
                    resumen=resumen or None,
                    datos_clave=datos,
                    objeciones=objeciones,
                    intereses=intereses,
                    preferencias=preferencias,
                    ultimo_tema=(
                        getattr(lead, "necesidad_principal", None).value
                        if getattr(lead, "necesidad_principal", None)
                        else None
                    ),
                    ultima_etapa=etapa.value if etapa else None,
                )
                logger.debug(
                    "[MEMORY] Persistida memoria de chat %s — objeciones=%d, intereses=%d",
                    chat_id, len(objeciones), len(intereses),
                )
            finally:
                db.close()
        except Exception as e:
            logger.warning("[MEMORY] Error guardando memoria %s: %s", chat_id, e)
