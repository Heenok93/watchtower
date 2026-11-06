import json
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from models.classification import CLASSIFICATION_DIMENSIONS
from processing import system2_classifier


def _fake_response(content):
    envelope = {"message": {"content": content}, "prompt_eval_count": 100, "eval_count": 50}
    class FakeResponse:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self): return json.dumps(envelope).encode("utf-8")
    return FakeResponse()


def test_system2_v2_parses_labels_only_and_marks_binary_codes():
    labels = {name: name in {"ai_relevant", "digital_health_ai"} for name in CLASSIFICATION_DIMENSIONS}
    content = json.dumps({"labels": labels})
    with patch.object(system2_classifier.urllib.request, "urlopen",
                      return_value=_fake_response(content)):
        prediction, raw, latency = system2_classifier.classify_with_system2(
            title="Test", abstract="Abstract", model="tomng/lfm2.5-instruct:latest"
        )
    assert prediction.labels.ai_relevant is True
    assert prediction.labels.digital_health_ai is True
    assert prediction.labels.laboratory_ai is False
    assert prediction.scores.ai_relevant == 1.0
    assert raw["score_encoding"] == "binary_decision_code_not_probability"
    assert raw["confidence_ordinal"] == {}
    assert raw["usage"] == {"input_tokens": 100, "output_tokens": 50}
    assert latency >= 0


def test_system2_v2_rejects_confidence_and_rationale_fields():
    labels = {name: False for name in CLASSIFICATION_DIMENSIONS}
    content = json.dumps({"labels": labels, "confidence": {}, "rationales": {}})
    with patch.object(system2_classifier.urllib.request, "urlopen",
                      return_value=_fake_response(content)):
        with pytest.raises(ValidationError):
            system2_classifier.classify_with_system2(
                title="Test", abstract="Abstract", model="tomng/lfm2.5-instruct:latest"
            )
