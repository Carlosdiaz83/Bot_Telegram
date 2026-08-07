"""
Auto-entrenamiento diario de Sofía (Sprint 29).

Cierra el ciclo de auto-mejora:

1. Entrena con simulaciones (TrainingEngine) y guarda los scores en DB.
2. Extrae lecciones desde los errores detectados en el entrenamiento.
3. Calcula la evolución y la deja disponible para el panel.

El scheduler tolera el free tier de Render: al despertar, si el último
entrenamiento tiene más de ``stale_horas`` horas, ejecuta un ciclo; luego
programa el siguiente en 24h.

Uso:
    from app.services.auto_trainer import AutoTrainer, AutoTrainerScheduler
    trainer = AutoTrainer(database_url)
    resumen = trainer.ejecutar_ciclo()
    scheduler = AutoTrainerScheduler(database_url)
    scheduler.iniciar()
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class AutoTrainer:
    """Ejecuta un ciclo completo de auto-entrenamiento."""

    def __init__(
        self,
        database_url: str,
        db_factory: Optional[Callable[[], object]] = None,
    ) -> None:
        self._database_url = database_url
        self._db_factory = db_factory

    def _factory(self) -> Callable[[], object]:
        if self._db_factory is not None:
            return self._db_factory
        from app.database.database import get_engine, get_session_factory
        return get_session_factory(get_engine(self._database_url))

    def _ultimo_entrenamiento(self) -> Optional[datetime]:
        """Devuelve la fecha del último entrenamiento guardado, o None."""
        try:
            from app.database.repository import TrainingRepository
            db = self._factory()()
            try:
                repo = TrainingRepository(db)
                historial = repo.historial(limit=1)
                if not historial:
                    return None
                return historial[0].creado
            finally:
                db.close()
        except Exception as e:
            logger.warning("[TRAINER] No se pudo leer último entrenamiento: %s", e)
            return None

    def _entrenar(self) -> int:
        """Corre las simulaciones y devuelve cuántas sesiones se guardaron."""
        try:
            from app.training.engine import TrainingEngine
            entrenador = TrainingEngine(database_url=self._database_url)
            resultados = entrenador.ejecutar_todos()
            logger.info(
                "[TRAINER] Entrenamiento completado: %d perfiles",
                len(resultados),
            )
            return len(resultados)
        except Exception as e:
            logger.error("[TRAINER] Error en entrenamiento: %s", e, exc_info=True)
            return 0

    def _extraer_lecciones(self) -> int:
        """Extrae lecciones desde los errores de los entrenamientos."""
        try:
            from app.services.lessons_service import LessonsService
            svc = LessonsService(self._factory())
            svc.sembrar_base()
            return svc.extraer_desde_entrenamiento()
        except Exception as e:
            logger.warning("[TRAINER] Error extrayendo lecciones: %s", e)
            return 0

    def _resumen_evolucion(self) -> dict:
        """Calcula la evolución histórica."""
        try:
            from app.services.commercial_evolution_service import CommercialEvolutionService
            db = self._factory()()
            try:
                evo_svc = CommercialEvolutionService(db)
                evolucion = evo_svc.obtener_evolucion()
                return {
                    "total_entrenamientos": evolucion.total_entrenamientos,
                    "primer_score": evolucion.primer_score,
                    "ultimo_score": evolucion.ultimo_score,
                    "mejora": evolucion.mejora,
                    "debilidades": evolucion.debilidades_principales[:3],
                    "fortalezas": evolucion.fortalezas[:3],
                    "errores_frecuentes": [
                        f"{tipo} (x{cant})" for tipo, cant in evolucion.errores_frecuentes[:5]
                    ],
                }
            finally:
                db.close()
        except Exception as e:
            logger.warning("[TRAINER] Error calculando evolución: %s", e)
            return {}

    def ejecutar_ciclo(self) -> dict:
        """
        Ejecuta un ciclo completo de auto-mejora.

        Returns:
            Dict con resumen: entrenados, lecciones_nuevas, evolucion.
        """
        logger.info("[TRAINER] === Iniciando ciclo de auto-entrenamiento ===")
        sembradas = 0
        try:
            from app.services.lessons_service import LessonsService
            sembradas = LessonsService(self._factory()).sembrar_base()
        except Exception as e:
            logger.warning("[TRAINER] Error sembrando lecciones: %s", e)

        entrenados = self._entrenar()
        lecciones = self._extraer_lecciones()
        evolucion = self._resumen_evolucion()

        resumen = {
            "entrenados": entrenados,
            "lecciones_sembradas": sembradas,
            "lecciones_nuevas": lecciones,
            "evolucion": evolucion,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        logger.info(
            "[TRAINER] Ciclo completado — entrenados=%d, lecciones_nuevas=%d, "
            "mejora=%s",
            entrenados, lecciones, evolucion.get("mejora", "n/a"),
        )
        return resumen


class AutoTrainerScheduler:
    """
    Programa ciclos de auto-entrenamiento: al iniciar si está obsoleto y
    cada 24 horas. Corre en un hilo daemon para no bloquear el webhook.
    """

    def __init__(
        self,
        database_url: str,
        *,
        stale_horas: float = 20.0,
        intervalo_horas: float = 24.0,
        check_segundos: float = 60.0,
        on_ciclo: Optional[Callable[[dict], None]] = None,
    ) -> None:
        self._trainer = AutoTrainer(database_url)
        self._stale_horas = stale_horas
        self._intervalo_horas = intervalo_horas
        self._check_segundos = check_segundos
        self._on_ciclo = on_ciclo
        self._thread: Optional[threading.Thread] = None
        self._detener_evento = threading.Event()
        self._ultima_ejecucion: Optional[datetime] = None

    def _debe_ejecutar(self) -> bool:
        ahora = datetime.now(timezone.utc)

        # No re-ejecutar dentro del intervalo, aunque el entrenamiento
        # no haya quedado guardado en DB.
        if self._ultima_ejecucion is not None:
            delta = (ahora - self._ultima_ejecucion).total_seconds() / 3600
            if delta < self._intervalo_horas:
                return False

        ultimo = self._trainer._ultimo_entrenamiento()
        if ultimo is None:
            return True
        if ultimo.tzinfo is None:
            ultimo = ultimo.replace(tzinfo=timezone.utc)
        horas = (ahora - ultimo).total_seconds() / 3600
        return horas >= self._stale_horas

    def _loop(self) -> None:
        while not self._detener_evento.is_set():
            try:
                if self._debe_ejecutar():
                    logger.info("[TRAINER] Último entrenamiento obsoleto — ejecutando ciclo")
                    resumen = self._trainer.ejecutar_ciclo()
                    self._ultima_ejecucion = datetime.now(timezone.utc)
                    if self._on_ciclo is not None:
                        try:
                            self._on_ciclo(resumen)
                        except Exception:
                            pass
            except Exception as e:
                logger.error("[TRAINER] Error en loop: %s", e, exc_info=True)

            self._detener_evento.wait(self._check_segundos)

    def iniciar(self) -> None:
        """Arranca el scheduler en un hilo daemon."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._loop,
            daemon=True,
            name="auto-trainer",
        )
        self._thread.start()
        logger.info(
            "[TRAINER] Scheduler iniciado (stale_horas=%.1f, check=%ds)",
            self._stale_horas, int(self._check_segundos),
        )

    def detener(self) -> None:
        """Detiene el scheduler."""
        self._detener_evento.set()
        logger.info("[TRAINER] Scheduler detenido")
