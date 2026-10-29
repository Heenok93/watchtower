"""Fournisseur Groq Cloud via son API compatible OpenAI."""

from __future__ import annotations

import json
import os
from typing import TypeVar

import requests
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class GroqProviderError(Exception):
    """Erreur de base du fournisseur Groq."""


class GroqConfigurationError(GroqProviderError):
    """Configuration Groq absente ou invalide."""


class GroqResponseError(GroqProviderError):
    """Réponse Groq vide ou non conforme au modèle attendu."""


class GroqProvider:
    """Client minimal Groq, sans dépendance SDK supplémentaire.

    La clé API est lue depuis GROQ_API_KEY et n'est jamais affichée.
    La sortie JSON est validée localement avec le modèle Pydantic fourni.
    """

    def __init__(
        self,
        model: str,
        temperature: float = 0.0,
        api_key: str | None = None,
        base_url: str = "https://api.groq.com/openai/v1",
        timeout: float = 120.0,
    ) -> None:
        self.model = model
        self.temperature = temperature
        self.api_key = api_key or os.getenv("GROQ_API_KEY")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        if not self.api_key:
            raise GroqConfigurationError(
                "GROQ_API_KEY is not set. Add it to the environment before selecting Groq."
            )

    def generate_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        output_model: type[T],
    ) -> T:
        # JSON Object Mode is broadly supported; Pydantic below enforces
        # the application's actual schema even if the model emits bad fields.
        schema = output_model.model_json_schema()
        effective_system_prompt = (
            f"{system_prompt}\n\n"
            "The response must be a single JSON object conforming to this JSON Schema.\n"
            f"JSON Schema:\n{json.dumps(schema, ensure_ascii=False)}"
        )
        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": effective_system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": self.temperature,
                    "response_format": {"type": "json_object"},
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            # Do not include request headers, to avoid leaking the API key.
            detail = str(exc)
            raise GroqProviderError(
                f"Groq API request failed for model '{self.model}': {detail}"
            ) from exc

        try:
            payload = response.json()
            content = payload["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise GroqResponseError(
                "Groq returned a response without valid message content."
            ) from exc

        if not isinstance(content, str) or not content.strip():
            raise GroqResponseError("Groq returned an empty response.")

        try:
            return output_model.model_validate_json(content)
        except ValidationError as exc:
            raise GroqResponseError(
                f"Groq response does not match {output_model.__name__}: {exc}"
            ) from exc

    def get_model_name(self) -> str:
        return self.model

    def get_provider_name(self) -> str:
        return "groq"
