"""Persistence for immutable model predictions and current/history multilabel results."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from models.classification import (
    ConsolidatedArticleClassification,
    ModelPredictionRecord,
)
from storage.database import get_connection


def _json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    )


def save_model_prediction(record: ModelPredictionRecord) -> int:
    """Append a raw model prediction. Existing predictions are never overwritten."""
    prediction = record.prediction
    with get_connection() as conn:
        cursor = conn.execute(
            """INSERT INTO model_predictions (
                article_id, run_id, model_role, provider_name, model_name,
                model_version, prompt_version, prompt_hash, taxonomy_version,
                input_hash, scores_json, labels_json, evidence_json,
                rationales_json, raw_response_json, latency_ms, input_tokens,
                output_tokens, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record.article_id, record.run_id, record.model_role,
                record.provider_name, record.model_name, record.model_version,
                record.prompt_version, record.prompt_hash, record.taxonomy_version,
                record.input_hash, _json(prediction.scores.as_dict()),
                _json(prediction.labels.as_dict()), _json(prediction.evidence),
                _json(prediction.rationales),
                None if prediction.raw_response is None else _json(prediction.raw_response),
                record.latency_ms, record.input_tokens, record.output_tokens,
                record.status, record.created_at.astimezone(timezone.utc).isoformat(),
            ),
        )
        return int(cursor.lastrowid)


def save_consolidated_classification(
    classification: ConsolidatedArticleClassification,
) -> int:
    """Upsert the current classification and append an immutable history revision."""
    now = classification.updated_at.astimezone(timezone.utc).isoformat()
    scores_json = _json(classification.scores.as_dict())
    labels_json = _json(classification.labels.as_dict())
    adjustments_json = _json([
        item.model_dump(mode="json") for item in classification.adjustments
    ])

    with get_connection() as conn:
        current = conn.execute(
            "SELECT revision FROM article_classifications WHERE article_id = ?",
            (classification.article_id,),
        ).fetchone()
        revision = (int(current["revision"]) + 1) if current else 1

        conn.execute(
            """INSERT INTO article_classifications (
                article_id, scores_json, labels_json, adjustments_json,
                taxonomy_version, system1_prediction_id, system2_prediction_id,
                review_status, revision, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(article_id) DO UPDATE SET
                scores_json=excluded.scores_json,
                labels_json=excluded.labels_json,
                adjustments_json=excluded.adjustments_json,
                taxonomy_version=excluded.taxonomy_version,
                system1_prediction_id=excluded.system1_prediction_id,
                system2_prediction_id=excluded.system2_prediction_id,
                review_status=excluded.review_status,
                revision=excluded.revision,
                updated_at=excluded.updated_at""",
            (
                classification.article_id, scores_json, labels_json,
                adjustments_json, classification.taxonomy_version,
                classification.system1_prediction_id,
                classification.system2_prediction_id,
                classification.review_status, revision, now,
            ),
        )
        conn.execute(
            """INSERT INTO article_classification_history (
                article_id, revision, scores_json, labels_json,
                adjustments_json, taxonomy_version, system1_prediction_id,
                system2_prediction_id, review_status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                classification.article_id, revision, scores_json, labels_json,
                adjustments_json, classification.taxonomy_version,
                classification.system1_prediction_id,
                classification.system2_prediction_id,
                classification.review_status, now,
            ),
        )
        return revision


def get_current_classification(article_id: int) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM article_classifications WHERE article_id = ?",
            (article_id,),
        ).fetchone()
    if row is None:
        return None
    result = dict(row)
    for key in ("scores_json", "labels_json", "adjustments_json"):
        result[key.removesuffix("_json")] = json.loads(result.pop(key))
    return result


def list_model_predictions(article_id: int) -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM model_predictions WHERE article_id = ? ORDER BY id",
            (article_id,),
        ).fetchall()
    output = []
    for row in rows:
        item = dict(row)
        for key in ("scores_json", "labels_json", "evidence_json", "rationales_json", "raw_response_json"):
            if item[key] is not None:
                item[key.removesuffix("_json")] = json.loads(item.pop(key))
        output.append(item)
    return output
