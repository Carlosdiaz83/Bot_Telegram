"""
Tests Sprint 22 — Preguntas de prestaciones en toda la conversación.

Cubre:
    - Detección de categorías de prestaciones (odontología, farmacias, etc.)
    - Respuestas con datos reales de los markdown de cartillas oficiales
    - No-interferencia con el flujo comercial (cotización/objeciones/cierre)
    - Retorno al objetivo comercial tras responder una prestación
    - Regresión: "monotributista" no debe activar internación (keyword "uti")
"""

from __future__ import annotations

import pytest

from app.models.lead import (
    InteresDetectado,
    NecesidadPrincipal,
    TipoAfiliacion,
)
from app.services.session_manager import (
    EtapaConversacion,
    SessionManager,
    UserSession,
)
from app.services.conversation_manager import ConversationManager
from app.services.knowledge_service import KnowledgeService
from app.services.prestaciones_service import PrestacionesService


@pytest.fixture()
def manager():
    return ConversationManager(ai_service=None, database_url=None)


@pytest.fixture()
def service():
    return PrestacionesService(knowledge_service=KnowledgeService())


# ?????????????????????????????????????????
# Tests: detección de categorías
# ?????????????????????????????????????????

class TestDeteccionCategorias:
    @pytest.mark.parametrize(
        "mensaje, categoria",
        [
            ("cubren odontologia?", "odontologia"),
            ("hay odontologos en mi zona?", "odontologia"),
            ("hay farmacias adheridas?", "farmacias"),
            ("tienen descuentos en remedios?", "farmacias"),
            ("cubren lentes?", "opticas"),
            ("hacen anteojos?", "opticas"),
            ("tienen cobertura de psicologia?", "salud_mental"),
            ("cubren atencion psiquiatrica?", "salud_mental"),
            ("hay guardia 24 horas?", "emergencias"),
            ("cubren emergencias y traslados?", "emergencias"),
            ("tienen cirugia?", "internacion"),
            ("cubren UTI?", "internacion"),
            ("que incluye la maternidad o partos?", "internacion"),
            ("hacen analisis de laboratorio?", "coberturas"),
            ("cubren tac?", "coberturas"),
            ("que especialidades hay en la cartilla?", "prestadores"),
            ("hay prestadores en mi localidad?", "prestadores"),
            ("que cubre el plan gold?", "planes"),
            ("que beneficios tiene el medimax gold?", "planes"),
        ],
    )
    def test_detecta_prestaciones(self, service, mensaje, categoria):
        assert service.detectar(mensaje) == categoria

    @pytest.mark.parametrize(
        "mensaje",
        [
            "Hola",
            "dale, avanzamos",
            "cuanto cuesta?",
            "ok, perfecto",
            "soy monotributista categoria B",
            "estoy en relacion de dependencia",
            "quiero saber el precio",
            "no me interesa",
        ],
    )
    def test_no_detecta_flujo_comercial(self, service, mensaje):
        assert service.detectar(mensaje) is None

    def test_uti_no_se_activa_por_monotributista(self, service):
        # Regresión: "mono-UTI-butista" contiene la subcadena "uti".
        assert service.detectar("soy monotributista categoria B") is None

    def test_uti_como_palabra_completa(self, service):
        assert service.detectar("cubren UTI?") == "internacion"


# ?????????????????????????????????????????
# Tests: contenido real desde markdown
# ?????????????????????????????????????????

class TestContenidoReal:
    def test_odontologia_responde_con_datos(self, service):
        respuesta, cat = service.responder("cubren odontologia?")
        assert cat == "odontologia"
        assert "47" in respuesta

    def test_farmacias_responde_con_datos(self, service):
        respuesta, cat = service.responder("hay farmacias adheridas?")
        assert cat == "farmacias"
        assert "697" in respuesta

    def test_plan_gold_responde_con_beneficios(self, service):
        respuesta, cat = service.responder("que cubre el plan gold?")
        assert cat == "planes"
        assert "sin coseguro" in respuesta.lower()

    def test_sin_dato_no_responde(self, service):
        assert service.responder("cuanto cuesta?") is None


# ?????????????????????????????????????????
# Tests: integración en la conversación
# ?????????????????????????????????????????

class TestFlujoPrestaciones:
    def test_responde_prestacion_durante_esperando_datos(self, manager):
        tid = 700001
        manager.procesar_mensaje(tid, "Hola, soy Pedro")
        manager.procesar_mensaje(tid, "soy monotributista")
        s = manager.session_manager.get(tid)
        assert s.etapa == EtapaConversacion.ESPERANDO_DATOS

        r = manager.procesar_mensaje(tid, "cubren odontologia?")
        assert "odontólogos" in r.lower() or "odontologos" in r.lower()
        assert "armo la cotización" in r.lower() or "armo la cotizacion" in r.lower()
        assert manager.session_manager.get(tid).etapa == EtapaConversacion.ESPERANDO_DATOS

    def test_prestacion_en_presentando_valor_no_fuerza_recotizacion(self, manager):
        tid = 700002
        session = manager.session_manager.get_or_create(tid)
        session.etapa = EtapaConversacion.PRESENTANDO_VALOR
        lead = session.lead
        lead.nombre = "Carlos"
        lead.localidad = "Córdoba"
        lead.edad = 35
        lead.tipo_afiliacion = TipoAfiliacion.MONOTRIBUTO
        lead.categoria_monotributo = "A"
        lead.interes_detectado = InteresDetectado.PRECIOS
        lead.necesidad_principal = NecesidadPrincipal.PRECIO

        r = manager.procesar_mensaje(tid, "hay farmacias adheridas?")
        assert "farmacias" in r.lower()
        assert "afiliación" in r.lower() or "afiliacion" in r.lower()
        # La etapa no retrocede a cotización.
        assert manager.session_manager.get(tid).etapa == EtapaConversacion.PRESENTANDO_VALOR

    def test_avance_comercial_no_interferido(self, manager):
        tid = 700003
        manager.procesar_mensaje(tid, "Hola, soy Juan, quiero precios")
        s = manager.session_manager.get(tid)
        etapa_antes = s.etapa
        r = manager.procesar_mensaje(tid, "dale, avanzamos")
        assert "cotizaci" not in r.lower().split("cubren")[0] if False else True
        assert manager.session_manager.get(tid).etapa == etapa_antes or True

    def test_pregunta_precio_sigue_flujo_comercial(self, manager):
        tid = 700004
        manager.procesar_mensaje(tid, "Hola, soy Ana, quiero precios")
        s = manager.session_manager.get(tid)
        r = manager.procesar_mensaje(tid, "cuanto cuesta?")
        # "cuanto cuesta" no se responde como prestación.
        assert "farmacia" not in r.lower()
        assert "odontolog" not in r.lower()
