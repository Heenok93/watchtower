"""LFM2.5 System 2 classifier — prompt V2 (labels-only contract)."""
from __future__ import annotations

from dotenv import load_dotenv
load_dotenv()
import hashlib, json, os, time, urllib.error, urllib.request
from typing import Any
from pydantic import BaseModel, ConfigDict
from models.classification import (
    ArticleClassificationPrediction, ClassificationLabels, ClassificationScores,
    ModelPredictionRecord,
)
from processing.system1_classifier import DEFINITIONS, TAXONOMY_VERSION
from storage.classification_repository import save_model_prediction

SYSTEM2_MODEL = os.getenv("WATCHTOWER_SYSTEM2_MODEL", "tomng/lfm2.5-instruct:latest")
SYSTEM2_HOST = os.getenv("WATCHTOWER_SYSTEM2_HOST", "http://localhost:11434")
SYSTEM2_PROMPT_VERSION = "lfm25_multilabel_review_v2_2026-11-06"
SYSTEM2_PROVIDER = "ollama"


class System2Response(BaseModel):
    """Only the eight Boolean labels are required from the small local model."""
    model_config = ConfigDict(extra="forbid")
    labels: ClassificationLabels


SYSTEM_PROMPT = """You are Watchtower's strict second-stage scientific article classifier.

Classify ONLY from the article title and abstract. Do not use outside knowledge, infer missing details, or classify from isolated keywords. The article must substantively meet a dimension's definition. The eight dimensions are independent multilabel decisions; more than one may be true.

First distinguish an actual AI method from conventional computation. AI includes machine learning, deep learning, NLP, computer vision, language models and reinforcement learning. Integer programming, coordinate-exchange, conventional statistical optimization, mechanistic equations, compartmental models, agent-based simulation, molecular docking and routine bioinformatics are NOT AI by themselves. If the abstract describes only these methods, ai_relevant is false.

Human-health scope is strict. Do not infer a human therapeutic or clinical purpose from a protein, molecule, assay, or biological target alone. Animal-only and fundamental molecular biology without a stated human diagnostic, therapeutic, drug-development or public-health purpose do not qualify as health-relevant.

Evaluate the eight dimensions independently:

- ai_relevant: AI is a substantive method, system, object of evaluation, implementation, governance or policy topic. A conventional statistical/optimization method alone is not AI.
- health_relevant: the central application concerns human disease, patients, clinical care, human public health, or human therapeutic development. Require a stated human-health link.
- agentic_ai_health: require a genuine autonomous closed loop in a human-health setting: the system observes or receives state, plans multiple steps, selects and executes actions or tool calls, evaluates intermediate results, and adapts or replans with limited human intervention. A chatbot, RAG system, LLM reasoning benchmark, predictor, CDSS, risk score, static workflow, automated extraction pipeline, or human-operated recommendation system is NOT agentic. An agent-based simulation is NOT agentic AI in healthcare.
- digital_health_ai: require a central digital health product, service, device, platform, infrastructure or care workflow, such as EHR/EMR integration, ambient documentation, clinical notes, telemedicine, patient-facing tools, wearables or connected health devices. Merely using digital data, software, or an EHR dataset to train a clinical prediction model is not enough.
- clinical_medicine_ai: require a direct patient-level clinical application: diagnosis, imaging interpretation, prognosis, triage, patient-level risk prediction, treatment selection or management. A workflow/documentation tool alone is not Clinical Medicine.
- laboratory_ai: require a human diagnostic laboratory test, assay, clinical pathology, diagnostic microbiology, immunological test, or diagnostic slide analysis. Wearable measurements, blood pressure monitoring, cardiotocography, ordinary imaging, or general clinical monitoring are not laboratory AI.
- epidemics_public_health_ai: require human population-level epidemiology, surveillance, outbreak detection/forecasting, transmission analysis or public-health intervention planning, with an actual AI method. Veterinary-only disease work and agent-based simulation alone do not qualify.
- drug_development_ai: require AI applied to discovery, design, screening, prioritization, optimization, safety, preclinical development or clinical development/evaluation of a therapeutic drug, vaccine, peptide or antibody for a stated human-health purpose. Do NOT include statistical optimization of trial design without AI; selection of existing treatments for an individual patient; tumor-growth simulation without development of a therapeutic candidate; generic protein-binding prediction or DEL virtual screening when no therapeutic purpose is stated; or molecular biology alone.

Contrastive rules:
- Cardiology chatbot or RAG clinical reasoning system: agentic_ai_health=false unless autonomous tool use and action execution are explicitly demonstrated.
- A longitudinal hypertension framework that autonomously plans, acts, follows up and adapts patient-specific care: agentic_ai_health=true when those capabilities are actually described.
- Medical-drone agent-based network simulation: agentic_ai_health=false; simulation agents are not autonomous clinical agents.
- Two-arm clinical-trial design using integer programming and coordinate-exchange only: ai_relevant=false and drug_development_ai=false.
- Molecular fingerprint language model for DEL protein-binder prioritization without a stated therapeutic indication: ai_relevant=true, but drug_development_ai=false and health_relevant=false unless the abstract establishes a human-health application.
- AI design of therapeutic antibodies or therapeutic peptides with an explicit candidate-development purpose: drug_development_ai=true.
- AI-assisted EHR documentation or ambient scribing: digital_health_ai=true; do not automatically assign clinical_medicine_ai or agentic_ai_health.

Do not force logical consistency by copying one label into another. Apply each definition independently. A positive label must be supported by the title/abstract and satisfy its own definition.

Return ONLY valid JSON with exactly one top-level key, labels, and exactly the eight Boolean keys below. Do not return confidence, evidence, rationales, markdown, comments, or additional keys:

{
  "labels": {
    "ai_relevant": false,
    "health_relevant": false,
    "agentic_ai_health": false,
    "digital_health_ai": false,
    "clinical_medicine_ai": false,
    "laboratory_ai": false,
    "epidemics_public_health_ai": false,
    "drug_development_ai": false
  }
}
""" + "\n\nFROZEN DIMENSION DEFINITIONS:\n" + "\n".join(
    f"- {name}: {definition}" for name, definition in DEFINITIONS.items()
)


def _prompt_hash() -> str:
    return hashlib.sha256(SYSTEM_PROMPT.encode("utf-8")).hexdigest()


def classify_with_system2(*, title: str, abstract: str | None, model: str | None = None,
                           host: str | None = None, timeout: int = 300
                           ) -> tuple[ArticleClassificationPrediction, dict[str, Any], int]:
    model_name = model or SYSTEM2_MODEL
    host_name = host or SYSTEM2_HOST
    user_prompt = (f"TITLE:\n{title or '(missing)'}\n\nABSTRACT:\n{abstract or '(missing)'}\n\n"
                   "Classify the article and return only the required labels JSON.")
    endpoint = host_name.rstrip("/")
    if not endpoint.endswith("/api/chat"):
        endpoint += "/api/chat"
    payload = {
        "model": model_name,
        "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                     {"role": "user", "content": user_prompt}],
        "format": System2Response.model_json_schema(),
        "options": {"temperature": 0.0},
        "stream": False,
    }
    request = urllib.request.Request(endpoint, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                                    headers={"Content-Type": "application/json"}, method="POST")
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            envelope = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"System 2 HTTP {exc.code}: {detail[:1500]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"System 2 connection error at {endpoint}: {exc.reason}") from exc
    latency_ms = int((time.perf_counter() - started) * 1000)
    content = (envelope.get("message") or {}).get("content")
    if not content:
        raise ValueError("LFM2.5 returned an empty response")
    parsed = System2Response.model_validate_json(content)
    labels = parsed.labels.as_dict()
    decision_codes = {name: float(value) for name, value in labels.items()}
    raw = {
        "content": content,
        "labels": labels,
        "confidence_ordinal": {},
        "rationales": {},
        "evidence": {},
        "score_encoding": "binary_decision_code_not_probability",
        "model": model_name,
        "prompt_version": SYSTEM2_PROMPT_VERSION,
        "prompt_hash": _prompt_hash(),
        "usage": {"input_tokens": envelope.get("prompt_eval_count"),
                  "output_tokens": envelope.get("eval_count")},
    }
    prediction = ArticleClassificationPrediction(
        scores=ClassificationScores(**decision_codes),
        labels=ClassificationLabels(**labels), evidence={}, rationales={}, raw_response=raw,
    )
    return prediction, raw, latency_ms


def persist_system2_prediction(*, article_id: int, run_id: str,
                               prediction: ArticleClassificationPrediction,
                               raw: dict[str, Any], latency_ms: int,
                               input_hash: str, model_name: str) -> int:
    usage = raw.get("usage", {})
    record = ModelPredictionRecord(
        article_id=article_id, run_id=run_id, model_role="system2",
        provider_name=SYSTEM2_PROVIDER, model_name=model_name,
        prompt_version=SYSTEM2_PROMPT_VERSION, prompt_hash=_prompt_hash(),
        taxonomy_version=TAXONOMY_VERSION, input_hash=input_hash,
        prediction=prediction, latency_ms=latency_ms,
        input_tokens=usage.get("input_tokens"), output_tokens=usage.get("output_tokens"),
        status="completed",
    )
    return save_model_prediction(record)
