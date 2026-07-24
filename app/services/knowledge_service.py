"""
Servicio de base de conocimiento comercial SERVIRED.

Carga y entrega contenido estructurado desde archivos markdown
para ser utilizado por la asistente comercial Sofía.

Uso:
    from app.services.knowledge_service import KnowledgeService
    ks = KnowledgeService()
    beneficios = ks.obtener_beneficios()
    objecion = ks.obtener_respuesta_objecion("precio")
    cierre = ks.obtener_tecnica_cierre("directo")
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

KNOWLEDGE_DIR = Path(__file__).parent.parent / "knowledge" / "servired"


class KnowledgeService:
    """
    Servicio de acceso a la base de conocimiento SERVIRED.

    Carga archivos markdown y entrega contenido segmentado
    según la necesidad del momento (beneficios, objeciones, cierres, etc.).
    """

    def __init__(self, knowledge_dir: Optional[Path] = None) -> None:
        self._dir = knowledge_dir or KNOWLEDGE_DIR
        self._cache: dict[str, str] = {}

    def _cargar_archivo(self, nombre: str) -> str:
        """Carga un archivo markdown y lo cachea."""
        if nombre in self._cache:
            return self._cache[nombre]

        archivo = self._dir / f"{nombre}.md"
        if not archivo.exists():
            logger.warning("Archivo de conocimiento no encontrado: %s", archivo)
            return ""

        contenido = archivo.read_text(encoding="utf-8")
        self._cache[nombre] = contenido
        return contenido

    def obtener_beneficios(self) -> str:
        """Retorna el contenido completo de beneficios."""
        return self._cargar_archivo("beneficios")

    def obtener_faq(self) -> str:
        """Retorna las preguntas frecuentes."""
        return self._cargar_archivo("faq")

    def obtener_objeciones(self) -> str:
        """Retorna el contenido de objeciones comerciales."""
        return self._cargar_archivo("objections")

    def obtener_argumentos_venta(self) -> str:
        """Retorna los argumentos de venta."""
        return self._cargar_archivo("sales_arguments")

    def obtener_cierres(self) -> str:
        """Retorna las técnicas de cierre."""
        return self._cargar_archivo("closing")

    # ── Métodos de búsqueda por contexto ──

    def obtener_respuesta_objecion(self, tipo_objecion: str) -> str:
        """
        Busca la respuesta sugerida para un tipo de objeción.

        Args:
            tipo_objecion: Texto clave de la objeción (ej: "caro", "pensar", "seguro").

        Returns:
            Respuesta sugerida o string vacío si no encuentra.
        """
        contenido = self.obtener_objeciones()
        tipo_lower = tipo_objecion.lower()

        # Buscar sección que contenga la palabra clave
        secciones = contenido.split("## ")
        for seccion in secciones:
            if tipo_lower in seccion.lower():
                # Extraer después de "Respuesta sugerida:" (quitar markers **)
                if "Respuesta sugerida:" in seccion:
                    parte = seccion.split("Respuesta sugerida:", 1)[1]
                    # Quitar markers ** y espacios
                    respuesta = parte.replace("**", "").strip()
                    # Tomar solo hasta el siguiente salto doble o ##
                    for fin in ["\n\n##", "\n\n#"]:
                        if fin in respuesta:
                            respuesta = respuesta.split(fin)[0].strip()
                    return respuesta

        return ""

    def obtener_argumento_perfil(self, perfil: str) -> str:
        """
        Busca argumentos de venta para un perfil específico.

        Args:
            perfil: Tipo de perfil (ej: "familias", "monotributistas").

        Returns:
            Argumentos del perfil o string vacío.
        """
        contenido = self.obtener_argumentos_venta()
        perfil_lower = perfil.lower()

        secciones = contenido.split("## ")
        for seccion in secciones:
            if perfil_lower in seccion.lower():
                # Extraer mensaje principal
                if "**Mensaje:**" in seccion:
                    parte = seccion.split("**Mensaje:**", 1)[1]
                    # Quitar markers ** y espacios
                    mensaje = parte.replace("**", "").strip()
                    # Tomar solo hasta el siguiente ##
                    if "\n\n##" in mensaje:
                        mensaje = mensaje.split("\n\n##")[0].strip()
                    return mensaje

        return ""

    def obtener_tecnica_cierre(self, tipo: str) -> str:
        """
        Busca una técnica de cierre específica.

        Args:
            tipo: Tipo de cierre (ej: "directo", "alternativo", "siguiente paso").

        Returns:
            Descripción de la técnica o string vacío.
        """
        contenido = self.obtener_cierres()
        tipo_lower = tipo.lower()

        secciones = contenido.split("## ")
        for seccion in secciones:
            if tipo_lower in seccion.lower():
                # Extraer ejemplos
                if "**Ejemplos:**" in seccion:
                    parte = seccion.split("**Ejemplos:**")[1]
                    ejemplos = parte.split("**Pasos:**")[0].strip()
                    return ejemplos

        return ""

    def obtener_beneficios_para_perfil(self, perfil: str) -> str:
        """
        Busca beneficios específicos para un perfil.

        Args:
            perfil: Tipo de perfil (ej: "familias", "monotributistas").

        Returns:
            Beneficios del perfil o string vacío.
        """
        contenido = self.obtener_argumentos_venta()
        perfil_lower = perfil.lower()

        secciones = contenido.split("## ")
        for seccion in secciones:
            if perfil_lower in seccion.lower():
                if "**Beneficios clave:**" in seccion:
                    parte = seccion.split("**Beneficios clave:**")[1]
                    beneficios = parte.strip().split("\n\n")[0]
                    return beneficios

        return ""
