"""
Servicio de lecciones aprendidas por Sofía (Sprint 29).

Es el "bucle de feedback" del ciclo de auto-mejora:

1. AUTO-ENTRENAMIENTO → extrae lecciones de los errores detectados
   en las simulaciones (TrainingEngine).
2. CONVERSACIONES REALES → extrae lecciones de patrones de error
   en el historial guardado en la DB.
3. HUMANO (panel) → Sofía puede agregar/toggle/votar lecciones.

Las lecciones activas se inyectan en el prompt del LLM en cada llamada,
así Sofía comunica mejor con el tiempo sin tocar código.

Uso:
    from app.services.lessons_service import LessonsService
    svc = LessonsService(db_factory)
    svc.extraer_desde_entrenamiento()
    texto = svc.bloque_para_prompt(limit=5)
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# Lecciones base: el conocimiento comercial que Sofía ya sabe y que se
# usa como semilla del bucle de feedback (se agregan si faltan).
_LECCIONES_BASE: list[dict[str, str]] = [
    {
        "categoria": "flujo",
        "titulo": "No cotizar sin diagnosticar",
        "texto": "NUNCA cotizar precios antes de conocer el tipo de afiliación "
                 "y el grupo familiar del cliente. Primero diagnosticá, después cotizá.",
        "contexto": "cuánto vale, precio, planes desde, costo",
        "fuente": "base",
    },
    {
        "categoria": "tono",
        "titulo": "Personalizar con el nombre",
        "texto": "Personalizá las respuestas con el nombre y datos del cliente "
                 "para generar confianza.",
        "contexto": "",
        "fuente": "base",
    },
    {
        "categoria": "cierre",
        "titulo": "Avanzar ante interés",
        "texto": "Cuando el cliente muestra interés, proponé el siguiente paso "
                 "concreto (avanzar a cotización, afiliación, asesor).",
        "contexto": "quiero, me interesa, avancemos, dale",
        "fuente": "base",
    },
    {
        "categoria": "objeciones",
        "titulo": "Validar antes de responder",
        "texto": "Ante una objeción (precio, cartilla, confianza), primero validá "
                 "la preocupación del cliente y después respondé.",
        "contexto": "caro, cartilla, no conozco, confianza",
        "fuente": "base",
    },
]

# Errores de entrenamiento → lecciones.
_ERROR_A_LECCION: dict[str, dict[str, str]] = {
    "cotizacion_sin_diagnostico": {
        "categoria": "flujo",
        "titulo": "No cotizar sin diagnosticar",
        "texto": "NUNCA cotizar precios sin antes conocer el tipo de afiliación "
                 "y grupo familiar del cliente.",
        "contexto": "cuánto vale, precio, planes desde",
    },
    "falta_avance": {
        "categoria": "cierre",
        "titulo": "Avanzar ante interés",
        "texto": "Cuando el cliente muestra interés, intentá avanzar al siguiente "
                 "paso comercial.",
        "contexto": "me interesa, avancemos",
    },
    "descuento_inmediato": {
        "categoria": "objeciones",
        "titulo": "No ofrecer descuentos sin investigar el valor",
        "texto": "No ofrezcas descuentos antes de entender qué valora el cliente.",
        "contexto": "descuento, promoción",
    },
    "sin_personalizacion": {
        "categoria": "tono",
        "titulo": "Personalizar con el nombre",
        "texto": "Personalizá las respuestas con el nombre y datos del cliente.",
        "contexto": "",
    },
    "cierre_prematuro": {
        "categoria": "flujo",
        "titulo": "Completar la calificación antes de cerrar",
        "texto": "No intentes cerrar la venta antes de completar la calificación "
                 "del cliente.",
        "contexto": "avancemos, quiero avanzar",
    },
}


class LessonsService:
    """
    Gestión de lecciones y su inyección en el prompt del LLM.
    """

    def __init__(self, db_factory: Optional[Callable[[], Any]] = None) -> None:
        self._db_factory = db_factory
        self._repo = None

    def _obtener_repo(self):
        from app.database.repository import SofiaLessonsRepository

        if self._db_factory is None:
            from app.database.database import get_session_factory, get_engine
            self._db_factory = get_session_factory(get_engine())

        db = self._db_factory()
        return SofiaLessonsRepository(db), db

    def _con_db(self, fn):
        """Ejecuta fn(repo, db) en una sesión nueva y la cierra."""
        repo, db = self._obtener_repo()
        try:
            return fn(repo)
        finally:
            db.close()

    # ── CRUD ──

    def agregar(
        self,
        titulo: str,
        texto: str,
        *,
        categoria: str = "flujo",
        contexto: Optional[str] = None,
        fuente: str = "auto",
        activo: bool = True,
        dedupe: bool = True,
    ) -> Any:
        """Agrega una lección. Si dedupe y ya existe igual, la devuelve."""
        if dedupe:
            existente = self._con_db(lambda repo: repo.buscar_por_texto(texto))
            if existente is not None:
                return existente
        return self._con_db(
            lambda repo: repo.crear(
                titulo=titulo, texto=texto, categoria=categoria,
                contexto=contexto, fuente=fuente, activo=activo,
            )
        )

    def listar(self, activo: Optional[bool] = None, categoria: Optional[str] = None) -> list:
        return self._con_db(
            lambda repo: repo.listar(activo=activo, categoria=categoria)
        )

    def obtener(self, leccion_id: int):
        """Obtiene una lección por id o None."""
        return self._con_db(lambda repo: repo.obtener(leccion_id))

    def activar(self, leccion_id: int, activo: bool) -> bool:
        return (
            self._con_db(lambda repo: repo.actualizar(leccion_id, activo=activo))
            is not None
        )

    def votar(self, leccion_id: int, delta: int) -> bool:
        def _votar(repo):
            leccion = repo.obtener(leccion_id)
            if leccion is None:
                return False
            repo.actualizar(leccion_id, votos=(leccion.votos or 0) + delta)
            return True
        return self._con_db(_votar)

    # ── Extracción automática ──

    def extraer_desde_entrenamiento(self) -> int:
        """
        Extrae lecciones desde los errores de los últimos entrenamientos
        guardados en la DB. Devuelve cuántas lecciones nuevas se crearon.
        """
        try:
            from app.database.repository import TrainingRepository
            from app.database.models import TrainingSessionDB
            from sqlalchemy import select

            def _recolectar(db):
                stmt = (
                    select(TrainingSessionDB.errores_detectados)
                    .order_by(TrainingSessionDB.creado.desc())
                    .limit(100)
                )
                return [r for (r,) in db.execute(stmt).all()]

            repo, db = self._obtener_repo()
            try:
                errores_total: dict[str, int] = {}
                for errores_json in _recolectar(db):
                    try:
                        errores = json.loads(errores_json or "[]")
                    except (json.JSONDecodeError, TypeError):
                        continue
                    if not isinstance(errores, list):
                        continue
                    for error in errores:
                        tipo = None
                        if isinstance(error, dict):
                            tipo = error.get("tipo")
                        elif isinstance(error, str):
                            tipo = error
                        if tipo and tipo in _ERROR_A_LECCION:
                            errores_total[tipo] = errores_total.get(tipo, 0) + 1

                nuevas = 0
                for tipo, cantidad in errores_total.items():
                    plantilla = _ERROR_A_LECCION[tipo]
                    existente = repo.buscar_por_texto(plantilla["texto"])
                    if existente is None:
                        repo.crear(
                            titulo=plantilla["titulo"],
                            texto=plantilla["texto"],
                            categoria=plantilla["categoria"],
                            contexto=plantilla["contexto"],
                            fuente="entrenamiento",
                        )
                        nuevas += 1
                        logger.info(
                            "[LEARNING] Lección desde entrenamiento (%s) ×%d",
                            tipo, cantidad,
                        )
                return nuevas
            finally:
                db.close()
        except Exception as e:
            logger.warning("[LEARNING] Error extrayendo lecciones: %s", e)
            return 0

    def sembrar_base(self) -> int:
        """Inserta las lecciones base si no existen. Devuelve cuántas se crearon."""
        creadas = 0
        for leccion in _LECCIONES_BASE:
            self.agregar(
                leccion["titulo"],
                leccion["texto"],
                categoria=leccion["categoria"],
                contexto=leccion.get("contexto") or None,
                fuente=leccion["fuente"],
            )
            creadas += 1
        return creadas

    # ── Inyección en el prompt ──

    def bloque_para_prompt(self, limit: int = 5) -> str:
        """
        Devuelve un bloque de texto con las lecciones activas mejor
        puntuadas, listo para inyectar en el system prompt del LLM.

        Returns:
            Texto con formato, o "" si no hay lecciones.
        """
        try:
            lecciones = self._con_db(
                lambda repo: repo.listar(activo=True, limit=limit)
            )
        except Exception as e:
            logger.warning("[LEARNING] Error leyendo lecciones: %s", e)
            return ""

        if not lecciones:
            return ""

        lineas = []
        for leccion in lecciones:
            texto = leccion.texto.strip()
            if leccion.contexto:
                texto = f"{texto} (aplica cuando: {leccion.contexto})"
            lineas.append(f"- {texto}")

        return "Lecciones aprendidas que DEBES aplicar al comunicarte:\n" + "\n".join(lineas)

    def aplicar_al_prompt(self, mensajes: list[dict[str, str]], limit: int = 5) -> list[dict[str, str]]:
        """
        Inyecta las lecciones activas como mensaje system del prompt.

        Args:
            mensajes: Lista de mensajes formato OpenAI.
            limit: Máximo de lecciones.

        Returns:
            La misma lista (mutada) con un system message de lecciones
            agregado después del primer system message.
        """
        bloque = self.bloque_para_prompt(limit=limit)
        if not bloque:
            return mensajes

        # Registrar usos
        try:
            repo, db = self._obtener_repo()
            try:
                lecciones = repo.listar(activo=True, limit=limit)
                for leccion in lecciones:
                    repo.registrar_uso(leccion.id)
            finally:
                db.close()
        except Exception:
            pass

        if mensajes and mensajes[0].get("role") == "system":
            mensajes.insert(1, {"role": "system", "content": bloque})
        else:
            mensajes.insert(0, {"role": "system", "content": bloque})
        return mensajes
