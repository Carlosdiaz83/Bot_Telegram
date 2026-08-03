"""
Respuesta del bot con adjuntos opcionales.

`RespuestaBot` es un `str` (compatible con toda la API existente que
espera texto) que además puede transportar archivos adjuntos para
enviar por Telegram (ej: cartillas oficiales en PDF como respaldo).

Uso:
    from app.services.respuesta_bot import RespuestaBot
    r = RespuestaBot("texto", archivos_adjuntos=["ruta/a.pdf"])
    r.archivos_adjuntos  # ["ruta/a.pdf"]
    str(r) == "texto"
"""

from __future__ import annotations


class RespuestaBot(str):
    """
    Texto de respuesta que puede incluir archivos adjuntos.

    Se comporta exactamente como un str (subclase), por lo que toda
    comparación, slice o logeo existente sigue funcionando.
    """

    def __new__(
        cls,
        texto: str = "",
        archivos_adjuntos: list[str] | None = None,
    ) -> "RespuestaBot":
        obj = str.__new__(cls, texto)
        obj.archivos_adjuntos: list[str] = list(archivos_adjuntos or [])
        return obj

    def con_adjunto(self, ruta: str) -> "RespuestaBot":
        """Agrega un archivo adjunto (sin duplicados) y retorna self."""
        if ruta and ruta not in self.archivos_adjuntos:
            self.archivos_adjuntos.append(ruta)
        return self

    @property
    def tiene_adjuntos(self) -> bool:
        return bool(self.archivos_adjuntos)
