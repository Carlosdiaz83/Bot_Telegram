"""
Cliente para proveedores LLM (Groq API, OpenAI, etc.).

Diseñado para ser extensible: si en el futuro se cambia de proveedor,
solo se modifica esta clase.

Uso:
    from app.ai.client import LLMClient
    client = LLMClient(api_key="...", provider="groq")
    respuesta = client.generar_respuesta(mensajes=[...])
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    """Respuesta estructurada del LLM."""

    texto: str
    modelo: str
    tokens_usados: int = 0
    exito: bool = True
    error: str = ""


class LLMClient:
    """
    Cliente unificado para proveedores LLM.

    Actualmente soporta Groq. Diseñado para agregar otros proveedores
    implementando la interfaz _llamada_groq, _llamada_openai, etc.
    """

    PROVIDERS = ("groq", "openai")

    def __init__(
        self,
        api_key: str = "",
        provider: str = "groq",
        model: str = "llama-3.3-70b-versatile",
    ) -> None:
        self._api_key = api_key
        self._provider = provider
        self._model = model
        self._client: Any = None

    def _obtener_cliente(self) -> Any:
        """Inicializa el cliente del proveedor de forma lazy."""
        if self._client is not None:
            return self._client

        if self._provider == "groq":
            try:
                from groq import Groq
                self._client = Groq(api_key=self._api_key)
                return self._client
            except ImportError:
                logger.error(
                    "groq no está instalado. Ejecutá: pip install groq"
                )
                raise
        elif self._provider == "openai":
            try:
                from openai import OpenAI
                self._client = OpenAI(api_key=self._api_key)
                return self._client
            except ImportError:
                logger.error(
                    "openai no está instalado. Ejecutá: pip install openai"
                )
                raise
        else:
            raise ValueError(f"Proveedor no soportado: {self._provider}")

    def generar_respuesta(
        self,
        mensajes: list[dict[str, str]],
        temperatura: float = 0.7,
        max_tokens: int = 500,
    ) -> LLMResponse:
        """
        Genera una respuesta usando el LLM configurado.

        Args:
            mensajes: Lista de mensajes en formato OpenAI
                      [{"role": "system", "content": "..."},
                       {"role": "user", "content": "..."}]
            temperatura: Creatividad (0.0 = preciso, 1.0 = creativo).
            max_tokens: Máximo de tokens en la respuesta.

        Returns:
            LLMResponse con el texto generado.
        """
        if not self._api_key:
            return LLMResponse(
                texto="",
                modelo=self._model,
                exito=False,
                error="API key no configurada",
            )

        try:
            cliente = self._obtener_cliente()

            if self._provider == "groq":
                return self._llamada_groq(cliente, mensajes, temperatura, max_tokens)
            elif self._provider == "openai":
                return self._llamada_openai(cliente, mensajes, temperatura, max_tokens)
            else:
                return LLMResponse(
                    texto="",
                    modelo=self._model,
                    exito=False,
                    error=f"Proveedor no implementado: {self._provider}",
                )
        except Exception as e:
            logger.error("Error en llamada LLM: %s", e)
            return LLMResponse(
                texto="",
                modelo=self._model,
                exito=False,
                error=str(e),
            )

    def _llamada_groq(
        self,
        cliente: Any,
        mensajes: list[dict[str, str]],
        temperatura: float,
        max_tokens: int,
    ) -> LLMResponse:
        """Llamada específica a Groq API."""
        respuesta = cliente.chat.completions.create(
            model=self._model,
            messages=mensajes,
            temperature=temperatura,
            max_tokens=max_tokens,
        )
        texto = respuesta.choices[0].message.content or ""
        tokens = getattr(respuesta.usage, "total_tokens", 0) if respuesta.usage else 0

        return LLMResponse(
            texto=texto.strip(),
            modelo=self._model,
            tokens_usados=tokens,
            exito=True,
        )

    def _llamada_openai(
        self,
        cliente: Any,
        mensajes: list[dict[str, str]],
        temperatura: float,
        max_tokens: int,
    ) -> LLMResponse:
        """Llamada específica a OpenAI API."""
        respuesta = cliente.chat.completions.create(
            model=self._model,
            messages=mensajes,
            temperature=temperatura,
            max_tokens=max_tokens,
        )
        texto = respuesta.choices[0].message.content or ""
        tokens = getattr(respuesta.usage, "total_tokens", 0) if respuesta.usage else 0

        return LLMResponse(
            texto=texto.strip(),
            modelo=self._model,
            tokens_usados=tokens,
            exito=True,
        )
