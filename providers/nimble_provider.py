"""Thin adapter for the official Bespoke Labs Nimble local scorer.

This module deliberately does NOT implement Watchtower's ``generate_structured``
interface. Nimble scores a flat schema of typed decisions and returns candidate
scores; it does not generate free-form JSON, explanations, or summaries.

Supported backends in the official repository:
- ``cuda``: ``nimble.scoring.cuda_scorer.CudaCandidateScorer``
- ``mlx``: ``nimble.scoring.parallel_scorer.ParallelScorer``

Create the scorer once and reuse it across articles. See the project README for
model preparation and platform requirements:
https://github.com/bespokelabsai/nimble
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Mapping


Backend = Literal["cuda", "mlx"]


class NimbleProviderError(RuntimeError):
    """Base exception for Nimble provider errors."""


class NimbleConfigurationError(NimbleProviderError):
    """Raised when the local Nimble scorer cannot be configured."""


class NimbleSchemaError(NimbleProviderError):
    """Raised when a decision schema is not supported by Nimble."""


class NimbleResponseError(NimbleProviderError):
    """Raised when the scorer returns a malformed result."""


@dataclass(frozen=True)
class NimbleDecisionResult:
    """Normalized result from one Nimble scoring operation.

    Attributes:
        output: The selected value for each schema field.
        fields: Per-field details returned by Nimble, including candidate
            ``scores`` and, when available, ``logits``.
        model_name: Model identifier recorded in the provider configuration.
        backend: The local inference backend used (``cuda`` or ``mlx``).
    """

    output: dict[str, Any]
    fields: dict[str, dict[str, Any]]
    model_name: str
    backend: str

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return {
            "output": self.output,
            "fields": self.fields,
            "model_name": self.model_name,
            "backend": self.backend,
        }


class NimbleProvider:
    """Thin, lazy-loading wrapper around the official Nimble scorer.

    Args:
        backend: ``"cuda"`` for the official NVIDIA/CUDA scorer or ``"mlx"``
            for the official Apple Silicon/MLX parallel scorer.
        config: Mapping of scorer configuration values, or a path to the JSON
            configuration produced by the official Nimble model preparation
            workflow (for example ``.cache/nimble-model.json``).
        scorer: Optional pre-created scorer. Useful for tests or when the caller
            manages the scorer lifecycle. If supplied, no Nimble import is made.
        model_name: Optional display name to persist with experimental results.

    Notes:
        - The scorer is initialized only once per provider instance.
        - This class intentionally exposes ``score(context, schema)`` rather
          than ``generate_structured(...)``. Keep it separate from the current
          Ollama/Groq article classifier until the experimental result format
          and persistence flow have been designed.
        - The official repository currently documents native inference on
          Apple Silicon (MLX) or Linux with a compatible NVIDIA GPU (CUDA).
          Native Windows support is not documented; WSL2/Linux may be needed.
    """

    def __init__(
        self,
        backend: Backend = "cuda",
        config: Mapping[str, Any] | str | Path | None = None,
        scorer: Any | None = None,
        model_name: str | None = None,
    ) -> None:
        if backend not in ("cuda", "mlx"):
            raise NimbleConfigurationError(
                f"Unsupported backend {backend!r}; expected 'cuda' or 'mlx'."
            )

        self.backend: Backend = backend
        self.config = self._load_config(config)
        self.model_name = (
            model_name
            or str(self.config.get("model_id") or self.config.get("model_name") or "Bespoke-Nimble-9B")
        )

        if scorer is not None:
            self.scorer = scorer
        else:
            self.scorer = self._create_scorer()

    @staticmethod
    def _load_config(
        config: Mapping[str, Any] | str | Path | None,
    ) -> dict[str, Any]:
        if config is None:
            return {}
        if isinstance(config, Mapping):
            return dict(config)

        path = Path(config)
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise NimbleConfigurationError(
                f"Cannot read Nimble config file {str(path)!r}: {exc}"
            ) from exc
        except json.JSONDecodeError as exc:
            raise NimbleConfigurationError(
                f"Nimble config file {str(path)!r} is not valid JSON: {exc}"
            ) from exc

        if not isinstance(loaded, dict):
            raise NimbleConfigurationError(
                "Nimble config must contain a JSON object."
            )
        return loaded

    def _create_scorer(self) -> Any:
        """Import and initialize the selected official backend lazily."""
        try:
            if self.backend == "cuda":
                from nimble.scoring.cuda_scorer import CudaCandidateScorer

                scorer_class = CudaCandidateScorer
            else:
                from nimble.scoring.parallel_scorer import ParallelScorer

                scorer_class = ParallelScorer
        except ImportError as exc:
            raise NimbleConfigurationError(
                "The official Nimble package/backend is not importable in this "
                "Python environment. Install and configure the official Nimble "
                "repository in its supported runtime, or pass a pre-created "
                "scorer to NimbleProvider."
            ) from exc

        try:
            return scorer_class(**self.config)
        except Exception as exc:
            raise NimbleConfigurationError(
                f"Could not initialize Nimble backend {self.backend!r}: "
                f"{type(exc).__name__}: {exc}"
            ) from exc

    @staticmethod
    def validate_schema(schema: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
        """Validate the documented flat enum/boolean schema shape.

        The schema follows the format in Bespoke Labs' official README. Nested
        fields and arbitrary JSON Schema/Pydantic schemas are not supported.
        """
        if not isinstance(schema, Mapping) or not schema:
            raise NimbleSchemaError("Schema must be a non-empty mapping.")

        validated: dict[str, dict[str, Any]] = {}
        for field_name, raw_field in schema.items():
            if not isinstance(field_name, str) or not field_name.strip():
                raise NimbleSchemaError("Every schema field needs a non-empty string name.")
            if not isinstance(raw_field, Mapping):
                raise NimbleSchemaError(f"Schema field {field_name!r} must be an object.")

            field = dict(raw_field)
            field_type = field.get("type")
            if field_type == "boolean":
                if "choices" in field:
                    choices = field["choices"]
                    if choices not in ([False, True], [True, False]):
                        raise NimbleSchemaError(
                            f"Boolean field {field_name!r} choices must be [False, True] or [True, False]."
                        )
            elif field_type == "enum":
                choices = field.get("choices")
                if not isinstance(choices, list) or not 1 <= len(choices) <= 26:
                    raise NimbleSchemaError(
                        f"Enum field {field_name!r} needs a list of 1 to 26 choices."
                    )
                if any(not isinstance(choice, str) or not choice for choice in choices):
                    raise NimbleSchemaError(
                        f"Enum field {field_name!r} choices must be non-empty strings."
                    )
                if len(set(choices)) != len(choices):
                    raise NimbleSchemaError(
                        f"Enum field {field_name!r} choices must be unique."
                    )
                descriptions = field.get("choice_descriptions")
                if descriptions is not None and not isinstance(descriptions, Mapping):
                    raise NimbleSchemaError(
                        f"choice_descriptions for {field_name!r} must be a mapping."
                    )
            else:
                raise NimbleSchemaError(
                    f"Unsupported type {field_type!r} for {field_name!r}; use 'enum' or 'boolean'."
                )

            description = field.get("description")
            if description is not None and not isinstance(description, str):
                raise NimbleSchemaError(
                    f"Description for {field_name!r} must be a string."
                )
            validated[field_name] = field

        return validated

    def score(
        self,
        context: str,
        schema: Mapping[str, Any],
    ) -> NimbleDecisionResult:
        """Score a text context against each field in a flat decision schema."""
        if not isinstance(context, str) or not context.strip():
            raise NimbleSchemaError("Context must be a non-empty string.")

        checked_schema = self.validate_schema(schema)
        try:
            raw_result = self.scorer.score(context, checked_schema)
        except Exception as exc:
            raise NimbleProviderError(
                f"Nimble scoring failed for model {self.model_name!r}: "
                f"{type(exc).__name__}: {exc}"
            ) from exc

        if not isinstance(raw_result, Mapping):
            raise NimbleResponseError("Nimble returned a non-object result.")

        output = raw_result.get("output")
        raw_fields = raw_result.get("fields")
        if not isinstance(output, Mapping) or not isinstance(raw_fields, Mapping):
            raise NimbleResponseError(
                "Nimble result must contain object fields named 'output' and 'fields'."
            )

        expected_names = set(checked_schema)
        if set(output) != expected_names or set(raw_fields) != expected_names:
            raise NimbleResponseError(
                "Nimble result fields do not match the requested schema. "
                f"Expected {sorted(expected_names)}, got output={sorted(output)}, "
                f"fields={sorted(raw_fields)}."
            )

        normalized_fields: dict[str, dict[str, Any]] = {}
        for field_name, schema_field in checked_schema.items():
            details = raw_fields[field_name]
            if not isinstance(details, Mapping):
                raise NimbleResponseError(
                    f"Nimble details for field {field_name!r} are malformed."
                )
            scores = details.get("scores")
            if not isinstance(scores, Mapping) or not scores:
                raise NimbleResponseError(
                    f"Nimble scores for field {field_name!r} are missing or malformed."
                )

            normalized_scores: dict[str, float] = {}
            for choice, score in scores.items():
                try:
                    numeric_score = float(score)
                except (TypeError, ValueError) as exc:
                    raise NimbleResponseError(
                        f"Non-numeric score for {field_name!r}/{choice!r}."
                    ) from exc
                if not math.isfinite(numeric_score):
                    raise NimbleResponseError(
                        f"Non-finite score for {field_name!r}/{choice!r}."
                    )
                normalized_scores[str(choice)] = numeric_score

            if schema_field["type"] == "boolean":
                boolean_choices = schema_field.get("choices", [False, True])
                expected_choices = {str(value).lower() for value in boolean_choices}
            else:
                expected_choices = set(schema_field["choices"])
            if set(normalized_scores) != expected_choices:
                raise NimbleResponseError(
                    f"Score choices for {field_name!r} do not match the schema. "
                    f"Expected {sorted(expected_choices)}, got {sorted(normalized_scores)}."
                )

            normalized_details: dict[str, Any] = {"scores": normalized_scores}
            logits = details.get("logits")
            if isinstance(logits, Mapping):
                normalized_details["logits"] = {
                    str(choice): float(value) for choice, value in logits.items()
                }
            normalized_fields[field_name] = normalized_details

        return NimbleDecisionResult(
            output=dict(output),
            fields=normalized_fields,
            model_name=self.model_name,
            backend=self.backend,
        )

    def get_model_name(self) -> str:
        return self.model_name

    def get_provider_name(self) -> str:
        return "nimble"
