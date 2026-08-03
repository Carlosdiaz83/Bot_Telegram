"""
Motor de conocimiento SERVIRED — fuente única de verdad.

Consulta la tabla unificada ServiredKnowledgeDB para encontrar
información relevante sobre planes, coberturas, beneficios,
objeciones y cierres según el Lead y la etapa conversacional.

Uso:
    from app.services.knowledge_engine import KnowledgeEngine
    engine = KnowledgeEngine(db_session)
    contexto = engine.contexto_para_lead(lead, etapa, mensaje)
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.database.repository import KnowledgeRepository
from app.models.lead import Lead, PrioridadCliente, TipoAfiliacion

logger = logging.getLogger(__name__)


class KnowledgeEngine:
    """
    Motor de conocimiento basado en PostgreSQL (tabla única).

    Consulta ServiredKnowledgeDB para encontrar información relevante
    según el perfil del Lead y la etapa conversacional.
    """

    def __init__(self, db: Session) -> None:
        self._repo = KnowledgeRepository(db)

    @property
    def disponible(self) -> bool:
        """Indica si hay datos de conocimiento en la DB."""
        return len(self._repo.activos()) > 0

    # ─────────────────────────────────────────
    # Contexto principal
    # ─────────────────────────────────────────

    def contexto_para_lead(
        self,
        lead: Lead,
        etapa: str = "",
        mensaje: str = "",
    ) -> str:
        """
        Genera contexto de conocimiento SERVIRED para un Lead.

        Busca en la tabla única por categoría, tags y texto relevante.

        Args:
            lead: Lead con datos del cliente.
            etapa: Etapa de la conversación.
            mensaje: Último mensaje del cliente.

        Returns:
            Texto con contexto relevante para el LLM.
        """
        perfil = self._detectar_perfil(lead)
        partes: list[str] = []

        # 1. Contexto general desde la DB
        contexto_general = self._repo.contexto_para_lead(
            perfil=perfil,
            necesidad=lead.necesidad_principal.value if lead.necesidad_principal else "",
            mensaje=mensaje,
        )
        if contexto_general:
            partes.append(contexto_general)

        # 2. Información específica por etapa
        info_etapa = self._info_por_etapa(lead, etapa)
        if info_etapa:
            partes.append(info_etapa)

        # 3. Búsqueda por tags del mensaje
        if mensaje:
            tags = self._extraer_tags(mensaje)
            if tags:
                por_tags = self._repo.buscar_por_tags(tags, limite=5)
                for item in por_tags:
                    partes.append(item.contenido[:250])

        resultado = "\n\n".join(partes)
        logger.debug(
            "[KNOWLEDGE_ENGINE] contexto generado: perfil=%s, partes=%d, chars=%d",
            perfil, len(partes), len(resultado),
        )
        return resultado

    # ─────────────────────────────────────────
    # Información por etapa
    # ─────────────────────────────────────────

    def _info_por_etapa(self, lead: Lead, etapa: str) -> str:
        """Busca en la DB información específica según la etapa."""
        partes: list[str] = []

        if etapa == "presentando_valor":
            items = self._repo.buscar_por_categoria("planes")
            if items:
                partes.append("Planes SERVIRED:")
                for item in items[:4]:
                    partes.append(f"  • {item.titulo}: {item.contenido[:150]}")

        elif etapa == "manejando_objeciones":
            items = self._repo.buscar_por_categoria("objeciones")
            if items:
                partes.append("Respuestas a objeciones:")
                for item in items[:3]:
                    partes.append(f"  • {item.titulo}: {item.contenido[:150]}")

        elif etapa == "intentando_cierre":
            items = self._repo.buscar_por_categoria("cierres")
            if items:
                partes.append("Argumentos de cierre:")
                for item in items[:3]:
                    partes.append(f"  • {item.titulo}: {item.contenido[:150]}")

        return "\n\n".join(partes)

    # ─────────────────────────────────────────
    # Tags
    # ─────────────────────────────────────────

    def _extraer_tags(self, mensaje: str) -> list[str]:
        """Extrae tags relevantes del mensaje."""
        palabras_stop = {
            "hola", "que", "como", "cual", "cuales", "donde", "cuando",
            "quiero", "necesito", "puedo", "sos", "tenes", "hay",
            "el", "la", "los", "las", "un", "una", "de", "del",
            "al", "en", "con", "por", "para", "sin", "sobre",
            "este", "esta", "esto", "ese", "esa", "eso",
            "mi", "tu", "su", "nuestro", "vuestro",
            "muy", "mas", "menos", "bien", "mal",
            "si", "no", "ok", "bueno", "gracias",
            "soy", "tengo", "teneis", "somos",
            "alguna", "algun", "algo", "nada", "todo",
        }
        palabras = (
            mensaje.lower()
            .replace("?", "").replace("!", "").replace(".", "").replace(",", "")
            .split()
        )
        return [p for p in palabras if len(p) > 3 and p not in palabras_stop][:10]

    # ─────────────────────────────────────────
    # Perfil
    # ─────────────────────────────────────────

    def _detectar_perfil(self, lead: Lead) -> str:
        """Detecta el perfil del Lead para buscar conocimiento relevante."""
        if lead.prioridad_cliente == PrioridadCliente.ECONOMICO:
            return "economico"
        if lead.grupo_familiar.conyuge or lead.grupo_familiar.hijos:
            return "familias"
        if lead.tipo_afiliacion == TipoAfiliacion.MONOTRIBUTO:
            return "monotributistas"
        return "particulares"

    # ─────────────────────────────────────────
    # Búsqueda puntual para preguntas de prestaciones
    # ─────────────────────────────────────────

    def buscar_contenido(self, categoria: str, mensaje: str = "") -> str:
        """
        Busca contenido puntual en la DB por categoría y palabras clave.

        Se usa para responder preguntas específicas sobre prestaciones
        (farmacias, odontología, cartillas, coberturas, etc.).

        Args:
            categoria: Categoría de conocimiento (farmacias, odontologia, etc.).
            mensaje: Mensaje del cliente para búsqueda por texto.

        Returns:
            Contenido relevante concatenado o "" si no hay resultados.
        """
        partes: list[str] = []

        # 1. Por categoría
        items = self._repo.buscar_por_categoria(categoria)
        for item in items[:3]:
            partes.append(item.contenido[:400])

        # 2. Por texto del mensaje (si la categoría no dio resultados)
        if not partes and mensaje:
            texto = self._normalizar_texto(mensaje)
            if texto:
                coincidencias = self._repo.buscar_por_texto(texto, limite=3)
                for item in coincidencias:
                    if item.contenido not in "\n".join(partes):
                        partes.append(item.contenido[:400])

        return "\n\n".join(partes)

    @staticmethod
    def _normalizar_texto(texto: str) -> str:
        """Extrae la primera palabra significativa para búsqueda."""
        palabras_stop = {
            "hola", "que", "como", "cual", "cuales", "donde", "cuando",
            "quiero", "necesito", "puedo", "hay", "el", "la", "los", "las",
            "un", "una", "de", "del", "al", "en", "con", "por", "para",
            "sin", "sobre", "que", "si", "no", "ok", "cubren", "cubre",
            "incluye", "tienen", "tiene", "hay",
        }
        acentos = {"á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ü": "u", "ñ": "n"}
        limpio = texto.lower()
        limpio = "".join(acentos.get(c, c) for c in limpio)
        for p in limpio.split():
            p = p.strip("?.,!¡")
            if len(p) > 4 and p not in palabras_stop:
                return p
        return ""

    # ─────────────────────────────────────────
    # CRUD (para ingestion)
    # ─────────────────────────────────────────

    def guardar(
        self,
        titulo: str,
        categoria: str,
        contenido: str,
        tags: str = "",
        fuente: str = "",
        prioridad_comercial: int = 0,
    ) -> int:
        """
        Guarda un registro de conocimiento.

        Returns:
            ID del registro creado.
        """
        item = self._repo.crear(
            titulo=titulo,
            categoria=categoria,
            contenido=contenido,
            tags=tags,
            fuente=fuente,
            prioridad_comercial=prioridad_comercial,
        )
        logger.info(
            "[KNOWLEDGE_ENGINE] Guardado: id=%d, titulo='%s', categoria='%s'",
            item.id, item.titulo, item.categoria,
        )
        return item.id
