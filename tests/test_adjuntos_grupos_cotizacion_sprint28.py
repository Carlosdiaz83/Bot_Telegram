"""
Tests Sprint 28 — Adjuntos en grupos + cotización sin asumir recibo.

Cubre:
    - Los adjuntos (documento/foto) solo se procesan en chats privados
      (en grupos NO deben tratarse como recibo de sueldo).
    - Un adjunto sin tipo de afiliación NO fuerza RELACION_DEPENDENCIA
      (regresión: bloqueaba cotizar monotributo/directo/prepago).
    - Si después el tipo resulta "con recibo", el archivo pendiente se
      aplica como recibo (sin volver a pedirlo).
    - Detección de "directo"/"prepago"/"prepaga" como PARTICULAR en el
      vendedor y en el qualifier de clientes.
"""

from __future__ import annotations

import pytest
from telegram.ext import MessageHandler, filters

from app.services.conversation_manager import ConversationManager
from app.services.lead_qualifier import _detectar_tipo_afiliacion
from app.services.session_manager import EtapaConversacion
from app.models.lead import TipoAfiliacion


@pytest.fixture
def manager():
    """ConversationManager sin DB ni IA."""
    return ConversationManager(ai_service=None, database_url=None)


@pytest.fixture
def pdf_recibo(tmp_path):
    from reportlab.pdfgen import canvas
    ruta = tmp_path / "recibo.pdf"
    c = canvas.Canvas(str(ruta))
    c.drawString(100, 700, "RECIBO DE SUELDO")
    c.drawString(100, 600, "OBRA SOCIAL $15.000")
    c.drawString(100, 580, "SEGURO $8.000")
    c.save()
    return str(ruta)


@pytest.fixture
def jpg_recibo(tmp_path):
    ruta = tmp_path / "foto.jpg"
    ruta.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 128)
    return str(ruta)


# ─────────────────────────────────────────
# Adjuntos en chats de grupo no se procesan
# ─────────────────────────────────────────

class TestAdjuntosSoloPrivado:
    def _update(self, *, document=False, photo=False, chat_type="private"):
        from telegram import Update
        d = {
            "update_id": 1,
            "message": {
                "message_id": 10,
                "date": 1600000000,
                "chat": {"id": 123, "type": chat_type},
                "from": {"id": 5, "first_name": "A", "is_bot": False},
                "text": "hola",
            },
        }
        if document:
            d["message"]["document"] = {
                "file_name": "recibo.pdf", "file_id": "doc1", "file_unique_id": "du1",
            }
        if photo:
            d["message"]["photo"] = [
                {"file_id": "x", "file_unique_id": "ux", "width": 100, "height": 100},
            ]
        return Update.de_json(d, bot=None)

    def test_documento_en_privado_se_procesa(self):
        handler = MessageHandler(
            filters.Document.ALL & ~filters.COMMAND & filters.ChatType.PRIVATE,
            lambda u, c: None,
        )
        assert handler.check_update(self._update(document=True)) is True

    def test_documento_en_grupo_no_se_procesa(self):
        handler = MessageHandler(
            filters.Document.ALL & ~filters.COMMAND & filters.ChatType.PRIVATE,
            lambda u, c: None,
        )
        assert handler.check_update(
            self._update(document=True, chat_type="group")
        ) is False

    def test_foto_en_privado_se_procesa(self):
        handler = MessageHandler(
            filters.PHOTO & filters.ChatType.PRIVATE,
            lambda u, c: None,
        )
        assert handler.check_update(self._update(photo=True)) is True

    def test_foto_en_grupo_no_se_procesa(self):
        handler = MessageHandler(
            filters.PHOTO & filters.ChatType.PRIVATE,
            lambda u, c: None,
        )
        assert handler.check_update(
            self._update(photo=True, chat_type="group")
        ) is False


# ─────────────────────────────────────────
# Adjunto sin tipo no asume relación de dependencia
# ─────────────────────────────────────────

class TestAdjuntoSinTipo:
    def test_vendedor_adjunto_sin_tipo_no_asume_recibo(self, manager, jpg_recibo):
        tid = 7001
        manager.procesar_mensaje(tid, "soy vendedor")
        respuesta = manager.procesar_documento(tid, jpg_recibo)
        session = manager.session_manager.get(tid)

        assert session.lead.tipo_afiliacion is None
        assert session.lead.tiene_recibo_sueldo is not True
        assert session.recibo_ruta == jpg_recibo
        assert session.etapa == EtapaConversacion.VENDEDOR_TIPO
        assert "monotributista" in respuesta

    def test_vendedor_monotributo_con_adjunto_no_marca_recibo(self, manager, jpg_recibo):
        tid = 7002
        manager.procesar_mensaje(tid, "soy vendedor")
        manager.procesar_mensaje(tid, "monotributo")
        manager.procesar_mensaje(tid, "Ana")
        respuesta = manager.procesar_documento(tid, jpg_recibo)
        lead = manager.session_manager.get(tid).lead

        assert lead.tipo_afiliacion == TipoAfiliacion.MONOTRIBUTO
        assert lead.tiene_recibo_sueldo is not True
        assert "recibo de sueldo" not in respuesta.lower()

    def test_vendedor_adjunto_luego_con_recibo_aplica_pendiente(self, manager, jpg_recibo):
        tid = 7003
        manager.procesar_mensaje(tid, "soy vendedor")
        manager.procesar_documento(tid, jpg_recibo)
        respuesta = manager.procesar_mensaje(tid, "con recibo")
        session = manager.session_manager.get(tid)

        assert session.lead.tipo_afiliacion == TipoAfiliacion.RELACION_DEPENDENCIA
        assert session.lead.tiene_recibo_sueldo is True
        assert "cómo se llama" in respuesta
        assert "enviar el recibo" not in respuesta.lower()

    def test_vendedor_adjunto_pdf_luego_recibo_extrae_conceptos(self, manager, pdf_recibo):
        tid = 7004
        manager.procesar_mensaje(tid, "soy vendedor")
        manager.procesar_documento(tid, pdf_recibo, nombre_archivo="recibo.pdf")
        manager.procesar_mensaje(tid, "con recibo")
        lead = manager.session_manager.get(tid).lead

        assert lead.tiene_recibo_sueldo is True
        assert lead.conceptos_obra_social == [15000.0, 8000.0]

    def test_cliente_adjunto_sin_tipo_no_asume_recibo(self, manager, jpg_recibo):
        tid = 7005
        manager.procesar_mensaje(tid, "Hola")
        manager.procesar_mensaje(tid, "Soy Lucía")
        respuesta = manager.procesar_documento(tid, jpg_recibo)
        lead = manager.session_manager.get(tid).lead

        assert lead.tipo_afiliacion is None
        assert lead.tiene_recibo_sueldo is not True
        assert "localidad" in respuesta.lower()

    def test_vendedor_adjunto_luego_monotributo_cotiza(self, manager, jpg_recibo):
        """Flujo completo del caso reportado: adjunto primero, monotributo después."""
        tid = 7006
        manager.procesar_mensaje(tid, "soy vendedor")
        manager.procesar_documento(tid, jpg_recibo)
        manager.procesar_mensaje(tid, "monotributo")
        manager.procesar_mensaje(tid, "Ana")
        manager.procesar_mensaje(tid, "30 años, de Córdoba")
        respuesta = manager.procesar_mensaje(tid, "categoría B")
        session = manager.session_manager.get(tid)
        lead = session.lead

        assert lead.tipo_afiliacion == TipoAfiliacion.MONOTRIBUTO
        assert lead.categoria_monotributo == "B"
        assert lead.tiene_recibo_sueldo is not True
        assert session.etapa == EtapaConversacion.VENDEDOR_COTIZANDO
        assert "otro cliente" in respuesta


# ─────────────────────────────────────────
# Detección de directo / prepago / prepaga
# ─────────────────────────────────────────

class TestDeteccionPrepagoDirecto:
    def test_cotizacion_detecta_directo(self, manager):
        assert (
            manager._detectar_tipo_cotizacion("paga en forma directa")
            == TipoAfiliacion.PARTICULAR
        )

    def test_cotizacion_detecta_prepago(self, manager):
        assert (
            manager._detectar_tipo_cotizacion("prepago")
            == TipoAfiliacion.PARTICULAR
        )

    def test_cotizacion_detecta_prepaga(self, manager):
        assert (
            manager._detectar_tipo_cotizacion("paga una prepaga")
            == TipoAfiliacion.PARTICULAR
        )

    def test_qualifier_detecta_prepaga(self):
        assert _detectar_tipo_afiliacion("pago una prepaga") == TipoAfiliacion.PARTICULAR

    def test_qualifier_detecta_directo(self):
        assert _detectar_tipo_afiliacion("soy directo") == TipoAfiliacion.PARTICULAR

    def test_vendedor_cotiza_directo_con_adjunto(self, manager, jpg_recibo):
        """Adjunto + 'directo' → cotiza como PARTICULAR sin recibo."""
        tid = 7007
        manager.procesar_mensaje(tid, "soy vendedor")
        manager.procesar_documento(tid, jpg_recibo)
        manager.procesar_mensaje(tid, "directo")
        manager.procesar_mensaje(tid, "Ana")
        respuesta = manager.procesar_mensaje(tid, "30 años, de Córdoba")
        session = manager.session_manager.get(tid)

        assert session.lead.tipo_afiliacion == TipoAfiliacion.PARTICULAR
        assert session.lead.tiene_recibo_sueldo is not True
        assert session.etapa == EtapaConversacion.VENDEDOR_COTIZANDO
        assert "otro cliente" in respuesta
