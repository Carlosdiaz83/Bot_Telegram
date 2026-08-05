"""
Tests Sprint 27 — Recibo de sueldo en foto o PDF.

Cubre:
    - Typo "con reecibo de sueldo" detecta RELACION_DEPENDENCIA
      (regresión: antes no se detectaba y el bot se quedaba sin respuesta)
    - El bot acepta un documento (PDF) como recibo de sueldo
    - El bot acepta una foto (jpg) como recibo de sueldo
    - Extracción de conceptos de obra social desde el texto del PDF
    - Confirmación simple del recibo ("sí lo tengo")
    - Flujo vendedor completo con recibo adjunto → cotización
    - Flujo cliente completo con recibo adjunto → cotización
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.conversation_manager import ConversationManager
from app.services.respuesta_bot import RespuestaBot
from app.services.session_manager import EtapaConversacion
from app.models.lead import TipoAfiliacion


# ─────────────────────────────────────────
# Fixtures y helpers
# ─────────────────────────────────────────

@pytest.fixture
def manager():
    """ConversationManager sin DB ni IA."""
    return ConversationManager(ai_service=None, database_url=None)


@pytest.fixture
def pdf_recibo(tmp_path):
    """Genera un PDF real de recibo de sueldo con conceptos de obra social."""
    from reportlab.pdfgen import canvas
    ruta = tmp_path / "recibo.pdf"
    c = canvas.Canvas(str(ruta))
    c.drawString(100, 700, "RECIBO DE SUELDO")
    c.drawString(100, 680, "Empresa ACME SRL")
    c.drawString(100, 620, "Conceptos de obra social:")
    c.drawString(100, 600, "OBRA SOCIAL $15.000")
    c.drawString(100, 580, "SEGURO $8.000")
    c.save()
    return str(ruta)


@pytest.fixture
def pdf_sin_texto(tmp_path):
    """Genera un PDF de imagen (sin texto extraíble)."""
    from reportlab.pdfgen import canvas
    ruta = tmp_path / "recibo_imagen.pdf"
    c = canvas.Canvas(str(ruta))
    c.rect(50, 500, 500, 200)
    c.save()
    return str(ruta)


@pytest.fixture
def jpg_recibo(tmp_path):
    """Genera una imagen jpg cualquiera (foto del recibo)."""
    ruta = tmp_path / "foto_recibo.jpg"
    ruta.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 256)
    return str(ruta)


# ─────────────────────────────────────────
# Regresión: typo "reecibo"
# ─────────────────────────────────────────

class TestTypoRecibo:
    def test_typo_reecibo_detecta_recibo(self, manager):
        """Regresión del bug reportado: 'con reecibo de sueldo' no se detectaba."""
        tid = 6001
        manager.procesar_mensaje(tid, "soy vendedor")
        respuesta = manager.procesar_mensaje(tid, "con reecibo de sueldo")
        session = manager.session_manager.get(tid)

        assert session.lead.tipo_afiliacion == TipoAfiliacion.RELACION_DEPENDENCIA
        assert session.etapa == EtapaConversacion.VENDEDOR_DATOS
        assert "cómo se llama" in respuesta

    def test_typo_reecibo_flujo_completo(self, manager):
        """El typo no bloquea llegar a la cotización."""
        tid = 6002
        manager.procesar_mensaje(tid, "soy vendedor")
        manager.procesar_mensaje(tid, "con reecibo")
        manager.procesar_mensaje(tid, "Ana")
        respuesta = manager.procesar_mensaje(tid, "30 años, de Córdoba")
        lead = manager.session_manager.get(tid).lead

        assert lead.tipo_afiliacion == TipoAfiliacion.RELACION_DEPENDENCIA
        # El flujo primero pide el recibo antes de cotizar.
        assert "recibo" in respuesta.lower()

    def test_typo_monotributista_afin(self, manager):
        """'reecibo' no confunde con monotributo ni directo."""
        tid = 6003
        manager.procesar_mensaje(tid, "soy vendedor")
        manager.procesar_mensaje(tid, "con reecibo de sueldo")
        lead = manager.session_manager.get(tid).lead
        assert lead.tipo_afiliacion == TipoAfiliacion.RELACION_DEPENDENCIA


# ─────────────────────────────────────────
# Aceptación de documento PDF
# ─────────────────────────────────────────

class TestDocumentoPDF:
    def test_pdf_se_procesa_como_recibo(self, manager, pdf_recibo):
        tid = 6011
        manager.procesar_mensaje(tid, "soy vendedor")
        manager.procesar_mensaje(tid, "con recibo")
        manager.procesar_mensaje(tid, "María")

        respuesta = manager.procesar_documento(
            tid, pdf_recibo, nombre_archivo="recibo.pdf"
        )
        session = manager.session_manager.get(tid)
        lead = session.lead

        assert lead.tiene_recibo_sueldo is True
        assert session.recibo_ruta == pdf_recibo
        assert "recib" in respuesta.lower()
        assert isinstance(respuesta, str)

    def test_pdf_extrae_conceptos_de_obra_social(self, manager, pdf_recibo):
        tid = 6012
        manager.procesar_mensaje(tid, "soy vendedor")
        manager.procesar_mensaje(tid, "con recibo")
        manager.procesar_mensaje(tid, "María")
        manager.procesar_documento(tid, pdf_recibo, nombre_archivo="recibo.pdf")

        lead = manager.session_manager.get(tid).lead
        assert lead.conceptos_obra_social == [15000.0, 8000.0]

    def test_pdf_sin_texto_no_rompe(self, manager, pdf_sin_texto):
        tid = 6013
        manager.procesar_mensaje(tid, "soy vendedor")
        manager.procesar_mensaje(tid, "con recibo")
        manager.procesar_mensaje(tid, "María")
        respuesta = manager.procesar_documento(
            tid, pdf_sin_texto, nombre_archivo="recibo_imagen.pdf"
        )

        lead = manager.session_manager.get(tid).lead
        assert lead.tiene_recibo_sueldo is True
        assert lead.conceptos_obra_social == []
        assert "recib" in respuesta.lower()

    def test_flujo_vendedor_completo_con_pdf(self, manager, pdf_recibo):
        tid = 6014
        manager.procesar_mensaje(tid, "soy vendedor")
        manager.procesar_mensaje(tid, "con recibo")
        manager.procesar_mensaje(tid, "María")
        manager.procesar_documento(tid, pdf_recibo, nombre_archivo="recibo.pdf")
        manager.procesar_mensaje(tid, "Villa María")
        respuesta = manager.procesar_mensaje(tid, "38 años")
        session = manager.session_manager.get(tid)
        lead = session.lead

        assert lead.tipo_afiliacion == TipoAfiliacion.RELACION_DEPENDENCIA
        assert lead.conceptos_obra_social == [15000.0, 8000.0]
        assert session.etapa == EtapaConversacion.VENDEDOR_COTIZANDO
        assert "otro cliente" in respuesta


# ─────────────────────────────────────────
# Aceptación de foto
# ─────────────────────────────────────────

class TestFoto:
    def test_foto_se_procesa_como_recibo(self, manager, jpg_recibo):
        tid = 6021
        manager.procesar_mensaje(tid, "soy vendedor")
        manager.procesar_mensaje(tid, "con recibo")
        manager.procesar_mensaje(tid, "Pedro")

        respuesta = manager.procesar_documento(tid, jpg_recibo)
        session = manager.session_manager.get(tid)

        assert session.lead.tiene_recibo_sueldo is True
        assert session.recibo_ruta == jpg_recibo
        assert "recib" in respuesta.lower()


# ─────────────────────────────────────────
# Confirmación simple del recibo
# ─────────────────────────────────────────

class TestConfirmacionRecibo:
    def test_si_lo_tengo_confirma_recibo(self, manager):
        tid = 6031
        manager.procesar_mensaje(tid, "soy vendedor")
        manager.procesar_mensaje(tid, "con recibo")
        manager.procesar_mensaje(tid, "Ana")
        respuesta = manager.procesar_mensaje(tid, "sí lo tengo")
        lead = manager.session_manager.get(tid).lead

        assert lead.tiene_recibo_sueldo is True
        # Sigue pidiendo conceptos, no vuelve a pedir el archivo del recibo.
        assert "me podés enviar el recibo" not in respuesta.lower()

    def test_ok_confirma_recibo(self, manager):
        tid = 6032
        manager.procesar_mensaje(tid, "soy vendedor")
        manager.procesar_mensaje(tid, "con recibo")
        manager.procesar_mensaje(tid, "Ana")
        manager.procesar_mensaje(tid, "ok")
        lead = manager.session_manager.get(tid).lead
        assert lead.tiene_recibo_sueldo is True

    def test_si_lo_tengo_no_confirma_para_otro_tipo(self, manager):
        """'sí lo tengo' no debe marcar recibo en un flujo monotributo."""
        tid = 6033
        manager.procesar_mensaje(tid, "soy vendedor")
        manager.procesar_mensaje(tid, "monotributo")
        manager.procesar_mensaje(tid, "Ana")
        manager.procesar_mensaje(tid, "sí lo tengo")
        lead = manager.session_manager.get(tid).lead
        assert lead.tiene_recibo_sueldo is None or lead.tiene_recibo_sueldo is False


# ─────────────────────────────────────────
# Flujo cliente con documento
# ─────────────────────────────────────────

class TestFlujoClienteDocumento:
    def test_cliente_envia_pdf_completa_flujo(self, manager, pdf_recibo):
        tid = 6041
        manager.procesar_mensaje(tid, "Hola")
        manager.procesar_mensaje(tid, "Soy Lucía")
        manager.procesar_mensaje(tid, "estoy en relación de dependencia")
        manager.procesar_mensaje(tid, "con recibo de sueldo")
        respuesta = manager.procesar_documento(
            tid, pdf_recibo, nombre_archivo="recibo.pdf"
        )
        session = manager.session_manager.get(tid)
        lead = session.lead

        assert lead.tipo_afiliacion == TipoAfiliacion.RELACION_DEPENDENCIA
        assert lead.tiene_recibo_sueldo is True
        assert lead.conceptos_obra_social == [15000.0, 8000.0]
        assert "recib" in respuesta.lower()

        respuesta = manager.procesar_mensaje(tid, "Córdoba, 32 años")
        assert session.etapa == EtapaConversacion.PRESENTANDO_VALOR
        assert isinstance(respuesta, RespuestaBot)

    def test_cliente_foto_sin_conceptos_pide_conceptos(self, manager, jpg_recibo):
        tid = 6042
        manager.procesar_mensaje(tid, "Hola")
        manager.procesar_mensaje(tid, "Soy Lucía")
        manager.procesar_mensaje(tid, "estoy en relación de dependencia")
        respuesta = manager.procesar_documento(tid, jpg_recibo)
        session = manager.session_manager.get(tid)
        lead = session.lead

        assert lead.tiene_recibo_sueldo is True
        assert lead.conceptos_obra_social == []
        assert "conceptos" in respuesta.lower()

    def test_documento_antes_del_nombre_pide_nombre(self, manager, pdf_recibo):
        tid = 6043
        manager.procesar_mensaje(tid, "Hola")
        respuesta = manager.procesar_documento(tid, pdf_recibo)
        assert "cómo te llamás" in respuesta.lower()
