"""Fournisseur Groq Cloud avec temporisation et reprise sur erreurs transitoires."""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
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
    """Client Groq minimal, avec débit limité et reprise automatique.

    Variables d'environnement facultatives :
      - GROQ_API_KEY : clé API (obligatoire)
      - WATCHTOWER_GROQ_MIN_INTERVAL_SECONDS : intervalle minimal entre appels (défaut 2 s)
      - WATCHTOWER_GROQ_MAX_RETRIES : reprises après l'appel initial (défaut 5)
      - WATCHTOWER_GROQ_BACKOFF_SECONDS : base du backoff exponentiel (défaut 2 s)

    Les erreurs 429 et les erreurs serveur transitoires sont retentées. Si Groq
    fournit Retry-After ou un en-tête x-ratelimit-reset-*, le délai indiqué est
    respecté. Les erreurs non transitoires ne sont pas retentées.
    """

    RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

    def __init__(
        self,
        model: str,
        temperature: float = 0.0,
        api_key: str | None = None,
        base_url: str = "https://api.groq.com/openai/v1",
        timeout: float = 120.0,
        min_interval: float | None = None,
        max_retries: int | None = None,
        backoff_seconds: float | None = None,
    ) -> None:
        self.model = model
        self.temperature = temperature
        self.api_key = api_key or os.getenv("GROQ_API_KEY")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.min_interval = max(
            0.0,
            float(min_interval if min_interval is not None else os.getenv(
                "WATCHTOWER_GROQ_MIN_INTERVAL_SECONDS", "2"
            )),
        )
        self.max_retries = max(
            0,
            int(max_retries if max_retries is not None else os.getenv(
                "WATCHTOWER_GROQ_MAX_RETRIES", "5"
            )),
        )
        self.backoff_seconds = max(
            0.1,
            float(backoff_seconds if backoff_seconds is not None else os.getenv(
                "WATCHTOWER_GROQ_BACKOFF_SECONDS", "2"
            )),
        )
        self._last_request_started: float | None = None
        if not self.api_key:
            raise GroqConfigurationError(
                "GROQ_API_KEY is not set. Add it to the environment before selecting Groq."
            )

    @staticmethod
    def _parse_duration(value: str | None) -> float | None:
        """Parse seconds, HTTP dates, or durations such as '1m2.5s'."""
        if not value:
            return None
        value = value.strip()
        try:
            return max(0.0, float(value))
        except ValueError:
            pass

        try:
            parsed_date = parsedate_to_datetime(value)
            if parsed_date.tzinfo is None:
                parsed_date = parsed_date.replace(tzinfo=timezone.utc)
            return max(0.0, (parsed_date - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            pass

        matches = list(re.finditer(r"(\d+(?:\.\d+)?)\s*(ms|s|m|h)", value.lower()))
        if not matches:
            return None
        multipliers = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}
        # Reject partial/unrecognized strings instead of guessing.
        if "".join(match.group(0) for match in matches).replace(" ", "") != value.lower().replace(" ", ""):
            return None
        return sum(float(match.group(1)) * multipliers[match.group(2)] for match in matches)

    def _rate_limit_delay(self) -> None:
        if self.min_interval <= 0 or self._last_request_started is None:
            return
        elapsed = time.monotonic() - self._last_request_started
        remaining = self.min_interval - elapsed
        if remaining > 0:
            print(f"Groq: temporisation {remaining:.1f} s avant la requête suivante.")
            time.sleep(remaining)

    def _retry_delay(self, response, attempt: int) -> float:
        candidates = [self.backoff_seconds * (2 ** attempt)]
        headers = getattr(response, "headers", {}) or {}
        for header in (
            "Retry-After",
            "x-ratelimit-reset-requests",
            "x-ratelimit-reset-tokens",
        ):
            parsed = self._parse_duration(headers.get(header))
            if parsed is not None:
                candidates.append(parsed)
        return max(candidates)

    def _post_with_retries(self, payload: dict) -> requests.Response:
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        for attempt in range(self.max_retries + 1):
            self._rate_limit_delay()
            self._last_request_started = time.monotonic()
            try:
                response = requests.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=self.timeout,
                )
            except requests.RequestException as exc:
                if attempt >= self.max_retries:
                    raise GroqProviderError(
                        f"Groq API request failed for model '{self.model}' after "
                        f"{attempt + 1} attempt(s): {type(exc).__name__}: {exc}"
                    ) from exc
                delay = self.backoff_seconds * (2 ** attempt)
                print(
                    f"Groq: erreur réseau ({type(exc).__name__}); "
                    f"nouvelle tentative dans {delay:.1f} s "
                    f"({attempt + 1}/{self.max_retries})."
                )
                time.sleep(delay)
                continue

            if response.status_code in self.RETRYABLE_STATUS_CODES:
                if attempt < self.max_retries:
                    delay = self._retry_delay(response, attempt)
                    print(
                        f"Groq: HTTP {response.status_code}; nouvelle tentative "
                        f"dans {delay:.1f} s ({attempt + 1}/{self.max_retries})."
                    )
                    time.sleep(delay)
                    continue
                body = (getattr(response, "text", "") or "").strip()
                if len(body) > 1000:
                    body = body[:1000] + "…"
                raise GroqProviderError(
                    f"Groq API request failed for model '{self.model}' after "
                    f"{attempt + 1} attempt(s): HTTP {response.status_code}. "
                    f"Response: {body or '(empty response)'}"
                )

            try:
                response.raise_for_status()
            except requests.RequestException as exc:
                body = (getattr(response, "text", "") or "").strip()
                if len(body) > 1000:
                    body = body[:1000] + "…"
                raise GroqProviderError(
                    f"Groq API request failed for model '{self.model}': {exc}. "
                    f"Response: {body or '(empty response)'}"
                ) from exc
            return response

        raise GroqProviderError("Groq retries exhausted unexpectedly.")

    def generate_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        output_model: type[T],
    ) -> T:
        schema = output_model.model_json_schema()
        effective_system_prompt = (
            f"{system_prompt}\n\n"
            "The response must be a single JSON object conforming to this JSON Schema.\n"
            f"JSON Schema:\n{json.dumps(schema, ensure_ascii=False)}"
        )
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": effective_system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.temperature,
            "response_format": {"type": "json_object"},
        }
        response = self._post_with_retries(payload)
        try:
            content = response.json()["choices"][0]["message"]["content"]
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
