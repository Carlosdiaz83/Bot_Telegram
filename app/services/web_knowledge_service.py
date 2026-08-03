"""
Servicio de conocimiento web SERVIRED — fallback autorizado.

Cuando la información solicitada NO está en la base de datos, consulta
la web oficial de SERVIRED (https://www.serviredsalud.com.ar) como
única fuente externa permitida.

Reglas:
    - Se usa SOLO cuando la DB no tiene el dato.
    - Nunca consulta otros sitios.
    - Nunca inventa información.
    - Resultados cacheados con TTL para no golpear el sitio.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

SERVIRE = "https://www.serviredsalud.com.ar"
PLANES_URL = f"{SERVIRE}/planes.php"
CARTILLAS_URL = f"{SERVIRE}/cartillas.php"
NOSOTROS_URL = f"{SERVIRE}/nosotros.php"
CHARSET = "iso-8859-1"
TTL_SEGUNDOS = 3600  # 1 hora


class WebKnowledgeService:
    """
    Consulta la web oficial de SERVIRED como fallback de conocimiento.

    Categorías soportadas:
        planes, cartilla, farmacias, contacto, empresa.
    """

    def __init__(self, timeout: float = 8.0) -> None:
        self._timeout = timeout
        self._cache: dict[str, tuple[float, str]] = {}

    # ─────────────────────────────────────────
    # API pública
    # ─────────────────────────────────────────

    def disponible(self) -> bool:
        """Verifica si la web responde (con timeout corto)."""
        try:
            import requests
            resp = requests.get(PLANES_URL, timeout=3)
            return resp.status_code == 200
        except Exception:
            return False

    def consultar_categoria(self, categoria: str) -> str:
        """
        Consulta contenido de una categoría en la web oficial.

        Args:
            categoria: planes|cartilla|farmacias|empresa|contacto.

        Returns:
            Texto relevante o "" si no se pudo obtener.
        """
        categoria = categoria.strip().lower()

        try:
            if categoria in ("planes", "plan", "coberturas", "beneficios"):
                return self._consultar_planes()
            if categoria in ("cartilla", "prestadores", "red"):
                return self._consultar_cartilla()
            if categoria in ("farmacias", "farmacia"):
                return self._consultar_farmacias()
            if categoria in ("empresa", "nosotros", "informacion"):
                return self._consultar_nosotros()
        except Exception as exc:
            logger.warning("[WEB] Error consultando '%s': %s", categoria, exc)

        return ""

    # ─────────────────────────────────────────
    # Fetch con cache
    # ─────────────────────────────────────────

    def _fetch(self, url: str) -> str:
        """Obtiene y cachea el HTML de una URL de serviredsalud.com.ar."""
        ahora = time.time()
        if url in self._cache:
            ts, html = self._cache[url]
            if ahora - ts < TTL_SEGUNDOS:
                return html

        try:
            import requests
            resp = requests.get(url, timeout=self._timeout, headers={
                "User-Agent": "Mozilla/5.0 (compatible; SofiaBot/1.0)",
            })
            if resp.status_code != 200:
                logger.warning("[WEB] HTTP %s para %s", resp.status_code, url)
                return ""
            resp.encoding = CHARSET
            html = resp.text
        except Exception as exc:
            logger.warning("[WEB] Error fetch %s: %s", url, exc)
            return ""

        self._cache[url] = (ahora, html)
        return html

    # ─────────────────────────────────────────
    # Parsers
    # ─────────────────────────────────────────

    def _texto_principal(self, html: str) -> str:
        """Extrae el texto visible del HTML de serviredsalud.com.ar."""
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")
            for tag in soup(["script", "style", "noscript"]):
                tag.decompose()
            texto = soup.get_text(separator="\n")
            lineas = [
                l.strip() for l in texto.splitlines()
                if l.strip() and len(l.strip()) > 2
            ]
            return "\n".join(lineas)
        except ImportError:
            import re
            return re.sub(r"<[^>]+>", " ", html)

    def _consultar_planes(self) -> str:
        """Extrae los beneficios de planes de la sección Planes."""
        html = self._fetch(PLANES_URL)
        if not html:
            return ""
        texto = self._texto_principal(html)

        partes: list[str] = []
        for plan in ("Plan Gold", "Plan Medimax", "Plan Único"):
            if plan in texto:
                idx = texto.index(plan)
                segmento = texto[idx:idx + 1500]
                # Cortar en la siguiente sección si aparece
                for corte in ("Me Interesa", "Cartilla de prestadores", "¿Tenés alguna duda?"):
                    if corte in segmento:
                        segmento = segmento.split(corte)[0]
                partes.append(segmento.strip())
            elif plan.replace("Plan ", "") in texto:
                idx = texto.index(plan.replace("Plan ", ""))
                segmento = texto[idx:idx + 1200]
                for corte in ("Me Interesa", "Cartilla de prestadores", "¿Tenés alguna duda?"):
                    if corte in segmento:
                        segmento = segmento.split(corte)[0]
                partes.append(segmento.strip())

        if not partes:
            return f"Planes disponibles en {PLANES_URL}.\n{texto[:1200]}"

        return "\n\n".join(partes)[:3000]

    def _consultar_cartilla(self) -> str:
        """Extrae referencia a la cartilla de prestadores."""
        html = self._fetch(CARTILLAS_URL)
        if not html:
            return ""
        texto = self._texto_principal(html)
        if "cartilla" in texto.lower() or "prestador" in texto.lower():
            return (
                "La cartilla de prestadores de SERVIRED cubre la red médica, "
                "farmacéutica, odontológica y ópticas en Córdoba e interior.\n"
                f"Consultá la cartilla completa en: {CARTILLAS_URL}\n"
                + texto[:800]
            )
        return ""

    def _consultar_farmacias(self) -> str:
        """Extrae referencia a la red de farmacias."""
        html = self._fetch(CARTILLAS_URL)
        if not html:
            return ""
        texto = self._texto_principal(html)
        for linea in texto.splitlines():
            if "farmacia" in linea.lower():
                return (
                    "SERVIRED tiene red de farmacias adheridas en Córdoba "
                    "e interior de la provincia.\n"
                    f"Consultá la cartilla de farmacias en: {CARTILLAS_URL}"
                )
        return ""

    def _consultar_nosotros(self) -> str:
        """Extrae información institucional."""
        html = self._fetch(NOSOTROS_URL)
        if not html:
            return ""
        texto = self._texto_principal(html)
        if texto:
            return texto[:1500]
        return ""

    def consultar_planes_sin_parsear(self) -> str:
        """Devuelve el texto completo de la sección Planes (para pruebas)."""
        html = self._fetch(PLANES_URL)
        return self._texto_principal(html) if html else ""
