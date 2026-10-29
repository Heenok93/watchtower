"""Smoke tests hors-ligne pour GroqProvider (aucun appel réseau réel)."""
import os
import unittest
from unittest.mock import Mock, patch

from models.llm_results import LLMResult
from providers.groq_provider import GroqConfigurationError, GroqProvider


class GroqProviderSmokeTests(unittest.TestCase):
    def test_parses_and_validates_structured_json(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "choices": [{"message": {"content": '{"relevant":true,"confidence":0.91,"reason":"The abstract evaluates an AI tool in clinical care.","summary":"The study evaluates an AI tool in clinical care."}'}}]
        }
        with patch("providers.groq_provider.requests.post", return_value=response) as post:
            provider = GroqProvider(model="qwen/qwen3.8-27b", api_key="test-key")
            result = provider.generate_structured(
                system_prompt="Return JSON.",
                user_prompt="Classify this article.",
                output_model=LLMResult,
            )
        self.assertIsInstance(result, LLMResult)
        self.assertTrue(result.relevant)
        self.assertEqual(provider.get_provider_name(), "groq")
        self.assertEqual(provider.get_model_name(), "qwen/qwen3.8-27b")
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer test-key")
        self.assertEqual(post.call_args.kwargs["json"]["response_format"], {"type": "json_object"})

    def test_requires_api_key(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(GroqConfigurationError):
                GroqProvider(model="qwen/qwen3.8-27b")


if __name__ == "__main__":
    unittest.main()
