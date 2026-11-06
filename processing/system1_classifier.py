"""JEV System 1 article-level multilabel classifier via Ollama SystemOne Noul."""
from __future__ import annotations

from dotenv import load_dotenv
load_dotenv()

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

from models.classification import (
    ArticleClassificationPrediction,
    ClassificationLabels,
    ClassificationScores,
    ConsolidatedArticleClassification,
    ModelPredictionRecord,
)
from storage.classification_repository import save_consolidated_classification, save_model_prediction

TAXONOMY_VERSION = "watchtower_v2_frozen"
PROMPT_VERSION = "watchtower_v2_compact_2026-11-05"
DEFAULT_MODEL = "jev08:latest"
DEFAULT_ENDPOINT = "http://localhost:11434/v1/systemone"
DEFAULT_THRESHOLD = 0.5  # operational threshold; calibrate against the 76-article reference set

DEFINITIONS = {
    "ai_relevant": (
        "The article substantively studies, discusses, develops, evaluates, validates, implements, "
        "regulates or applies an AI system/method as a central topic or contribution. Include AI-focused "
        "reviews, implementation, governance, policy and regulatory studies, even when the paper does "
        "not develop a new model. AI includes explicitly identified ML/DL, NLP, computer vision, "
        "reinforcement learning and generative/LLM methods. Exclude incidental AI mentions, conventional "
        "statistics, mechanistic/compartmental models, agent-based simulation alone, molecular dynamics, "
        "docking and routine bioinformatics unless an actual AI method is identified."
    ),
    "health_relevant": (
        "The central topic has a direct application to HUMAN health: human disease, patients, clinical "
        "care, diagnosis, prevention, treatment, human epidemiology/public health, health services, or "
        "therapeutic drug/vaccine development. Exclude veterinary-only/animal-only studies and animal "
        "models without a stated human-health application. Exclude fundamental omics, genetics, molecular "
        "biology, biochemistry or immunology without a direct human diagnostic, therapeutic, drug-development "
        "or public-health purpose. A non-human vector/intermediate-host study qualifies only when its stated "
        "aim is to reduce transmission of a human disease."
    ),
    "agentic_ai_health": (
        "The article concerns AI applied to HUMAN health that autonomously plans multi-step tasks, selects "
        "and executes actions or uses tools, adapts actions to intermediate results, and makes operational "
        "decisions with little/no human intervention. A predictive model, clinical decision-support system "
        "(CDSS), risk score, diagnostic classifier, ordinary chatbot/LLM, text generator, static workflow "
        "automation, or the words 'agent'/'multi-agent' alone are NOT sufficient; explicit autonomous "
        "planning and action are required."
    ),
    "digital_health_ai": (
        "AI whose central application is a digital health technology, service, device or workflow: EHR/EMR, "
        "Ambient AI, clinical notes/documentation, health information systems, hospital workflow, "
        "telemedicine, mobile health, wearables, connected/digital health devices and patient-facing digital "
        "tools. EHR, ambient scribing, clinical notes, wearables and connected devices are Digital Health "
        "by default. Do not assign Digital Health merely because a clinical model uses digital data/software. "
        "Add Clinical Medicine only when a distinct direct patient-level clinical application is also central."
    ),
    "clinical_medicine_ai": (
        "AI applied directly to the HUMAN patient or their clinical management: medical imaging for patient "
        "assessment/diagnosis, direct diagnosis, prognosis, patient-level risk prediction, clinical decision, "
        "precision medicine, treatment selection, personalised treatment or direct care. EHR/documentation, "
        "ambient scribing and workflow-only tools are Digital Health, not Clinical Medicine, unless a distinct "
        "patient-level diagnostic/prognostic/treatment application is central. Trials of new drugs/vaccines "
        "belong to Drug Development, not Clinical Medicine, unless a separate patient-level AI application is studied."
    ),
    "laboratory_ai": (
        "AI for HUMAN diagnostic laboratory tests and methods: diagnostic assay/test development or "
        "validation, laboratory measurement/interpretation, diagnostic microbiology, immunological tests, "
        "clinical pathology, histopathology and diagnostic slide analysis. Immunology qualifies when used "
        "for a concrete human diagnostic/test purpose. Exclude fundamental immunology/omics/molecular "
        "biology without a direct diagnostic application. Clinical trials of new drugs/vaccines are Drug Development, not Laboratory."
    ),
    "epidemics_public_health_ai": (
        "AI for HUMAN epidemiology and public health: human disease surveillance, outbreak detection or "
        "forecasting, transmission prediction/modelling, population-level risk, public-health monitoring "
        "or intervention planning. An actual AI/ML method is required; conventional statistics, mechanistic, "
        "compartmental or agent-based models alone do not qualify. Exclude veterinary-only outbreaks."
    ),
    "drug_development_ai": (
        "AI applied to discovery, design, screening, prioritisation, repurposing, optimisation, pharmacology, "
        "toxicity/safety prediction, preclinical development or clinical development/evaluation of therapeutic "
        "drugs and vaccines for human health. Clinical trials of new drugs/vaccines belong here when AI is used "
        "in their development or evaluation. Developing an AI software system, clinical prediction model or "
        "healthcare application is NOT Drug Development. Exclude molecules without a human therapeutic "
        "purpose and basic omics/computational chemistry without an explicit drug-development aim."
    ),
}
DIMENSIONS = tuple(DEFINITIONS)
COMMON_INSTRUCTIONS = (
    "Judge the article's central objective, methods and contribution using title/abstract only. "
    "Do not infer missing facts or classify from isolated keywords. Apply the definition below."
)
TRUE_CRITERION = "The central topic or contribution clearly meets the definition above."
FALSE_CRITERION = "The definition is not substantively met, or the title/abstract do not support it."
SYSTEM1_PROMPT_HASH = hashlib.sha256(
    json.dumps({"version": PROMPT_VERSION, "definitions": DEFINITIONS,
               "common": COMMON_INSTRUCTIONS}, sort_keys=True).encode("utf-8")
).hexdigest()


def build_questions() -> dict[str, Any]:
    return {
        name: {
            "type": "noul",
            "instructions": f"{COMMON_INSTRUCTIONS} Definition: {definition}",
            "criteria": {"true": TRUE_CRITERION, "false": FALSE_CRITERION},
        }
        for name, definition in DEFINITIONS.items()
    }


def classify_with_system1(
    *, article_id: int, title: str, abstract: str | None,
    model: str | None = None, endpoint: str | None = None,
    timeout: int = 180, threshold: float | None = None,
) -> tuple[ArticleClassificationPrediction, dict[str, Any], int]:
    """Return raw Noul scores and thresholded labels; no consistency repair."""
    model = model or os.getenv("WATCHTOWER_SYSTEM1_MODEL", DEFAULT_MODEL)
    endpoint = endpoint or os.getenv("WATCHTOWER_SYSTEM1_ENDPOINT", DEFAULT_ENDPOINT)
    threshold = float(os.getenv("WATCHTOWER_SYSTEM1_THRESHOLD", DEFAULT_THRESHOLD)) if threshold is None else threshold
    if not 0 <= threshold <= 1:
        raise ValueError("System 1 threshold must be between 0 and 1.")

    state = (
        f"Title: {title or '(No title available.)'}\n\n"
        f"Abstract: {abstract or '(No abstract available.)'}"
    )
    payload = {"model": model, "state": state, "questions": build_questions()}
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            envelope = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"System 1 HTTP {exc.code}: {detail[:1500]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"System 1 connection error at {endpoint}: {exc.reason}") from exc
    elapsed_ms = int((time.perf_counter() - started) * 1000)

    answers = envelope.get("answers") or {}
    scores: dict[str, float] = {}
    for dimension in DIMENSIONS:
        value = (answers.get(dimension) or {}).get("noul")
        if value is None:
            raise ValueError(f"System 1 response has no Noul score for {dimension}.")
        score = float(value)
        if not 0.0 <= score <= 1.0:
            raise ValueError(f"Invalid Noul score for {dimension}: {score}")
        scores[dimension] = score

    labels = {name: score >= threshold for name, score in scores.items()}
    prediction = ArticleClassificationPrediction(
        scores=ClassificationScores(**scores),
        labels=ClassificationLabels(**labels),
        evidence={}, rationales={}, raw_response=envelope,
    )
    return prediction, envelope, elapsed_ms


def persist_system1_prediction(
    *, article_id: int, run_id: str, prediction: ArticleClassificationPrediction,
    envelope: dict[str, Any], elapsed_ms: int, input_hash: str,
    model_name: str,
) -> int:
    usage = envelope.get("usage") or {}
    record = ModelPredictionRecord(
        article_id=article_id, run_id=run_id, model_role="system1",
        provider_name="ollama_systemone", model_name=model_name,
        prompt_version=PROMPT_VERSION, prompt_hash=SYSTEM1_PROMPT_HASH,
        taxonomy_version=TAXONOMY_VERSION, input_hash=input_hash,
        prediction=prediction, latency_ms=elapsed_ms,
        input_tokens=usage.get("input_tokens"),
        output_tokens=usage.get("output_tokens"), status="completed",
    )
    prediction_id = save_model_prediction(record)
    save_consolidated_classification(ConsolidatedArticleClassification(
        article_id=article_id, scores=prediction.scores, labels=prediction.labels,
        adjustments=[], taxonomy_version=TAXONOMY_VERSION,
        system1_prediction_id=prediction_id, review_status="system1",
    ))
    return prediction_id
