"""
Tests Sprint 18F — Optimización estrategia comercial.

Cubre:
    - Detección de intención comercial en primer mensaje (salta recolección)
    - Lenguaje activo en argumentos comerciales (sin "¿Querés que te cuente?")
    - Lenguaje asertivo en cierres (sin "¿Qué preferís?" / "¿Te parece?")
    - Recolección agresiva de datos (2-3 preguntas en un solo mensaje)
    - Flujo completo: intención → recolección → valor → cierre
"""

from __future__ import annotations

import pytest

from app.models.lead import (
    EstadoComercial,
    GrupoFamiliar,
    InteresDetectado,
    Lead,
    NecesidadPrincipal,
    PrioridadCliente,
    TipoAfiliacion,
)
from app.services.session_manager import (
    EtapaConversacion,
    SessionManager,
    UserSession,
)
from app.services.conversation_manager import ConversationManager
from app.services.sales_strategy import (
    _argumento_empresa,
    _argumento_familiar,
    _argumento_generico,
    _argumento_monotributista,
    _argumento_prestadores,
    _argumento_precio,
    _argumento_calidad,
    _argumento_beneficios,
)
from app.services.closing_strategy import (
    _cierre_alternativo,
    _cierre_beneficio,
    _cierre_directo,
    recuperar_indeciso,
)


# ─────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────

@pytest.fixture()
def manager():
    return ConversationManager(ai_service=None, database_url=None)


def _lead_base(**kwargs) -> Lead:
    lead = Lead(lead_id="test_18f")
    for k, v in kwargs.items():
        setattr(lead, k, v)
    return lead


# ─────────────────────────────────────────
# Tests: Lenguaje activo en argumentos
# ─────────────────────────────────────────

class TestLenguajeActivoArgumentos:
    """Verifica que los argumentos NO contengan lenguaje pasivo."""

    PASSIVE_PATTERNS = [
        "¿Querés que te cuente",
        "¿Te gustaría que te cuente",
        "¿Querés que veamos",
        "¿Hay algún prestador",
    ]

    def _assert_no_passive(self, texto: str) -> None:
        for patron in self.PASSIVE_PATTERNS:
            assert patron not in texto, (
                f"Lenguaje pasivo encontrado: '{patron}' en: {texto}"
            )

    def test_precio_sin_pasivo(self):
        lead = _lead_base(
            nombre="Carlos",
            prioridad_cliente=PrioridadCliente.ECONOMICO,
        )
        texto = _argumento_precio(lead)
        self._assert_no_passive(texto)
        assert "presupuesto" in texto.lower()

    def test_familiar_sin_pasivo(self):
        lead = _lead_base(
            nombre="María",
            prioridad_cliente=PrioridadCliente.FAMILIAR,
        )
        texto = _argumento_familiar(lead)
        self._assert_no_passive(texto)
        assert "familia" in texto.lower()

    def test_calidad_sin_pasivo(self):
        lead = _lead_base(
            nombre="Pedro",
            prioridad_cliente=PrioridadCliente.COMPLETO,
        )
        texto = _argumento_calidad(lead)
        self._assert_no_passive(texto)
        assert "cobertura" in texto.lower()

    def test_beneficios_sin_pasivo(self):
        lead = _lead_base(
            nombre="Ana",
            necesidad_principal=NecesidadPrincipal.BENEFICIOS,
        )
        texto = _argumento_beneficios(lead)
        self._assert_no_passive(texto)
        assert "beneficios" in texto.lower()

    def test_prestadores_sin_pasivo(self):
        lead = _lead_base(
            nombre="Luis",
            necesidad_principal=NecesidadPrincipal.ACCESO_PRESTADORES,
        )
        texto = _argumento_prestadores(lead)
        self._assert_no_passive(texto)
        assert "prestadores" in texto.lower()

    def test_monotributista_sin_pasivo(self):
        lead = _lead_base(
            nombre="Jorge",
            tipo_afiliacion=TipoAfiliacion.MONOTRIBUTO,
        )
        texto = _argumento_monotributista(lead)
        self._assert_no_passive(texto)
        assert "monotributo" in texto.lower() or "monotributista" in texto.lower()

    def test_empresa_sin_pasivo(self):
        lead = _lead_base(
            nombre="Sandra",
            tipo_afiliacion=TipoAfiliacion.EMPRESA,
        )
        texto = _argumento_empresa(lead)
        self._assert_no_passive(texto)
        assert "empresa" in texto.lower()

    def test_generico_sin_pasivo(self):
        lead = _lead_base(nombre="Roberto")
        texto = _argumento_generico(lead)
        self._assert_no_passive(texto)


# ─────────────────────────────────────────
# Tests: Lenguaje asertivo en cierres
# ─────────────────────────────────────────

class TestLenguajeAsertivoCierres:
    """Verifica que los cierres NO contengan lenguaje pasivo."""

    PASSIVE_PATTERNS = [
        "¿Querés que avancemos",
        "¿Querés que iniciemos",
        "¿Qué preferís?",
        "¿Te parece?",
    ]

    def _assert_no_passive(self, texto: str) -> None:
        for patron in self.PASSIVE_PATTERNS:
            assert patron not in texto, (
                f"Lenguaje pasivo encontrado: '{patron}' en: {texto}"
            )

    def test_cierre_directo_sin_pasivo(self):
        lead = _lead_base(nombre="Carlos")
        texto = _cierre_directo(lead)
        self._assert_no_passive(texto)
        assert "avanzo" in texto.lower() or "afiliación" in texto.lower()

    def test_cierre_beneficio_sin_pasivo(self):
        lead = _lead_base(nombre="María")
        texto = _cierre_beneficio(lead)
        self._assert_no_passive(texto)
        assert "iniciamos" in texto.lower() or "familia" in texto.lower()

    def test_cierre_alternativo_sin_pasivo(self):
        lead = _lead_base(nombre="Pedro")
        texto = _cierre_alternativo(lead)
        self._assert_no_passive(texto)
        assert "avanzo" in texto.lower() or "coordinamos" in texto.lower()

    def test_recuperar_indeciso_familia_sin_pasivo(self):
        lead = _lead_base(nombre="Ana")
        lead.actualizar_grupo_familiar(conyuge=True)
        texto = recuperar_indeciso(lead)
        self._assert_no_passive(texto)
        assert "familia" in texto.lower()

    def test_recuperar_indeciso_precio_sin_pasivo(self):
        lead = _lead_base(
            nombre="Luis",
            prioridad_cliente=PrioridadCliente.ECONOMICO,
        )
        texto = recuperar_indeciso(lead)
        self._assert_no_passive(texto)
        assert "presupuesto" in texto.lower()

    def test_recuperar_indeciso_default_sin_pasivo(self):
        lead = _lead_base(nombre="Roberto")
        texto = recuperar_indeciso(lead)
        self._assert_no_passive(texto)
        assert "datos" in texto.lower() or "asesor" in texto.lower()


# ─────────────────────────────────────────
# Tests: Detección de intención en NUEVO
# ─────────────────────────────────────────

class TestIntencionEnNuevo:
    """Verifica que la intención comercial detectada en el primer mensaje
    active la recolección agresiva de datos."""

    def test_precio_detectado_salta_a_calificacion(self, manager):
        session = manager.session_manager.get_or_create(9001)
        respuesta = manager._handle_nuevo(session, "Quiero precios")

        assert session.etapa == EtapaConversacion.CALIFICANDO
        assert "familia" in respuesta.lower() or "situación laboral" in respuesta.lower()

    def test_afiliacion_detectado_salta_a_calificacion(self, manager):
        session = manager.session_manager.get_or_create(9002)
        respuesta = manager._handle_nuevo(session, "Me quiero afiliar")

        assert session.etapa == EtapaConversacion.CALIFICANDO
        assert "familia" in respuesta.lower() or "situación laboral" in respuesta.lower()

    def test_cambio_detectado_salta_a_calificacion(self, manager):
        session = manager.session_manager.get_or_create(9003)
        respuesta = manager._handle_nuevo(session, "Quiero cambiar de obra social")

        assert session.etapa == EtapaConversacion.CALIFICANDO
        assert "familia" in respuesta.lower() or "situación laboral" in respuesta.lower()

    def test_sin_intencion_se_queda_en_nuevo(self, manager):
        session = manager.session_manager.get_or_create(9004)
        manager._handle_nuevo(session, "Hola")

        assert session.etapa == EtapaConversacion.NUEVO

    def test_intencion_con_nombre_pide_datos_completos(self, manager):
        session = manager.session_manager.get_or_create(9005)
        respuesta = manager._handle_nuevo(session, "Soy Carlos, quiero precios")

        assert session.lead.nombre == "Carlos"
        assert session.lead.interes_detectado == InteresDetectado.PRECIOS
        assert session.etapa == EtapaConversacion.CALIFICANDO

    def test_intencion_sin_nombre_pide_nombre_y_datos(self, manager):
        session = manager.session_manager.get_or_create(9006)
        respuesta = manager._handle_nuevo(session, "quiero afiliarme")

        assert session.lead.interes_detectado == InteresDetectado.AFILIACION
        assert "llamás" in respuesta.lower() or "nombre" in respuesta.lower()
        assert "familia" in respuesta.lower() or "situación laboral" in respuesta.lower()


# ─────────────────────────────────────────
# Tests: Recolectar datos en NUEVO con intención
# ─────────────────────────────────────────

class TestRecoleccionAgresiva:
    """Verifica que con intención comercial, se recolecten datos de forma agresiva."""

    def test_pregunta_combinada_familia_y_situacion(self, manager):
        session = manager.session_manager.get_or_create(9010)
        session.lead.interes_detectado = InteresDetectado.PRECIOS
        respuesta = manager._generar_siguiente_pregunta(
            session.lead, "tipo_afiliacion"
        )

        assert "situación laboral" in respuesta.lower() or "familia" in respuesta.lower()

    def test_con_intencion_combina_preguntas(self, manager):
        session = manager.session_manager.get_or_create(9011)
        session.lead.interes_detectado = InteresDetectado.AFILIACION
        session.lead.tipo_afiliacion = None
        respuesta = manager._generar_siguiente_pregunta(
            session.lead, "grupo_familiar"
        )

        assert "y" in respuesta.lower() or "," in respuesta


# ─────────────────────────────────────────
# Tests: Flujo completo intención → cierre
# ─────────────────────────────────────────

class TestFlujoCompletoIntencion:
    """Verifica el flujo completo desde detección de intención hasta cierre."""

    def test_flujo_precios_nombre_familia_tipo(self, manager):
        # Primer mensaje: nombre + intención
        r1 = manager.procesar_mensaje(9020, "Soy Carlos, quiero precios")
        assert "familia" in r1.lower() or "situación laboral" in r1.lower()

        # Segundo mensaje: familia + tipo afiliación
        r2 = manager.procesar_mensaje(9020, "Somos 3, monotributo")
        session = manager.session_manager.get_or_create(9020)
        assert session.lead.tipo_afiliacion == TipoAfiliacion.MONOTRIBUTO

    def test_flujo_afiliacion_sin_nombre(self, manager):
        # Primer mensaje: solo intención
        r1 = manager.procesar_mensaje(9021, "Quiero afiliarme")
        assert "llamás" in r1.lower() or "nombre" in r1.lower()

        # Segundo mensaje: nombre + familia + tipo
        r2 = manager.procesar_mensaje(9021, "Soy Pedro, somos 2, relación de dependencia")
        session = manager.session_manager.get_or_create(9021)
        assert session.lead.nombre == "Pedro"
        assert session.lead.tipo_afiliacion == TipoAfiliacion.RELACION_DEPENDENCIA

    def test_retorno_manera_activa(self, manager):
        session = manager.session_manager.get_or_create(9022)
        session.lead.nombre = "Ana"
        session.etapa = EtapaConversacion.PRESENTANDO_VALOR
        session.lead.interes_detectado = InteresDetectado.PRECIOS

        respuesta = manager._handle_valor(session, "ok")
        session2 = manager.session_manager.get_or_create(9022)
        assert session2.etapa == EtapaConversacion.INTENTANDO_CIERRE

    def test_cierre_no_es_pasivo(self, manager):
        session = manager.session_manager.get_or_create(9023)
        session.lead.nombre = "Luis"
        session.lead.estado_comercial = EstadoComercial.INTENTANDO_CIERRE
        session.etapa = EtapaConversacion.INTENTANDO_CIERRE

        respuesta = manager._handle_cierre(session, "dale")
        assert "excelente" in respuesta.lower() or "bienvenido" in respuesta.lower()
        PASSIVE = ["¿Querés", "¿Te gustaría", "¿Qué preferís", "¿Te parece"]
        for p in PASSIVE:
            assert p not in respuesta, f"Lenguaje pasivo en cierre: {p}"


# ─────────────────────────────────────────
# Tests: Valor sin preguntas pasivas
# ─────────────────────────────────────────

class TestValorSinPasivo:
    """Verifica que _handle_valor no genera preguntas pasivas."""

    def test_valor_sin_beneficios_avanza_a_cierre(self, manager):
        session = manager.session_manager.get_or_create(9030)
        session.lead.nombre = "Test"
        session.lead.interes_detectado = InteresDetectado.PRECIOS
        session.etapa = EtapaConversacion.PRESENTANDO_VALOR

        respuesta = manager._handle_valor(session, "bien")
        assert "avanzamos" in respuesta.lower() or "afiliación" in respuesta.lower()

    def test_valor_fuerza_cierre_despues_de_3_mensajes(self, manager):
        session = manager.session_manager.get_or_create(9031)
        session.lead.nombre = "Test"
        session.lead.interes_detectado = InteresDetectado.PRECIOS
        session.etapa = EtapaConversacion.PRESENTANDO_VALOR
        session.mensajes_en_etapa = 3

        respuesta = manager._handle_valor(session, "genial")
        assert session.etapa == EtapaConversacion.INTENTANDO_CIERRE
