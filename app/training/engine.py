"""
Motor de entrenamiento comercial.

Orquesta simulaciones, evaluación, reglas de calidad
y detección de errores para entrenar a Sofía.

Uso:
    from app.training.engine import TrainingEngine
    trainer = TrainingEngine()
    resultado = trainer.ejecutar(perfil="cliente_busca_precio")
    print(resultado.score_final)
    for error in resultado.errores:
        print(error.tipo, error.descripcion)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from app.simulation.engine import SimuladorConversacion, ResultadoSimulacion
from app.simulation.profiles import PERFILES_CLIENTES, obtener_perfil, listar_perfiles
from app.services.conversation_manager import ConversationManager
from app.services.sales_evaluator import SalesEvaluatorService, EvaluacionComercial

logger = logging.getLogger(__name__)


@dataclass
class ErrorComercial:
    """
    Error detectado en la conversación.

    Attributes:
        tipo: Identificador del error (ej: "cotizacion_sin_diagnostico").
        descripcion: Descripción legible del error.
        mensaje_cliente: Mensaje del cliente que provocó el error.
        respuesta_sofia: Respuesta de Sofía que contenía el error.
        gravedad: "alta", "media" o "baja".
    """
    tipo: str
    descripcion: str
    mensaje_cliente: str = ""
    respuesta_sofia: str = ""
    gravedad: str = "media"


@dataclass
class ResultadoEntrenamiento:
    """
    Resultado completo de un entrenamiento.

    Attributes:
        perfil: Nombre del perfil utilizado.
        resultado_simulacion: Resultado de la simulación.
        evaluacion: Evaluación comercial.
        errores: Lista de errores detectados.
        recomendaciones: Lista de recomendaciones.
        score_final: Score final (0-100).
    """
    perfil: str
    resultado_simulacion: ResultadoSimulacion
    evaluacion: EvaluacionComercial
    errores: list[ErrorComercial] = field(default_factory=list)
    recomendaciones: list[str] = field(default_factory=list)
    score_final: int = 0


class TrainingEngine:
    """
    Motor de entrenamiento comercial.

    Ejecuta simulaciones contra el ConversationManager,
    las evalúa, detecta errores y genera recomendaciones.
    Opcionalmente guarda los resultados en DB para análisis de evolución.
    """

    def __init__(self, database_url: Optional[str] = None) -> None:
        self._manager = ConversationManager()
        self._simulador = SimuladorConversacion(self._manager)
        self._evaluador = SalesEvaluatorService()
        self._db_enabled = database_url is not None
        self._db_factory = None
        if self._db_enabled:
            from app.database.database import get_engine, get_session_factory, crear_tablas
            engine = get_engine(database_url)
            crear_tablas(engine)
            self._db_factory = get_session_factory(engine)

    def ejecutar(self, perfil: str) -> ResultadoEntrenamiento:
        """
        Ejecuta un entrenamiento completo con un perfil.

        Args:
            perfil: Nombre del perfil a simular.

        Returns:
            ResultadoEntrenamiento con simulación, evaluación, errores y recomendaciones.
        """
        profile = obtener_perfil(perfil)
        if profile is None:
            raise ValueError(f"Perfil no encontrado: {perfil}")

        logger.info("Ejecutando entrenamiento con perfil: %s", perfil)

        # 1. Simular
        resultado_sim = self._simulador.simular(profile)

        # 2. Evaluar
        evaluacion = self._evaluador.evaluar(resultado_sim)

        # 3. Detectar errores
        errores = self._detectar_errores(resultado_sim)

        # 4. Generar recomendaciones
        recomendaciones = self._generar_recomendaciones(evaluacion, errores)

        # 5. Calcular score final (score - penalización por errores)
        penalizacion = sum(
            15 if e.gravedad == "alta" else 10 if e.gravedad == "media" else 5
            for e in errores
        )
        score_final = max(0, evaluacion.score_total - penalizacion)

        resultado = ResultadoEntrenamiento(
            perfil=perfil,
            resultado_simulacion=resultado_sim,
            evaluacion=evaluacion,
            errores=errores,
            recomendaciones=recomendaciones,
            score_final=score_final,
        )

        logger.info(
            "Entrenamiento %s completado — score: %d, errores: %d",
            perfil,
            score_final,
            len(errores),
        )

        # 6. Guardar en DB si está habilitado
        if self._db_enabled:
            self._guardar_en_db(resultado)

        return resultado

    def ejecutar_todos(self) -> list[ResultadoEntrenamiento]:
        """
        Ejecuta entrenamiento con todos los perfiles disponibles.

        Returns:
            Lista de resultados, uno por perfil.
        """
        perfiles = listar_perfiles()
        resultados = []
        for perfil in perfiles:
            resultado = self.ejecutar(perfil)
            resultados.append(resultado)
        return resultados

    def ejecutar_lote(self, perfiles: list[str]) -> list[ResultadoEntrenamiento]:
        """
        Ejecuta entrenamiento con un lote de perfiles.

        Args:
            perfiles: Lista de nombres de perfiles.

        Returns:
            Lista de resultados.
        """
        resultados = []
        for perfil in perfiles:
            resultado = self.ejecutar(perfil)
            resultados.append(resultado)
        return resultados

    def _guardar_en_db(self, resultado: ResultadoEntrenamiento) -> None:
        """
        Guarda el resultado del entrenamiento en la base de datos.

        Args:
            resultado: Resultado del entrenamiento a persistir.
        """
        from app.database.repository import TrainingRepository
        session = self._db_factory()
        try:
            repo = TrainingRepository(session)
            repo.guardar({
                "perfil": resultado.perfil,
                "score_total": resultado.score_final,
                "score_descubrimiento": resultado.evaluacion.score_descubrimiento,
                "score_calificacion": resultado.evaluacion.score_calificacion,
                "score_valor": resultado.evaluacion.score_valor,
                "score_objeciones": resultado.evaluacion.score_objeciones,
                "score_cierre": resultado.evaluacion.score_cierre,
                "cantidad_errores": len(resultado.errores),
                "errores": [e.tipo for e in resultado.errores],
                "recomendaciones": resultado.recomendaciones,
            })
            logger.info("Entrenamiento %s guardado en DB", resultado.perfil)
        except Exception as e:
            session.rollback()
            logger.error("Error guardando entrenamiento en DB: %s", str(e))
        finally:
            session.close()

    def _detectar_errores(self, resultado: ResultadoSimulacion) -> list[ErrorComercial]:
        """
        Detecta errores comerciales en la conversación.

        Args:
            resultado: Resultado de la simulación.

        Returns:
            Lista de errores detectados.
        """
        errores: list[ErrorComercial] = []
        lead = resultado.lead_final
        intercambios = resultado.intercambios

        if lead is None or len(intercambios) < 2:
            return errores

        for i, intercambio in enumerate(intercambios):
            msg_cliente = intercambio.mensaje_cliente.lower()
            resp_sofia = intercambio.respuesta_sofia.lower()

            # Error 1: Cotización sin diagnóstico
            if self._es_pregunta_precio(msg_cliente):
                if lead.nombre is None or lead.tipo_afiliacion is None:
                    if any(
                        p in resp_sofia
                        for p in ["desde $", "planes desde", "costo", "precio"]
                    ):
                        errores.append(
                            ErrorComercial(
                                tipo="cotizacion_sin_diagnostico",
                                descripcion=(
                                    "Cotizó precio sin diagnosticar necesidades del cliente."
                                ),
                                mensaje_cliente=intercambio.mensaje_cliente,
                                respuesta_sofia=intercambio.respuesta_sofia,
                                gravedad="alta",
                            )
                        )

            # Error 2: Falta de avance comercial
            if i == len(intercambios) - 2 and lead.estado_comercial.value == "interesado":
                if "avancemos" not in resp_sofia and "querés" not in resp_sofia:
                    errores.append(
                        ErrorComercial(
                            tipo="falta_avance",
                            descripcion=(
                                "No intentó avanzar comercialmente "
                                "cuando el cliente mostró interés."
                            ),
                            mensaje_cliente=intercambio.mensaje_cliente,
                            respuesta_sofia=intercambio.respuesta_sofia,
                            gravedad="alta",
                        )
                    )

            # Error 3: Descuento sin investigar valor
            if any(p in resp_sofia for p in ["descuento", "promoción", "oferta especial"]):
                if any(p in msg_cliente for p in ["caro", "cuesta", "precio", "dinero"]):
                    tiene_necesidad = (
                        lead.necesidad_principal is not None
                        or lead.prioridad_cliente is not None
                    )
                    if not tiene_necesidad:
                        errores.append(
                            ErrorComercial(
                                tipo="descuento_inmediato",
                                descripcion=(
                                    "Ofreció descuento sin investigar "
                                    "el valor percibido por el cliente."
                                ),
                                mensaje_cliente=intercambio.mensaje_cliente,
                                respuesta_sofia=intercambio.respuesta_sofia,
                                gravedad="alta",
                            )
                        )

            # Error 4: Sin personalización
            if i >= 3 and lead.nombre is not None:
                if lead.necesidad_principal is None and lead.prioridad_cliente is None:
                    if any(
                        p in resp_sofia
                        for p in ["servired", "cobertura", "plan"]
                    ):
                        if lead.nombre.lower() not in resp_sofia:
                            errores.append(
                                ErrorComercial(
                                    tipo="sin_personalizacion",
                                    descripcion=(
                                        "Respuesta genérica sin personalizar "
                                        "con datos del cliente."
                                    ),
                                    mensaje_cliente=intercambio.mensaje_cliente,
                                    respuesta_sofia=intercambio.respuesta_sofia,
                                    gravedad="media",
                                )
                            )

            # Error 5: Cierre prematuro
            if i <= 2 and lead.nombre is not None:
                if any(
                    p in resp_sofia
                    for p in ["avancemos", "quiero avanzar", "proceso"]
                ):
                    if lead.tipo_afiliacion is None:
                        errores.append(
                            ErrorComercial(
                                tipo="cierre_prematuro",
                                descripcion=(
                                    "Intentó cerrar antes de completar "
                                    "la calificación."
                                ),
                                mensaje_cliente=intercambio.mensaje_cliente,
                                respuesta_sofia=intercambio.respuesta_sofia,
                                gravedad="media",
                            )
                        )

        return errores

    @staticmethod
    def _es_pregunta_precio(texto: str) -> bool:
        """Detecta si el mensaje es una pregunta sobre precio."""
        return any(
            p in texto
            for p in [
                "cuánto", "cuanto", "precio", "precios", "costo",
                "costa", "vale", "valor", "pagar", "planes desde",
            ]
        )

    def _generar_recomendaciones(
        self,
        evaluacion: EvaluacionComercial,
        errores: list[ErrorComercial],
    ) -> list[str]:
        """
        Genera recomendaciones basadas en la evaluación y errores.

        Args:
            evaluacion: Evaluación comercial.
            errores: Lista de errores detectados.

        Returns:
            Lista de recomendaciones.
        """
        recomendaciones: list[str] = []

        # Recomendaciones por dimensión
        if evaluacion.descubrimiento < 10:
            recomendaciones.append(
                "Mejorar descubrimiento: preguntar nombre, edad, "
                "localidad y necesidad antes de ofrecer."
            )

        if evaluacion.calificacion < 10:
            recomendaciones.append(
                "Mejorar calificación: obtener tipo de afiliación, "
                "grupo familiar y situación laboral."
            )

        if evaluacion.valor < 10:
            recomendaciones.append(
                "Mejorar presentación de valor: explicar beneficios "
                "personalizados antes de cerrar."
            )

        if evaluacion.objeciones < 10:
            recomendaciones.append(
                "Mejorar manejo de objeciones: validar la preocupación "
                "antes de responder."
            )

        if evaluacion.cierre < 10:
            recomendaciones.append(
                "Mejorar cierre: intentar avanzar cuando el cliente "
                "muestra interés."
            )

        # Recomendaciones por errores
        tipos_errores = {e.tipo for e in errores}

        if "cotizacion_sin_diagnostico" in tipos_errores:
            recomendaciones.append(
                "NUNCA cotizar sin antes diagnosticar necesidades."
            )

        if "falta_avance" in tipos_errores:
            recomendaciones.append(
                "Detectar señales de interés e intentar avanzar "
                "al siguiente paso."
            )

        if "descuento_inmediato" in tipos_errores:
            recomendaciones.append(
                "No ofrecer descuentos sin investigar el valor "
                "percibido por el cliente."
            )

        if "sin_personalizacion" in tipos_errores:
            recomendaciones.append(
                "Personalizar todas las respuestas con los datos "
                "del cliente (nombre, perfil, necesidad)."
            )

        if "cierre_prematuro" in tipos_errores:
            recomendaciones.append(
                "Completar la calificación antes de intentar cerrar."
            )

        return recomendaciones
