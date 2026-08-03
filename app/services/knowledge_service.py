"""
Servicio de base de conocimiento comercial SERVIRED.

Motor de conocimiento profundo que carga documentos desde archivos markdown
organizados por categoría y entrega contexto relevante según el Lead.

Uso:
    from app.services.knowledge_service import KnowledgeService
    ks = KnowledgeService()
    contexto = ks.contexto_para_lead(lead, etapa, mensaje)
    beneficios = ks.obtener_beneficios()
    objecion = ks.obtener_respuesta_objecion("precio")
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from app.models.lead import (
    Lead,
    NecesidadPrincipal,
    PrioridadCliente,
    TipoAfiliacion,
)

logger = logging.getLogger(__name__)

KNOWLEDGE_DIR = Path(__file__).parent.parent / "knowledge" / "servired"


class KnowledgeService:
    """
    Motor de conocimiento profundo SERVIRED.

    Carga documentos markdown organizados por categoría y entrega
    contexto relevante según el perfil del Lead y la etapa conversacional.
    """

    def __init__(self, knowledge_dir: Optional[Path] = None) -> None:
        self._dir = knowledge_dir or KNOWLEDGE_DIR
        self._cache: dict[str, str] = {}

    # ─────────────────────────────────────────
    # Carga de archivos (con búsqueda en subdirs)
    # ─────────────────────────────────────────

    def _cargar_archivo(self, nombre: str) -> str:
        """Carga un archivo markdown y lo cachea. Busca en subdirs."""
        if nombre in self._cache:
            return self._cache[nombre]

        # Buscar en raíz primero
        archivo = self._dir / f"{nombre}.md"
        if archivo.exists():
            contenido = archivo.read_text(encoding="utf-8")
            self._cache[nombre] = contenido
            return contenido

        # Buscar en subdirectorios
        for sub in self._dir.iterdir():
            if sub.is_dir():
                archivo_sub = sub / f"{nombre}.md"
                if archivo_sub.exists():
                    contenido = archivo_sub.read_text(encoding="utf-8")
                    self._cache[nombre] = contenido
                    return contenido

        logger.warning("Archivo de conocimiento no encontrado: %s", nombre)
        return ""

    def _cargar_archivo_ruta_relativa(self, ruta: str) -> str:
        """Carga un archivo por ruta relativa al directorio de conocimiento."""
        if ruta in self._cache:
            return self._cache[ruta]

        archivo = self._dir / ruta
        if archivo.exists():
            contenido = archivo.read_text(encoding="utf-8")
            self._cache[ruta] = contenido
            return contenido

        logger.warning("Archivo de conocimiento no encontrado: %s", ruta)
        return ""

    # ─────────────────────────────────────────
    # API backward-compatible (Sprint 1-14)
    # ─────────────────────────────────────────

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

    # ─────────────────────────────────────────
    # API profunda — conocimiento por categoría
    # ─────────────────────────────────────────

    def obtener_empresa(self) -> str:
        """Retorna información de la empresa SERVIRED."""
        return self._cargar_archivo_ruta_relativa("empresa/info.md")

    def obtener_planes(self) -> str:
        """Retorna el catálogo de planes."""
        return self._cargar_archivo_ruta_relativa("planes/catalogo.md")

    def obtener_coberturas(self) -> str:
        """Retorna la información detallada de coberturas."""
        return self._cargar_archivo_ruta_relativa("coberturas/detallada.md")

    def obtener_beneficios_por_categoria(self) -> str:
        """Retorna beneficios organizados por categoría de cliente."""
        return self._cargar_archivo_ruta_relativa("beneficios/por_categoria.md")

    def obtener_objeciones_avanzadas(self) -> str:
        """Retorna objeciones avanzadas con datos de venta."""
        return self._cargar_archivo_ruta_relativa("objeciones_avanzadas/respuestas.md")

    def obtener_comparativas(self) -> str:
        """Retorna comparativas con competencia."""
        return self._cargar_archivo_ruta_relativa("comparativas/vs_competencia.md")

    def obtener_farmacias(self) -> str:
        """Retorna información de la red de farmacias."""
        return self._cargar_archivo_ruta_relativa("farmacias/red_farmacias.md")

    def obtener_odontologia(self) -> str:
        """Retorna información de cobertura odontológica."""
        return self._cargar_archivo_ruta_relativa("odontologia/cobertura.md")

    def obtener_beneficios_planes(self) -> str:
        """Retorna los beneficios reales de los planes (cartillas oficiales)."""
        return self._cargar_archivo_ruta_relativa("planes/beneficios.md")

    def obtener_red_medica(self) -> str:
        """Retorna el resumen de la red de prestadores médicos."""
        return self._cargar_archivo_ruta_relativa("prestadores/red_medica.md")

    def obtener_red_farmacias(self) -> str:
        """Retorna el resumen de la red de farmacias adheridas."""
        return self._cargar_archivo_ruta_relativa("prestadores/red_farmacias.md")

    def obtener_red_odontologica(self) -> str:
        """Retorna el resumen de la red odontológica."""
        return self._cargar_archivo_ruta_relativa("prestadores/red_odontologica.md")

    # ─────────────────────────────────────────
    # Métodos de búsqueda por contexto (Sprint 1-14)
    # ─────────────────────────────────────────

    def obtener_respuesta_objecion(self, tipo_objecion: str) -> str:
        """
        Busca la respuesta sugerida para un tipo de objeción.
        Busca en objeciones básicas y avanzadas.
        """
        # Buscar primero en objeciones avanzadas
        avanzadas = self.obtener_objeciones_avanzadas()
        tipo_lower = tipo_objecion.lower()

        for seccion in avanzadas.split("## "):
            if tipo_lower in seccion.lower():
                if "Respuesta sugerida:" in seccion:
                    parte = seccion.split("Respuesta sugerida:", 1)[1]
                    respuesta = parte.replace("**", "").strip()
                    for fin in ["\n\n##", "\n\n#"]:
                        if fin in respuesta:
                            respuesta = respuesta.split(fin)[0].strip()
                    return respuesta

        # Fallback a objeciones básicas
        contenido = self.obtener_objeciones()
        for seccion in contenido.split("## "):
            if tipo_lower in seccion.lower():
                if "Respuesta sugerida:" in seccion:
                    parte = seccion.split("Respuesta sugerida:", 1)[1]
                    respuesta = parte.replace("**", "").strip()
                    for fin in ["\n\n##", "\n\n#"]:
                        if fin in respuesta:
                            respuesta = respuesta.split(fin)[0].strip()
                    return respuesta

        return ""

    def obtener_argumento_perfil(self, perfil: str) -> str:
        """Busca argumentos de venta para un perfil específico."""
        contenido = self.obtener_argumentos_venta()
        perfil_lower = perfil.lower()

        for seccion in contenido.split("## "):
            if perfil_lower in seccion.lower():
                if "**Mensaje:**" in seccion:
                    parte = seccion.split("**Mensaje:**", 1)[1]
                    mensaje = parte.replace("**", "").strip()
                    if "\n\n##" in mensaje:
                        mensaje = mensaje.split("\n\n##")[0].strip()
                    return mensaje

        return ""

    def obtener_tecnica_cierre(self, tipo: str) -> str:
        """Busca una técnica de cierre específica."""
        contenido = self.obtener_cierres()
        tipo_lower = tipo.lower()

        for seccion in contenido.split("## "):
            if tipo_lower in seccion.lower():
                if "**Ejemplos:**" in seccion:
                    parte = seccion.split("**Ejemplos:**")[1]
                    ejemplos = parte.split("**Pasos:**")[0].strip()
                    return ejemplos

        return ""

    def obtener_beneficios_para_perfil(self, perfil: str) -> str:
        """Busca beneficios específicos para un perfil."""
        contenido = self.obtener_argumentos_venta()
        perfil_lower = perfil.lower()

        for seccion in contenido.split("## "):
            if perfil_lower in seccion.lower():
                if "**Beneficios clave:**" in seccion:
                    parte = seccion.split("**Beneficios clave:**")[1]
                    beneficios = parte.strip().split("\n\n")[0]
                    return beneficios

        return ""

    # ─────────────────────────────────────────
    # Motor de conocimiento profundo — contexto por Lead
    # ─────────────────────────────────────────

    def contexto_para_lead(
        self,
        lead: Lead,
        etapa: str = "",
        mensaje: str = "",
    ) -> str:
        """
        Genera contexto de conocimiento relevante para el Lead.

        Analiza el perfil del Lead y entrega únicamente la información
        que el AIService necesita para generar una respuesta comercial.

        Args:
            lead: Lead con datos del cliente.
            etapa: Etapa de la conversación.
            mensaje: Último mensaje del cliente.

        Returns:
            Contexto de conocimiento concatenado.
        """
        partes: list[str] = []

        # 1. Empresa (siempre, para contexto general)
        empresa = self.obtener_empresa()
        if empresa:
            partes.append(f"## Sobre SERVIRED\n{empresa[:500]}")

        # 2. Planes relevantes según perfil
        planes = self._planes_para_lead(lead)
        if planes:
            partes.append(f"## Planes recomendados\n{planes}")

        # 3. Beneficios relevantes
        beneficios = self._beneficios_para_lead(lead)
        if beneficios:
            partes.append(f"## Beneficios relevantes\n{beneficios}")

        # 4. Coberturas relevantes
        coberturas = self._coberturas_para_lead(lead, mensaje)
        if coberturas:
            partes.append(f"## Coberturas\n{coberturas}")

        # 5. Objeciones (si el mensaje parece objeción)
        objeciones = self._objeciones_para_mensaje(mensaje)
        if objeciones:
            partes.append(f"## Respuesta a objeciones\n{objeciones}")

        # 6. Comparativas (si el cliente menciona competencia)
        if self._menciona_competencia(mensaje):
            comparativas = self.obtener_comparativas()
            if comparativas:
                partes.append(f"## Comparativas\n{comparativas[:600]}")

        # 7. Odontología (si pregunta por odontología)
        if self._menciona_odontologia(mensaje):
            odonto = self.obtener_odontologia()
            if odonto:
                partes.append(f"## Odontología\n{odonto}")

        # 8. Farmacias (si pregunta por medicamentos)
        if self._menciona_farmacias(mensaje):
            farm = self.obtener_farmacias()
            if farm:
                partes.append(f"## Farmacias\n{farm}")

        return "\n\n".join(partes)

    def _planes_para_lead(self, lead: Lead) -> str:
        """Selecciona los planes más relevantes según el perfil del Lead."""
        planes = self.obtener_planes()
        if not planes:
            return ""

        perfil = self._detectar_perfil(lead)
        if not perfil:
            return planes[:600]

        partes: list[str] = []
        for seccion in planes.split("## "):
            seccion_lower = seccion.lower()
            if perfil in seccion_lower:
                partes.append(seccion.strip())

        return "\n\n".join(partes) if partes else planes[:600]

    def _beneficios_para_lead(self, lead: Lead) -> str:
        """Selecciona beneficios relevantes según el perfil."""
        beneficios = self.obtener_beneficios_por_categoria()
        if not beneficios:
            return self.obtener_beneficios()

        perfil = self._detectar_perfil(lead)
        if not perfil:
            return beneficios[:600]

        partes: list[str] = []
        for seccion in beneficios.split("## "):
            seccion_lower = seccion.lower()
            if perfil in seccion_lower:
                partes.append(seccion.strip())

        return "\n\n".join(partes) if partes else beneficios[:600]

    def _coberturas_para_lead(self, lead: Lead, mensaje: str) -> str:
        """Selecciona coberturas relevantes según el Lead y el mensaje."""
        coberturas = self.obtener_coberturas()
        if not coberturas:
            return ""

        mensaje_lower = mensaje.lower()

        partes: list[str] = []
        for seccion in coberturas.split("## "):
            seccion_lower = seccion.lower()
            if any(p in mensaje_lower for p in [
                "emergencia", "urgente", "accidente",
            ]) and "emergencia" in seccion_lower:
                partes.append(seccion.strip())
            elif any(p in mensaje_lower for p in [
                "estudio", "análisis", "análisis", "laboratorio",
            ]) and "estudio" in seccion_lower:
                partes.append(seccion.strip())
            elif any(p in mensaje_lower for p in [
                "internación", "hospital", "clínica",
            ]) and "internación" in seccion_lower:
                partes.append(seccion.strip())

        if not partes:
            return coberturas[:500]

        return "\n\n".join(partes)

    def _objeciones_para_mensaje(self, mensaje: str) -> str:
        """Busca objeciones relevantes para el mensaje actual."""
        if not mensaje:
            return ""

        avanzadas = self.obtener_objeciones_avanzadas()
        if not avanzadas:
            return ""

        mensaje_lower = mensaje.lower()
        partes: list[str] = []

        for seccion in avanzadas.split("## "):
            seccion_lower = seccion.lower()
            if any(p in mensaje_lower for p in [
                "caro", "cuesta", "precio", "dinero", "plata", "costo",
            ]) and any(p in seccion_lower for p in ["caro", "precio"]):
                partes.append(seccion.strip())
            elif any(p in mensaje_lower for p in [
                "pensar", "después", "luego", "mañana",
            ]) and any(p in seccion_lower for p in ["pensar", "tiempo"]):
                partes.append(seccion.strip())
            elif any(p in mensaje_lower for p in [
                "seguro", "duda", "no sé", "no estoy",
            ]) and any(p in seccion_lower for p in ["seguro", "duda", "convencido"]):
                partes.append(seccion.strip())
            elif any(p in mensaje_lower for p in [
                "otra obra", "ya tengo", "cambiar",
            ]) and any(p in seccion_lower for p in ["otra obra", "cambiar"]):
                partes.append(seccion.strip())

        return "\n\n".join(partes) if partes else ""

    def _detectar_perfil(self, lead: Lead) -> str:
        """Detecta el perfil del Lead para seleccionar conocimiento."""
        if lead.grupo_familiar.conyuge or lead.grupo_familiar.hijos:
            return "familia"
        if lead.tipo_afiliacion == TipoAfiliacion.MONOTRIBUTO:
            return "monotributista"
        if lead.tipo_afiliacion == TipoAfiliacion.RELACION_DEPENDENCIA:
            return "aportes"
        if lead.tipo_afiliacion == TipoAfiliacion.PARTICULAR:
            return "particular"
        if lead.prioridad_cliente == PrioridadCliente.ECONOMICO:
            return "económico"
        if lead.prioridad_cliente == PrioridadCliente.COMPLETO:
            return "premium"
        return ""

    def _menciona_competencia(self, mensaje: str) -> bool:
        """Detecta si el mensaje menciona competencia."""
        if not mensaje:
            return False
        mensaje_lower = mensaje.lower()
        return any(p in mensaje_lower for p in [
            "otra obra", "otra prepaga", "ya tengo", "cambio",
            "comparar", "diferencia", "mejor que",
        ])

    def _menciona_odontologia(self, mensaje: str) -> bool:
        """Detecta si el mensaje menciona odontología."""
        if not mensaje:
            return False
        mensaje_lower = mensaje.lower()
        return any(p in mensaje_lower for p in [
            "odontol", "dental", "diente", "dientes",
            "ortodonc", "bracket", "limpieza dental",
        ])

    def _menciona_farmacias(self, mensaje: str) -> bool:
        """Detecta si el mensaje menciona farmacias o medicamentos."""
        if not mensaje:
            return False
        mensaje_lower = mensaje.lower()
        return any(p in mensaje_lower for p in [
            "farmacia", "medicamento", "medicación",
            "remedio", "receta", "comprar pastilla",
        ])
