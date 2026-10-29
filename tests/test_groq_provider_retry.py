"""Tests hors-ligne du mécanisme de temporisation/reprise Groq."""
import unittest
from unittest.mock import Mock, patch

from models.llm_results import LLMResult
from providers.groq_provider import GroqProvider, GroqProviderError


def success_response():
    response = Mock()
    response.status_code = 200
    response.headers = {}
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "choices": [{"message": {"content": '{"relevant":true,"confidence":0.91,"reason":"Relevant clinical AI study.","summary":"Evaluates clinical AI."}'}}]
    }
    return response


class GroqRetryTests(unittest.TestCase):
    def test_retries_429_then_succeeds(self):
        rate_limited = Mock()
        rate_limited.status_code = 429
        rate_limited.headers = {"Retry-After": "3"}
        rate_limited.text = '{"error":{"message":"rate limit reached"}}'
        success = success_response()
        with patch("providers.groq_provider.requests.post", side_effect=[rate_limited, success]) as post, \
             patch("providers.groq_provider.time.sleep") as sleep:
            provider = GroqProvider(
                model="qwen/qwen3.8-27b", api_key="test-key", min_interval=0,
                max_retries=2, backoff_seconds=1,
            )
            result = provider.generate_structured("System", "User", LLMResult)
        self.assertTrue(result.relevant)
        self.assertEqual(post.call_count, 2)
        sleep.assert_called_once_with(3.0)

    def test_stops_after_retry_limit_with_useful_error(self):
        rate_limited = Mock()
        rate_limited.status_code = 429
        rate_limited.headers = {}
        rate_limited.text = '{"error":{"message":"tokens per minute exceeded"}}'
        with patch("providers.groq_provider.requests.post", return_value=rate_limited), \
             patch("providers.groq_provider.time.sleep"):
            provider = GroqProvider(
                model="qwen/qwen3.8-27b", api_key="test-key", min_interval=0,
                max_retries=1, backoff_seconds=0.1,
            )
            with self.assertRaisesRegex(GroqProviderError, "tokens per minute exceeded"):
                provider.generate_structured("System", "User", LLMResult)

    def test_parses_reset_duration(self):
        self.assertEqual(GroqProvider._parse_duration("1m2.5s"), 62.5)
        self.assertEqual(GroqProvider._parse_duration("250ms"), 0.25)


if __name__ == "__main__":
    unittest.main()
