"""
Ingestor de documentos para la base de conocimiento SERVIRED.

Convierte archivos markdown, texto plano y (preparado) PDFs
en registros en la tabla única ServiredKnowledgeDB.

Uso:
    from app.services.document_ingester import DocumentIngester
    ingester = DocumentIngester(knowledge_engine)
    ingester.ingestir_markdown("planes", "docs/planes.md")
    ingester.ingestir_texto("coberturas", "Coberturas SERVIRED", "...")
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class DocumentIngester:
    """
    Pipeline de ingestión de documentos para KnowledgeEngine.

    Convierte archivos en registros de ServiredKnowledgeDB.
    """

    def __init__(self, knowledge_engine) -> None:
        self._engine = knowledge_engine

    def ingestir_markdown(
        self,
        categoria: str,
        ruta_archivo: str | Path,
        titulo: Optional[str] = None,
        tags: str = "",
        prioridad_comercial: int = 0,
    ) -> int:
        """
        Ingesta un archivo markdown como registro de conocimiento.

        Returns:
            ID del registro creado.
        """
        ruta = Path(ruta_archivo)
        if not ruta.exists():
            raise FileNotFoundError(f"Archivo no encontrado: {ruta}")

        contenido = ruta.read_text(encoding="utf-8")
        if titulo is None:
            titulo = ruta.stem.replace("_", " ").replace("-", " ").title()

        return self._engine.guardar(
            titulo=titulo,
            categoria=categoria,
            contenido=contenido,
            tags=tags,
            fuente=str(ruta),
            prioridad_comercial=prioridad_comercial,
        )

    def ingestir_texto(
        self,
        categoria: str,
        titulo: str,
        contenido: str,
        tags: str = "",
        fuente: str = "",
        prioridad_comercial: int = 0,
    ) -> int:
        """
        Ingesta texto plano como registro de conocimiento.

        Returns:
            ID del registro creado.
        """
        return self._engine.guardar(
            titulo=titulo,
            categoria=categoria,
            contenido=contenido,
            tags=tags,
            fuente=fuente,
            prioridad_comercial=prioridad_comercial,
        )

    def ingestir_pdf(
        self,
        categoria: str,
        ruta_archivo: str | Path,
        titulo: Optional[str] = None,
        tags: str = "",
        prioridad_comercial: int = 0,
    ) -> int:
        """
        Ingesta un PDF como registro de conocimiento.

        NOTA: Requiere PyPDF2 o pdfplumber instalada.
        """
        ruta = Path(ruta_archivo)
        if not ruta.exists():
            raise FileNotFoundError(f"Archivo no encontrado: {ruta}")

        if titulo is None:
            titulo = ruta.stem.replace("_", " ").replace("-", " ").title()

        contenido = self._extraer_texto_pdf(ruta)

        return self._engine.guardar(
            titulo=titulo,
            categoria=categoria,
            contenido=contenido,
            tags=tags,
            fuente=str(ruta),
            prioridad_comercial=prioridad_comercial,
        )

    def _extraer_texto_pdf(self, ruta: Path) -> str:
        """Extrae texto de un PDF. Intenta PyPDF2, luego pdfplumber."""
        try:
            from PyPDF2 import PdfReader
            reader = PdfReader(str(ruta))
            partes = []
            for page in reader.pages:
                texto = page.extract_text()
                if texto:
                    partes.append(texto)
            return "\n\n".join(partes)
        except ImportError:
            pass

        try:
            import pdfplumber
            with pdfplumber.open(str(ruta)) as pdf:
                partes = []
                for page in pdf.pages:
                    texto = page.extract_text()
                    if texto:
                        partes.append(texto)
            return "\n\n".join(partes)
        except ImportError:
            raise NotImplementedError(
                "Para ingestar PDFs, instalá PyPDF2 o pdfplumber"
            )
