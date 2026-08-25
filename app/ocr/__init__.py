"""
OCR para recibos de sueldo (fotos JPG/PNG).

Usa Tesseract OCR con soporte español para extraer texto de imágenes
y luego parsear los conceptos de obra social ($ montos).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_TESSERACT_LANG = "spa+eng"


def extraer_texto_imagen(ruta: str) -> str:
    """Extrae texto de una imagen usando Tesseract OCR.

    Preprocesa la imagen con Pillow para mejorar la calidad del OCR:
    - Convierte a escala de grises
    - Aumenta contraste
    - Redimensiona si es muy chica
    """
    try:
        import pytesseract
        from PIL import Image, ImageEnhance, ImageFilter
    except ImportError as e:
        logger.warning("[OCR] Librerías no disponibles: %s", e)
        return ""

    try:
        img = Image.open(ruta)
    except Exception as e:
        logger.warning("[OCR] No se pudo abrir imagen %s: %s", ruta, e)
        return ""

    try:
        if img.mode != "L":
            img = img.convert("L")

        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(2.0)

        enhancer = ImageEnhance.Sharpness(img)
        img = enhancer.enhance(2.0)

        if img.width < 1000:
            ratio = 1000 / img.width
            img = img.resize(
                (int(img.width * ratio), int(img.height * ratio)),
                Image.LANCZOS,
            )

        texto = pytesseract.image_to_string(img, lang=_TESSERACT_LANG)
        logger.info(
            "[OCR] Texto extraído de %s (%d chars)",
            Path(ruta).name, len(texto),
        )
        return texto
    except Exception as e:
        logger.warning("[OCR] Error en OCR de %s: %s", ruta, e)
        return ""


def extraer_conceptos_imagen(ruta: str) -> list[float]:
    """Extrae conceptos de obra social de una imagen de recibo.

    1. Extrae texto con OCR
    2. Busca líneas con 'obra social', 'os', 'salud', 'seguro', 'aporte'
    3. De esas líneas extrae montos
    4. Si no encuentra por contexto, extrae todos los montos como fallback
    """
    texto = extraer_texto_imagen(ruta)
    if not texto.strip():
        return []

    montos = _parsear_montos_obra_social(texto)
    if montos:
        logger.info("[OCR] Conceptos de obra social encontrados: %s", montos)
    else:
        logger.info("[OCR] No se encontraron conceptos específicos de obra social")

    return montos


def _parsear_montos_obra_social(texto: str) -> list[float]:
    """Busca montos asociados a conceptos de obra social en el texto OCR.

    Estrategia:
    1. Buscar líneas que contengan keywords de obra social
    2. Extraer montos de esas líneas
    3. Fallback: extraer todos los montos si no se encontraron keywords
    """
    lineas = texto.split("\n")
    montos: list[float] = []
    keywords_obra_social = [
        "obra social", "ob. social", "os", "salud", "seguro",
        "aporte", "descuento", "medico", "prepaga", "cobertura",
    ]

    for linea in lineas:
        linea_lower = linea.lower().strip()
        if any(kw in linea_lower for kw in keywords_obra_social):
            montos_linea = _extraer_montos_de_texto(linea)
            montos.extend(montos_linea)

    if not montos:
        montos = _extraer_montos_de_texto(texto)

    return montos


def _extraer_montos_de_texto(texto: str) -> list[float]:
    """Extrae montos monetarios de un texto."""
    montos: list[float] = []
    patron_dolar = re.findall(r'\$?([\d.,]+)', texto)
    for monto_str in patron_dolar:
        monto_limpio = monto_str.replace(".", "").replace(",", ".")
        try:
            monto = float(monto_limpio)
            if monto >= 100:
                montos.append(monto)
        except ValueError:
            continue

    if not montos:
        patron_numeros = re.findall(r'(\d{3,})', texto)
        for num_str in patron_numeros:
            try:
                num = float(num_str)
                if num >= 100:
                    montos.append(num)
            except ValueError:
                continue

    return montos
