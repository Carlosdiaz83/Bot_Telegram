"""
Servicio de cartillas oficiales SERVIRED.

Resuelve qué PDF de cartilla corresponde a cada plan o categoría de
prestación, para adjuntarlo como respaldo en Telegram.

Los PDFs viven en servired_knowledge/ (copiado por el Dockerfile) y se
resuelven por ruta relativa al root del repo, por lo que funciona igual
en local y en el contenedor de Render.

Uso:
    from app.services.cartilla_service import CartillaService
    cartilla = CartillaService()
    cartilla.plan_a_pdf("medimax_gold")       # ruta del PDF del plan
    cartilla.categoria_pdfs("odontologia")    # [ruta del PDF de odonto]
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class CartillaService:
    """Mapa plan/categoría → PDF de cartilla oficial."""

    REPO_ROOT = Path(__file__).resolve().parent.parent.parent

    # PDF de cartilla por plan (clave normalizada sin espacios).
    PLANES_PDF: dict[str, str] = {
        "gold": "servired_knowledge/planes/PLAN GOLD JULIO 2025.pdf",
        "medimax_gold": "servired_knowledge/planes/PLAN MEDIMAX GOLD COMPLETO JULIO 2025.pdf",
        "medimax": "servired_knowledge/planes/PLAN MEDIMAX COMPLETO JULIO 2025.pdf",
        "medimax_co": "servired_knowledge/planes/PLAN MEDIMAX CO COMPLETO JULIO 2025.pdf",
    }

    # PDF de cartilla por categoría de prestación.
    CATEGORIA_PDF: dict[str, str] = {
        "odontologia": "servired_knowledge/coberturas/SERVIRED ODONTO CBA E INTERIOR.pdf",
        "farmacias": "servired_knowledge/coberturas/SERVIRED FARMACIA CBA E INTERIOR.pdf",
    }

    # Sinónimos para detectar el plan mencionado en un mensaje.
    _PLANES_SINONIMOS: dict[str, str] = {
        "gold": "gold",
        "medimax gold": "medimax_gold",
        "medimax_gold": "medimax_gold",
        "medimax co": "medimax_co",
        "medimax_co": "medimax_co",
        "medimaxco": "medimax_co",
        "medimax": "medimax",
    }

    def __init__(self, root: Path | None = None) -> None:
        self._root = root or self.REPO_ROOT

    # ─────────────────────────────────────────
    # Resolución de rutas
    # ─────────────────────────────────────────

    def _ruta(self, relativa: str) -> Path:
        return self._root / relativa

    def _existe(self, relativa: str) -> bool:
        return self._ruta(relativa).is_file()

    def normalizar_plan(self, plan: str) -> str:
        """Normaliza una clave de plan a la forma sin espacios."""
        if not plan:
            return ""
        p = plan.lower().strip()
        if p.startswith("plan_"):
            p = p[len("plan_"):]
        p = p.replace("-", " ").replace("_", " ")
        p = " ".join(p.split())
        return self._PLANES_SINONIMOS.get(p, p.replace(" ", "_"))

    def _plan_en_mensaje(self, mensaje: str) -> str | None:
        """Detecta el plan mencionado en un mensaje (o None)."""
        if not mensaje:
            return None
        texto = mensaje.lower().strip()
        texto = texto.replace("_", " ")
        texto = " ".join(texto.split())
        # "medimax gold" y "medimax co" antes que "gold"/"medimax"
        # (orden por longitud descendente evita falsos positivos).
        for nombre in sorted(self._PLANES_SINONIMOS, key=len, reverse=True):
            if nombre in texto:
                return self._PLANES_SINONIMOS[nombre]
        return None

    # ─────────────────────────────────────────
    # API pública
    # ─────────────────────────────────────────

    def plan_a_pdf(self, plan: str) -> str | None:
        """
        Retorna la ruta del PDF de cartilla del plan (o None).

        Solo retorna rutas que existen en el filesystem.
        """
        clave = self.normalizar_plan(plan)
        relativa = self.PLANES_PDF.get(clave)
        if not relativa or not self._existe(relativa):
            return None
        return str(self._ruta(relativa))

    def planes_pdfs(self) -> list[str]:
        """Retorna los PDFs de cartilla de todos los planes disponibles."""
        pdfs: list[str] = []
        for clave in self.PLANES_PDF:
            pdf = self.plan_a_pdf(clave)
            if pdf and pdf not in pdfs:
                pdfs.append(pdf)
        return pdfs

    def plan_pdfs(self, plan: str) -> list[str]:
        """Retorna los PDFs de cartilla para un plan específico."""
        pdf = self.plan_a_pdf(plan)
        return [pdf] if pdf else []

    def categoria_pdfs(self, categoria: str, mensaje: str = "") -> list[str]:
        """
        Retorna los PDFs de cartilla correspondientes a una categoría.

        - "planes": PDF del plan mencionado, o todos los planes si es
          una pregunta genérica de planes.
        - "odontologia"/"farmacias": PDF de la cartilla de esa categoría.
        - Otras categorías sin cartilla: lista vacía.
        """
        if categoria == "planes":
            plan = self._plan_en_mensaje(mensaje)
            if plan:
                return self.plan_pdfs(plan)
            return self.planes_pdfs()

        relativa = self.CATEGORIA_PDF.get(categoria)
        if not relativa or not self._existe(relativa):
            return []
        return [str(self._ruta(relativa))]
