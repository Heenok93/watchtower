from typing import TypeVar

import ollama
from pydantic import BaseModel, ValidationError


T = TypeVar("T", bound=BaseModel)


class OllamaProviderError(Exception):
    """Base exception for Ollama provider errors."""


class OllamaConnectionError(OllamaProviderError):
    """Raised when Watchtower cannot communicate with Ollama."""


class OllamaResponseError(OllamaProviderError):
    """Raised when Ollama returns an invalid structured response."""


class OllamaProvider:
    """
    Thin wrapper around the Ollama Python client.

    Responsibilities:
    - communicate with Ollama;
    - request structured JSON output;
    - validate the response with a Pydantic model.

    Scientific classification logic belongs outside this provider.
    """

    def __init__(
        self,
        model: str,
        host: str = "http://localhost:11434",
        temperature: float = 0.0,
    ):
        self.model = model
        self.host = host
        self.temperature = temperature

        self.client = ollama.Client(host=self.host)

    def generate_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        output_model: type[T],
    ) -> T:
        """
        Generate a structured response and validate it
        against the supplied Pydantic model.
        """

        try:
            response = self.client.chat(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": system_prompt,
                    },
                    {
                        "role": "user",
                        "content": user_prompt,
                    },
                ],
                format=output_model.model_json_schema(),
                options={
                    "temperature": self.temperature,
                },
                stream=False,
            )

        except Exception as exc:
            raise OllamaConnectionError(
                f"Failed to communicate with Ollama "
                f"using model '{self.model}': {exc}"
            ) from exc

        try:
            content = response.message.content

        except (AttributeError, KeyError) as exc:
            raise OllamaResponseError(
                "Ollama returned a response without message content."
            ) from exc

        if not content:
            raise OllamaResponseError(
                "Ollama returned an empty response."
            )

        try:
            return output_model.model_validate_json(content)

        except ValidationError as exc:
            raise OllamaResponseError(
                f"Ollama returned a response that does not match "
                f"{output_model.__name__}: {exc}"
            ) from exc

    def get_model_name(self) -> str:
        """
        Return the model configured for this provider.

        Watchtower should persist this value with each LLM result.
        """
        return self.model

    def get_provider_name(self) -> str:
        """
        Return the provider identifier used for persistence.
        """
        return "ollama"