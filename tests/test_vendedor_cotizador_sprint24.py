"""
Tests Sprint 24 — Modo vendedor (cotizador para vendedores).

Cubre:
    - Detección de "soy vendedor" → activa modo vendedor
    - Flujo completo de cotización de un cliente (monotributo y recibo)
    - Pregunta de tipo: recibo de sueldo / monotributo / directo, o consulta
    - Consultas de prestaciones en modo vendedor (con PDF de respaldo)
    - Loop de "cotizar otro cliente" y salida del modo vendedor
    - Salir a mitad de flujo con "no soy vendedor"
    - El flujo normal de cliente no se ve afectado
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.respuesta_bot import RespuestaBot
from app.services.session_manager import EtapaConversacion
from app.services.conversation_manager import ConversationManager
from app.models.lead import TipoAfiliacion


# ─────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────

@pytest.fixture
def manager():
    """ConversationManager sin DB ni IA."""
    return ConversationManager(ai_service=None, database_url=None)


def _flujo_completo_monotributo(manager, tid):
    """Recorre el flujo vendedor completo con un cliente monotributo."""
    manager.procesar_mensaje(tid, "soy vendedor")
    manager.procesar_mensaje(tid, "monotributo")
    manager.procesar_mensaje(tid, "Juan")
    manager.procesar_mensaje(tid, "45 años, de Córdoba")
    return manager.procesar_mensaje(tid, "categoría B")


# ─────────────────────────────────────────
# Detección y activación del modo vendedor
# ─────────────────────────────────────────

class TestDeteccionVendedor:
    def test_soy_vendedor_activa_modo(self, manager):
        tid = 5001
        respuesta = manager.procesar_mensaje(tid, "soy vendedor")
        session = manager.session_manager.get(tid)

        assert session.es_vendedor is True
        assert session.etapa == EtapaConversacion.VENDEDOR_TIPO
        assert "recibo de sueldo" in respuesta
        assert "monotributo" in respuesta
        assert "directo" in respuesta

    def test_soy_vendedor_no_pide_nombre_del_vendedor(self, manager):
        tid = 5002
        respuesta = manager.procesar_mensaje(tid, "soy vendedor")
        session = manager.session_manager.get(tid)
        assert session.lead.nombre is None
        assert "¿Cómo te llamás?" not in respuesta

    def test_variantes_detectadas(self, manager):
        for msg in ["soy vendedor", "soy vendedora", "vendo planes"]:
            tid = 6000 + hash(msg) % 1000
            manager.procesar_mensaje(tid, msg)
            assert manager.session_manager.get(tid).es_vendedor is True

    def test_cliente_normal_no_entra_a_vendedor(self, manager):
        tid = 5003
        respuesta = manager.procesar_mensaje(tid, "Hola, quiero información")
        session = manager.session_manager.get(tid)
        assert session.es_vendedor is False
        assert "recibo de sueldo, monotributo o directo" not in respuesta


# ─────────────────────────────────────────
# Flujo completo de cotización de un cliente
# ─────────────────────────────────────────

class TestFlujoCotizacionVendedor:
    def test_monotributo_completo(self, manager):
        tid = 5011
        respuesta = _flujo_completo_monotributo(manager, tid)
        session = manager.session_manager.get(tid)

        assert session.etapa == EtapaConversacion.VENDEDOR_COTIZANDO
        assert session.es_vendedor is True
        assert "Juan" in respuesta
        assert "otro cliente" in respuesta
        assert isinstance(respuesta, RespuestaBot)
        nombres = [Path(p).name for p in respuesta.archivos_adjuntos]
        assert any("MEDIMAX" in n for n in nombres)

    def test_lead_guarda_datos_del_cliente(self, manager):
        tid = 5012
        _flujo_completo_monotributo(manager, tid)
        lead = manager.session_manager.get(tid).lead

        assert lead.nombre == "Juan"
        assert lead.edad == 45
        assert lead.localidad == "Córdoba"
        assert lead.tipo_afiliacion == TipoAfiliacion.MONOTRIBUTO
        assert lead.categoria_monotributo == "B"

    def test_recibo_de_sueldo_con_conceptos(self, manager):
        tid = 5013
        manager.procesar_mensaje(tid, "soy vendedor")
        manager.procesar_mensaje(tid, "con recibo")
        manager.procesar_mensaje(tid, "María")
        manager.procesar_mensaje(tid, "38 años, de Villa María")
        respuesta = manager.procesar_mensaje(
            tid, "sí, tengo el recibo, los conceptos son $15.000 y $8.000"
        )
        lead = manager.session_manager.get(tid).lead

        assert lead.tipo_afiliacion == TipoAfiliacion.RELACION_DEPENDENCIA
        assert lead.conceptos_obra_social == [15000.0, 8000.0]
        assert "María" in respuesta

    def test_directo_particular(self, manager):
        tid = 5014
        manager.procesar_mensaje(tid, "soy vendedor")
        manager.procesar_mensaje(tid, "directo")
        respuesta = manager.procesar_mensaje(tid, "Pedro, 30 años, Córdoba")
        lead = manager.session_manager.get(tid).lead

        assert lead.tipo_afiliacion == TipoAfiliacion.PARTICULAR
        assert "Pedro" in respuesta
        assert "otro cliente" in respuesta

    def test_una_pregunta_por_mensaje(self, manager):
        tid = 5015
        manager.procesar_mensaje(tid, "soy vendedor")
        manager.procesar_mensaje(tid, "monotributo")
        respuesta = manager.procesar_mensaje(tid, "Juan")
        assert "localidad" in respuesta
        # Pregunta puntual, no enumera varios faltantes
        assert "edad" not in respuesta or respuesta.count("¿") == 1


# ─────────────────────────────────────────
# Consulta en modo vendedor
# ─────────────────────────────────────────

class TestConsultaVendedor:
    def test_consulta_deriva_a_pregunta(self, manager):
        tid = 5021
        manager.procesar_mensaje(tid, "soy vendedor")
        respuesta = manager.procesar_mensaje(tid, "es una consulta")
        assert "Decime tu consulta" in respuesta

    def test_prestacion_en_modo_vendedor(self, manager):
        tid = 5022
        manager.procesar_mensaje(tid, "soy vendedor")
        manager.procesar_mensaje(tid, "monotributo")
        respuesta = manager.procesar_mensaje(tid, "¿cubren odontología?")
        session = manager.session_manager.get(tid)

        assert "odontólogos" in respuesta
        assert "otro cliente" in respuesta
        assert session.etapa == EtapaConversacion.VENDEDOR_DATOS
        assert any(
            "ODONTO" in Path(p).name for p in respuesta.archivos_adjuntos
        )

    def test_tengo_una_consulta_avanza_a_etapa_consulta(self, manager):
        tid = 5023
        manager.procesar_mensaje(tid, "soy vendedor")
        respuesta = manager.procesar_mensaje(tid, "tengo una consulta")
        session = manager.session_manager.get(tid)

        assert "Decime tu consulta" in respuesta
        assert session.etapa == EtapaConversacion.VENDEDOR_CONSULTA

    def test_consulta_coseguro_responde_con_dato_real(self, manager):
        """Regresión: 'el plan medimax tiene coseguro?' ya no entra en bucle
        pidiendo el tipo de afiliación, sino que responde el dato real y
        retoma el loop de cotización."""
        tid = 5024
        manager.procesar_mensaje(tid, "soy vendedor")
        manager.procesar_mensaje(tid, "tengo una consulta")
        respuesta = manager.procesar_mensaje(tid, "el plan medimax tiene coseguro?")
        session = manager.session_manager.get(tid)

        assert "coseguro" in respuesta.lower()
        assert "Sin coseguros en prestadores de cartilla" in respuesta
        assert "otro cliente" in respuesta
        assert session.etapa == EtapaConversacion.VENDEDOR_COTIZANDO

    def test_consulta_tras_cotizacion_no_se_pierde(self, manager):
        """Regresión: tras cotizar un cliente, una consulta libre se atiende
        en lugar de repetir '¿Querés que cotice otro cliente...?'."""
        tid = 5025
        _flujo_completo_monotributo(manager, tid)
        respuesta = manager.procesar_mensaje(tid, "tengo una consulta")
        session = manager.session_manager.get(tid)

        assert "Decime tu consulta" in respuesta
        assert session.etapa == EtapaConversacion.VENDEDOR_CONSULTA

        respuesta = manager.procesar_mensaje(tid, "¿el plan medimax gold tiene copagos?")
        assert "coseguro" in respuesta.lower()
        session = manager.session_manager.get(tid)
        assert session.etapa == EtapaConversacion.VENDEDOR_COTIZANDO

    def test_consulta_general_sin_dato_vuelve_al_loop(self, manager):
        tid = 5026
        manager.procesar_mensaje(tid, "soy vendedor")
        manager.procesar_mensaje(tid, "tengo una consulta")
        respuesta = manager.procesar_mensaje(tid, "¿cómo facturan a las empresas?")
        session = manager.session_manager.get(tid)

        assert "otro cliente" in respuesta
        assert session.etapa == EtapaConversacion.VENDEDOR_COTIZANDO

    def test_consulta_luego_cotizar_otro_cliente(self, manager):
        tid = 5027
        manager.procesar_mensaje(tid, "soy vendedor")
        manager.procesar_mensaje(tid, "tengo una consulta")
        manager.procesar_mensaje(tid, "el plan medimax tiene coseguro?")
        respuesta = manager.procesar_mensaje(tid, "sí, otro cliente")
        session = manager.session_manager.get(tid)

        assert session.etapa == EtapaConversacion.VENDEDOR_TIPO
        assert session.es_vendedor is True
        assert "recibo de sueldo" in respuesta


# ─────────────────────────────────────────
# Loop de otro cliente y salida
# ─────────────────────────────────────────

class TestLoopYSalida:
    def test_otro_cliente_reinicia_datos(self, manager):
        tid = 5031
        _flujo_completo_monotributo(manager, tid)
        respuesta = manager.procesar_mensaje(tid, "sí, otro cliente")
        session = manager.session_manager.get(tid)

        assert session.etapa == EtapaConversacion.VENDEDOR_TIPO
        assert session.es_vendedor is True
        assert session.lead.nombre is None
        assert "recibo de sueldo" in respuesta

    def test_no_cierra_modo(self, manager):
        tid = 5032
        _flujo_completo_monotributo(manager, tid)
        respuesta = manager.procesar_mensaje(tid, "no, gracias")
        session = manager.session_manager.get(tid)

        assert session.es_vendedor is False
        assert session.etapa == EtapaConversacion.NUEVO
        assert "Salí del modo vendedor" in respuesta

    def test_salir_a_mitad_de_flujo(self, manager):
        tid = 5033
        manager.procesar_mensaje(tid, "soy vendedor")
        manager.procesar_mensaje(tid, "monotributo")
        respuesta = manager.procesar_mensaje(tid, "no soy vendedor")
        session = manager.session_manager.get(tid)

        assert session.es_vendedor is False
        assert session.etapa == EtapaConversacion.NUEVO
        assert "Salí del modo vendedor" in respuesta

    def test_reactivar_modo_despues_de_salir(self, manager):
        tid = 5034
        manager.procesar_mensaje(tid, "soy vendedor")
        manager.procesar_mensaje(tid, "monotributo")
        manager.procesar_mensaje(tid, "no soy vendedor")
        respuesta = manager.procesar_mensaje(tid, "soy vendedor")
        session = manager.session_manager.get(tid)

        assert session.es_vendedor is True
        assert session.etapa == EtapaConversacion.VENDEDOR_TIPO
        assert "recibo de sueldo" in respuesta


# ─────────────────────────────────────────
# No interfiere con el flujo normal de cliente
# ─────────────────────────────────────────

class TestNoInterfiere:
    def test_flujo_cliente_normal(self, manager):
        tid = 5041
        manager.procesar_mensaje(tid, "Hola")
        manager.procesar_mensaje(tid, "Soy Ana")
        manager.procesar_mensaje(tid, "Quiero info")
        manager.procesar_mensaje(tid, "Particular, solo para mí")
        respuesta = manager.procesar_mensaje(tid, "Córdoba, 30 años")
        session = manager.session_manager.get(tid)

        assert session.es_vendedor is False
        assert session.etapa == EtapaConversacion.PRESENTANDO_VALOR
        assert "otro cliente" not in respuesta
