"""
Servicio de respuestas sobre prestaciones SERVIRED.

Responde preguntas específicas del cliente sobre beneficios, cartillas
y prestaciones (ej: "¿cubren odontología?", "¿hay farmacias adheridas?",
"¿qué incluye el plan gold?").

Fuentes permitidas (en orden):
    1. Base de datos (KnowledgeEngine) — fuente primaria.
    2. Archivos markdown (KnowledgeService) — resúmenes de cartillas oficiales.
    3. Web oficial serviredsalud.com.ar (WebKnowledgeService) — SOLO si el
       dato no está en la DB ni en los archivos.

Nunca inventa información. Si no hay dato disponible, devuelve None para
que la conversación continúe con el flujo normal.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

PLANES_NOMBRES = ["gold", "medimax gold", "medimax_gold", "medimax co", "medimax_co", "medimax"]


class PrestacionesService:
    """
    Detecta preguntas sobre prestaciones y responde con conocimiento real.
    """

    # ── Categorías y keywords de detección ──
    CATEGORIAS: dict[str, list[str]] = {
        "farmacias": [
            "farmacia", "farmacias", "remedio", "remedios", "medicamento",
            "medicamentos", "medicación", "medicacion", "pastillas", "receta",
            "descuento en farmacia",
        ],
        "odontologia": [
            "odontolog", "dental", "dientes", "dentista", "ortodon",
            "bracket", "brackets", "limpieza dental", "cirugía bucal",
            "cirugia bucal", "odontopediatr", "prótesis", "protesis dental",
            "blanqueamiento",
        ],
        "opticas": [
            "óptica", "optica", "ópticas", "opticas", "lentes", "anteojos",
            "cristales", "armazones", "lentes de contacto",
        ],
        "prestadores": [
            "cartilla", "prestador", "prestadores", "médicos", "medicos",
            "doctores", "especialistas", "clínica", "clinica", "sanatorio",
            "especialidad", "especialidades", "red médica", "red medica",
            "atención médica", "atencion medica", "en mi localidad",
            "en mi barrio", "cerca de mi", "cerca mio",
        ],
        "coberturas": [
            "estudios", "análisis", "analisis", "laboratorio", "laboratorios",
            "resonancia", "tomografía", "tomografia", "mamografía", "mamografia",
            "radiografía", "radiografia", "diagnóstico por imágenes",
            "diagnostico por imagenes", "imágenes", "imagenes", "tac",
            "diagnóstico", "diagnostico",
        ],
        "emergencias": [
            "urgencia", "urgencias", "emergencia", "emergencias", "traslado",
            "asistencia domiciliaria", "atención domiciliaria", "ambulancia",
            "urgencias 24", "24 horas", "guardia",
        ],
        "internacion": [
            "internación", "internacion", "cirugía", "cirugia", "hospitalización",
            "hospitalizacion", "uci", "uti", "materno", "parto", "cesárea",
            "cesarea", "quirófano", "quiropano",
        ],
        "salud_mental": [
            "psicología", "psicologia", "psicólogo", "psicologo", "psiquiatr",
            "salud mental",
        ],
        "planes": [
            "qué cubre", "que cubre", "qué incluye", "que incluye",
            "qué beneficios", "que beneficios", "qué cobertura", "que cobertura",
            "beneficios del plan", "incluye el plan", "cubre el plan",
            "cobertura de los planes", "qué tiene el", "que tiene el",
        ],
    }

    # ── Accesoores de archivos markdown por categoría ──
    _MARKDOWN: dict[str, str] = {
        "farmacias": "obtener_red_farmacias",
        "odontologia": "obtener_red_odontologica",
        "opticas": "obtener_beneficios_planes",
        "prestadores": "obtener_red_medica",
        "coberturas": "obtener_beneficios_planes",
        "emergencias": "obtener_beneficios_planes",
        "internacion": "obtener_beneficios_planes",
        "salud_mental": "obtener_beneficios_planes",
        "planes": "obtener_beneficios_planes",
    }

    # ── Orden de prioridad para evitar falsos positivos ──
    # Las categorías más específicas se evalúan primero.
    _ORDEN = [
        "odontologia", "farmacias", "opticas", "salud_mental",
        "emergencias", "internacion", "coberturas", "prestadores", "planes",
    ]

    def __init__(
        self,
        knowledge_engine: Optional[Any] = None,
        knowledge_service: Optional[Any] = None,
        web_service: Optional[Any] = None,
    ) -> None:
        self._engine = knowledge_engine
        self._knowledge = knowledge_service
        self._web = web_service

    # ─────────────────────────────────────────
    # API pública
    # ─────────────────────────────────────────

    def responder(self, mensaje: str) -> tuple[str, str] | None:
        """
        Responde una pregunta sobre prestaciones si la detecta.

        Returns:
            Tupla (respuesta, categoria) o None si no hay pregunta
            de prestaciones o no hay dato disponible.
        """
        if not mensaje or len(mensaje.strip()) < 4:
            return None

        categoria = self._detectar_categoria(mensaje)
        if not categoria:
            return None

        contenido = self._obtener_contenido(categoria, mensaje)
        if not contenido:
            return None

        respuesta = self._formatear(categoria, contenido, mensaje)
        if not respuesta:
            return None

        return respuesta, categoria

    def detectar(self, mensaje: str) -> str | None:
        """Detecta la categoría de prestación en el mensaje (sin resolver contenido)."""
        return self._detectar_categoria(mensaje)

    def detalle_plan(self, plan: str) -> str:
        """
        Devuelve la sección detallada de beneficios de un plan desde la
        cartilla oficial (markdown → DB → web). Vacío si no hay sección.

        Acepta claves con espacios o guiones bajos
        (ej: "medimax_gold" o "medimax gold").
        """
        if not plan:
            return ""
        clave = plan.lower().strip().replace("_", " ").replace("-", " ")
        clave = " ".join(clave.split())

        # 1. Markdown oficial (contenido completo, sin truncar).
        contenido = ""
        if self._knowledge is not None:
            try:
                contenido = self._knowledge.obtener_beneficios_planes() or ""
            except Exception as exc:
                logger.warning("[PRESTACIONES] Error leyendo beneficios.md: %s", exc)

        # 2. DB (si el markdown no está disponible).
        if not contenido:
            contenido = self._obtener_contenido("planes", f"que cubre el plan {clave}")

        if not contenido:
            return ""
        seccion = self._extraer_seccion_plan(contenido, clave)
        return seccion or ""

    # ─────────────────────────────────────────
    # Detección de categoría
    # ─────────────────────────────────────────

    def _detectar_categoria(self, mensaje: str) -> str | None:
        texto = self._normalizar(mensaje)
        for cat in self._ORDEN:
            for kw in self.CATEGORIAS[cat]:
                if self._coincide(texto, kw):
                    # "farmacia" no debe activarse por "farmacéutica" en contexto de planes
                    return cat
        return None

    @staticmethod
    def _coincide(texto: str, kw: str) -> bool:
        # Palabras cortas (uti, uci, tac) solo como palabra completa para no
        # disparar por subcadenas tipo "monotributista" (contiene "uti").
        if len(kw) <= 4:
            return re.search(rf"\b{re.escape(kw)}\b", texto) is not None
        return kw in texto

    @staticmethod
    def _normalizar(texto: str) -> str:
        texto = texto.lower()
        acentos = {
            "á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ü": "u", "ñ": "n",
        }
        return "".join(acentos.get(c, c) for c in texto)

    # ─────────────────────────────────────────
    # Obtención de contenido
    # ─────────────────────────────────────────

    def _obtener_contenido(self, categoria: str, mensaje: str) -> str:
        # 1. Base de datos (fuente primaria)
        desde_db = self._desde_db(categoria, mensaje)
        if desde_db:
            return desde_db

        # 2. Archivos markdown (resúmenes de cartillas oficiales)
        desde_markdown = self._desde_markdown(categoria)
        if desde_markdown:
            return desde_markdown

        # 3. Web oficial (último recurso)
        if self._web is not None:
            desde_web = self._web.consultar_categoria(categoria)
            if desde_web:
                return desde_web

        return ""

    def _desde_db(self, categoria: str, mensaje: str) -> str:
        if self._engine is None:
            return ""
        try:
            return self._engine.buscar_contenido(categoria, mensaje)
        except Exception as exc:
            logger.warning("[PRESTACIONES] Error consultando DB: %s", exc)
            return ""

    def _desde_markdown(self, categoria: str) -> str:
        if self._knowledge is None:
            return ""
        metodo = getattr(self._knowledge, self._MARKDOWN.get(categoria, ""), None)
        if metodo is None:
            return ""
        try:
            return metodo() or ""
        except Exception as exc:
            logger.warning("[PRESTACIONES] Error leyendo markdown '%s': %s", categoria, exc)
            return ""

    # ─────────────────────────────────────────
    # Formateo de respuesta
    # ─────────────────────────────────────────

    # ── Introducción natural por categoría ──
    _INTROS: dict[str, str] = {
        "farmacias": "Sí, SERVIRED tiene una amplia red de farmacias adheridas.",
        "odontologia": "Sí, los planes SERVIRED incluyen cobertura odontológica.",
        "opticas": "Sí, los planes incluyen cobertura de ópticas.",
        "prestadores": "SERVIRED tiene una amplia red de prestadores en Córdoba capital e interior.",
        "coberturas": "Los planes SERVIRED cubren prácticas de diagnóstico y estudios.",
        "emergencias": "Los planes incluyen urgencias, emergencias y traslados.",
        "internacion": "Los planes incluyen cirugías e internaciones clínicas.",
        "salud_mental": "Sí, los planes cubren salud mental (psicología y psiquiatría).",
        "planes": "Estos son los beneficios que incluyen los planes SERVIRED:",
    }

    # ── Búsqueda de la prestación puntual dentro de los beneficios de planes ──
    _BENEFICIO_BUSQUEDA: dict[str, list[str]] = {
        "salud_mental": ["salud mental"],
        "opticas": ["ópticas", "cristales - armazones", "lentes de contacto"],
        "internacion": ["plan materno infantil", "internaciones en uci", "cirugía e internaciones"],
        "emergencias": ["urgencias, emergencias", "traslado, asistencia"],
        "coberturas": ["prácticas de diagnóstico", "diagnóstico por imágenes", "radiografías / mamografías"],
        "odontologia": ["odontología general", "prótesis odontológica", "blanqueamiento"],
        "farmacias": ["red médica, farmacéutica", "farmacéutica"],
    }

    def _formatear(self, categoria: str, contenido: str, mensaje: str) -> str:
        # Si pregunta por un plan específico, extraer su sección del contenido crudo
        plan = self._plan_mencionado(mensaje)
        if plan and categoria in ("planes", "coberturas", "internacion",
                                  "emergencias", "salud_mental", "opticas"):
            seccion = self._extraer_seccion_plan(contenido, plan)
            if seccion:
                intro = self._INTROS.get(categoria, "")
                return f"{intro}\n{seccion}"

        texto = self._limpiar_markdown(contenido)

        # Beneficio puntual dentro de los beneficios de planes
        if categoria in self._BENEFICIO_BUSQUEDA:
            puntual = self._buscar_beneficio(texto, self._BENEFICIO_BUSQUEDA[categoria])
            if puntual:
                intro = self._INTROS.get(categoria, "")
                return f"{intro} {puntual}"

        return self._primer_parrafo(texto, categoria)

    def _buscar_beneficio(self, texto: str, keywords: list[str]) -> str:
        """Busca la línea del beneficio que coincide con las keywords."""
        for kw in keywords:
            kw_norm = self._normalizar(kw)
            for linea in texto.splitlines():
                if kw_norm in self._normalizar(linea):
                    linea_limpia = linea.strip()
                    if linea_limpia.startswith("-"):
                        linea_limpia = linea_limpia.lstrip("- ").strip()
                    return linea_limpia[:300]
        return ""

    def _plan_mencionado(self, mensaje: str) -> str | None:
        texto = self._normalizar(mensaje)
        # "medimax gold" antes que "gold"
        if "medimax gold" in texto or "medimax_gold" in texto:
            return "medimax gold"
        if "medimax co" in texto or "medimax_co" in texto:
            return "medimax co"
        if "gold" in texto:
            return "gold"
        if "medimax" in texto:
            return "medimax"
        return None

    def _extraer_seccion_plan(self, contenido: str, plan: str) -> str:
        """Extrae la sección de un plan específico del markdown crudo."""
        patrones = {
            "gold": r"##\s+Plan\s+Gold\b",
            "medimax gold": r"##\s+Plan\s+Medimax\s+Gold\b",
            "medimax co": r"##\s+Plan\s+Medimax\s+CO\b",
            "medimax": r"##\s+Plan\s+Medimax\b(?!\s*(?:Gold|CO|Co)\b)",
        }
        patron = patrones.get(plan)
        if not patron:
            return ""
        match = re.search(patron, contenido, re.IGNORECASE)
        if not match:
            return ""

        inicio = match.end()
        fin = inicio
        for sig in (r"##\s+Plan\s+Gold\b", r"##\s+Plan\s+Medimax\s+Gold\b",
                    r"##\s+Plan\s+Medimax\s+CO\b", r"##\s+Plan\s+Medimax\b",
                    r"##\s+Nota\b"):
            for m in re.finditer(sig, contenido[inicio:], re.IGNORECASE):
                pos = inicio + m.start()
                if fin == inicio or pos < fin:
                    fin = pos
                break

        seccion = contenido[inicio:fin if fin > inicio else inicio + 1500]
        # Limpiar subencabezados de la sección
        lineas = []
        for l in seccion.splitlines():
            s = l.strip()
            if re.match(r"^#{1,4}\s", s):
                continue
            if s:
                lineas.append(s)
        return "\n".join(lineas)[:1400]

    def _primer_parrafo(self, texto: str, categoria: str) -> str:
        """Extrae los primeros datos útiles del contenido."""
        lineas = [l.strip() for l in texto.splitlines() if l.strip()]
        utiles: list[str] = []
        for l in lineas:
            if l.startswith("#"):
                continue
            if l.startswith("-") and any(k in l.lower() for k in [
                "cobertura", "localidades", "prestador", "farmacia", "odontólog",
                "odontolog", "incluye", "sin coseguro", "red", "médica", "medica",
            ]):
                utiles.append(l)
            elif len(utiles) < 3:
                utiles.append(l)
            if len(utiles) >= 4:
                break

        base = " ".join(utiles) if utiles else texto[:400]
        return base[:600]

    @staticmethod
    def _limpiar_markdown(texto: str) -> str:
        """Quita encabezados, fuentes y referencias sobrantes."""
        lineas = []
        for l in texto.splitlines():
            s = l.strip()
            if not s:
                continue
            if s.startswith("_") and s.endswith("_"):
                continue
            if re.match(r"^#+\s", s):
                continue
            if re.match(r"^fuente", s, re.IGNORECASE):
                continue
            lineas.append(s)
        return "\n".join(lineas)
