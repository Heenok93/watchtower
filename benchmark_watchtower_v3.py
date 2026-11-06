#!/usr/bin/env python3
"""Watchtower V2 multilabel benchmark (compact SystemOne prompts).

The model directly evaluates eight independent dimensions:
  ai_relevant, health_relevant, agentic_ai_health,
  digital_health_ai, clinical_medicine_ai, laboratory_ai,
  epidemics_public_health_ai, drug_development_ai.

The benchmark then derives two mutually exclusive primary labels and five
secondary labels, while preserving all raw scores/predictions. A consistency
pass promotes AI/Health eligibility when a primary or secondary domain is
positive; this avoids silently discarding a strong domain prediction because
one of the two broad eligibility scores fell below threshold.

Examples:
  uv run python benchmark_watchtower_v3.py --mode systemone --model tev1 \
    --sample watchtower_ground_truth_76.csv \
    --output reports/benchmark_tev1_v3.csv --limit 3

  uv run python benchmark_watchtower_v3.py --mode systemone --model tev1 \
    --sample watchtower_ground_truth_76.csv \
    --output reports/benchmark_tev1_v3.csv

  uv run python benchmark_watchtower_v3.py --mode ollama-chat --model lfm2.5:instruct \
    --sample watchtower_ground_truth_76.csv \
    --output reports/benchmark_lfm25_v3.csv

Use --resume to continue an interrupted run. SQLite is never accessed or modified.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

CHAT_ENDPOINT = "http://localhost:11434/api/chat"
SYSTEMONE_ENDPOINT = "http://localhost:11434/v1/systemone"
TAXONOMY_VERSION = "watchtower_v2_frozen"
PROMPT_VERSION = "watchtower_v2_compact_2026-11-05"

# Direct model outputs. Non-agentic is derived from eligibility + non-agentic status.
MODEL_FIELDS = (
    "ai_relevant",
    "health_relevant",
    "agentic_ai_health",
    "digital_health_ai",
    "clinical_medicine_ai",
    "laboratory_ai",
    "epidemics_public_health_ai",
    "drug_development_ai",
)
SECONDARY_FIELDS = (
    "digital_health_ai",
    "clinical_medicine_ai",
    "laboratory_ai",
    "epidemics_public_health_ai",
    "drug_development_ai",
)
HUMAN_GROUND_TRUTH_FIELDS = (
    "human_ai_label",
    "human_health_label",
    "human_agentic_ai_health",
    "human_non_agentic_ai_health",
    "human_digital_health_ai",
    "human_clinical_medicine_ai",
    "human_laboratory_ai",
    "human_epidemics_public_health_ai",
    "human_drug_development_ai",
)

# Compact, final operational definitions. Each definition is sent once per Noul question.
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
        "belong to Drug Development, not Clinical Medicine, unless a separate patient-level AI application "
        "is studied."
    ),
    "laboratory_ai": (
        "AI for HUMAN diagnostic laboratory tests and methods: diagnostic assay/test development or "
        "validation, laboratory measurement/interpretation, diagnostic microbiology, immunological tests, "
        "clinical pathology, histopathology and diagnostic slide analysis. Immunology qualifies when used "
        "for a concrete human diagnostic/test purpose. Exclude fundamental immunology/omics/molecular "
        "biology without a direct diagnostic application. Clinical trials of new drugs/vaccines are Drug "
        "Development, not Laboratory."
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

COMMON_SYSTEMONE_INSTRUCTIONS = (
    "Judge the article's central objective, methods and contribution using title/abstract only. "
    "Do not infer missing facts or classify from isolated keywords. Apply the definition below."
)
SYSTEMONE_TRUE = "The central topic or contribution clearly meets the definition above."
SYSTEMONE_FALSE = "The definition is not substantively met, or the title/abstract do not support it."

SYSTEM_PROMPT = """You are a scientific-literature classifier for Watchtower V2. Use only the supplied title and abstract.

Return eight independent boolean assessments: AI relevance, human-health relevance, agentic AI, and the five application domains. Assess the article's central objective, methods and contribution, not isolated keywords. Do not infer missing facts.

Important boundaries:
- AI relevance includes substantive AI-focused reviews, implementation, governance, policy and regulatory studies; a new model need not be developed. A mere AI mention, conventional statistics, agent-based simulation alone, mechanistic models, docking or routine bioinformatics is not enough.
- Health means direct HUMAN-health relevance. Exclude veterinary/animal-only work and fundamental omics/genetics/molecular biology/biochemistry/immunology without a direct human diagnostic, therapeutic, drug-development or public-health purpose.
- Agentic requires autonomous multi-step planning and action/tool use, adaptation to results and operational decisions with little/no human intervention. Predictive models, CDSS, ordinary chatbots/LLMs, text generation and static automation are not agentic by themselves.
- Digital Health covers EHR/EMR, Ambient AI, clinical notes, health IT/workflows, telemedicine, mobile health, wearables and connected devices. These belong to Digital Health by default.
- Clinical Medicine requires a direct patient-level diagnostic, prognostic, predictive, treatment-selection or care application. EHR/documentation/workflow alone is not Clinical Medicine. A paper may be both Digital and Clinical only when both contributions are central.
- Laboratory covers human diagnostic tests/assays, diagnostic microbiology/immunology, clinical pathology and histopathology. Fundamental biology without diagnostic purpose is excluded.
- Epidemics/Public Health requires an AI method applied to human epidemiology, outbreak surveillance/forecasting, transmission or population-level public health. Agent-based or mechanistic modelling alone is not AI.
- Drug Development covers AI for therapeutic drug/vaccine discovery and development, toxicity, repurposing, preclinical or clinical evaluation. Trials of new drugs/vaccines belong here when AI is used in their development/evaluation. Developing an AI software tool or clinical prediction model is not Drug Development.

The five domains are multi-label and may overlap. Do not force a domain when evidence is insufficient. Agentic and non-agentic primary labels are derived by the script; do not return non_agentic_ai_health. Return only JSON matching the schema. For every field provide a concise reason and a short exact evidence quotation, or an empty string if none."""

USER_TEMPLATE = """Classify this scientific article for Watchtower V2.

Article ID: {article_id}
Title: {title}
Abstract:
{abstract}

For each of these eight fields return relevant (boolean), confidence (low/medium/high), reason (one concise sentence), and evidence (short exact quote from title/abstract or empty string):
ai_relevant, health_relevant, agentic_ai_health, digital_health_ai, clinical_medicine_ai, laboratory_ai, epidemics_public_health_ai, drug_development_ai.
The five domain labels may overlap. The script derives the mutually exclusive primary labels and applies consistency rules."""


def make_chat_schema() -> dict[str, Any]:
    item = {
        "type": "object",
        "properties": {
            "relevant": {"type": "boolean"},
            "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
            "reason": {"type": "string"},
            "evidence": {"type": "string"},
        },
        "required": ["relevant", "confidence", "reason", "evidence"],
    }
    return {
        "type": "object",
        "properties": {name: item for name in MODEL_FIELDS},
        "required": list(MODEL_FIELDS),
    }


def make_systemone_questions() -> dict[str, Any]:
    questions: dict[str, Any] = {}
    for name in MODEL_FIELDS:
        questions[name] = {
            "type": "noul",
            "instructions": f"{COMMON_SYSTEMONE_INSTRUCTIONS} Definition: {DEFINITIONS[name]}",
            "criteria": {
                "true": SYSTEMONE_TRUE,
                "false": SYSTEMONE_FALSE,
            },
        }
    return questions


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        sample = f.read(16384)
        f.seek(0)
        lines = sample.splitlines()
        header = lines[0] if lines else ""
        delimiter = max([",", ";", "\t", "|"], key=lambda d: header.count(d))
        rows = list(csv.DictReader(f, delimiter=delimiter))
    if not rows:
        raise ValueError(f"No rows found in {path}")
    cleaned = []
    for row in rows:
        cleaned.append({(k or "").strip(): (v or "").strip()
                        for k, v in row.items() if k is not None})
    return cleaned


def parse_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"true", "1", "yes", "y", "oui", "o"}:
        return True
    if text in {"false", "0", "no", "n", "non"}:
        return False
    return None


def validate_ground_truth(rows: list[dict[str, str]], require_labels: bool = True) -> list[str]:
    """Validate binary labels and logical constraints; return warnings/errors."""
    problems: list[str] = []
    present = set(rows[0])
    missing = [c for c in HUMAN_GROUND_TRUTH_FIELDS if c not in present]
    if missing and require_labels:
        raise ValueError("Missing human ground-truth columns: " + ", ".join(missing))
    if missing:
        return ["Ground truth columns not all present; metric comparison will be incomplete: " + ", ".join(missing)]

    for i, row in enumerate(rows, 1):
        vals = {c: parse_bool(row.get(c)) for c in HUMAN_GROUND_TRUTH_FIELDS}
        invalid = [c for c, v in vals.items() if v is None]
        aid = row.get("article_id", f"row {i}")
        if invalid:
            problems.append(f"{aid}: blank/invalid boolean(s): {', '.join(invalid)}")
            continue
        eligible = bool(vals["human_ai_label"] and vals["human_health_label"])
        primaries = [vals["human_agentic_ai_health"], vals["human_non_agentic_ai_health"]]
        secondaries = [vals[f"human_{c}"] for c in SECONDARY_FIELDS]
        if primaries[0] and primaries[1]:
            problems.append(f"{aid}: Agentic and Non-Agentic are both True")
        if not eligible and (any(primaries) or any(secondaries)):
            problems.append(f"{aid}: primary/secondary label True although AI and Health are not both True")
        if eligible and sum(bool(x) for x in primaries) != 1:
            problems.append(f"{aid}: AI=True and Health=True but exactly one primary label is not set")
    return problems


def write_csv_atomic(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, delimiter=";", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        f.flush()
    tmp.replace(path)


def request_json(endpoint: str, payload: dict[str, Any], timeout: int) -> tuple[dict[str, Any], float]:
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Cannot reach {endpoint}: {exc.reason}") from exc
    elapsed = time.perf_counter() - started
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON response: {body[:1500]}") from exc
    return parsed, elapsed


def parse_chat_content(content: str) -> dict[str, Any]:
    try:
        obj = json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, flags=re.S)
        if not match:
            raise RuntimeError(f"Model returned non-JSON content: {content[:1500]}")
        obj = json.loads(match.group(0))
    if not isinstance(obj, dict):
        raise RuntimeError("Model response must be a JSON object.")
    for name in MODEL_FIELDS:
        item = obj.get(name)
        if not isinstance(item, dict) or not isinstance(item.get("relevant"), bool):
            raise RuntimeError(f"Missing/invalid {name}.relevant in model response.")
        if item.get("confidence") not in {"low", "medium", "high"}:
            item["confidence"] = "low"
        if not isinstance(item.get("reason"), str):
            item["reason"] = ""
        if not isinstance(item.get("evidence"), str):
            item["evidence"] = ""
    return obj


def ns_to_seconds(value: Any) -> str:
    try:
        return round(float(value) / 1_000_000_000, 3)
    except (TypeError, ValueError):
        return ""


def derive_labels(raw: dict[str, bool]) -> tuple[dict[str, Any], list[str]]:
    """Apply consistency rules without overwriting raw model outputs.

    Rule: any positive primary-agentic or secondary-domain prediction implies
    both AI relevance and human-health relevance. Raw predictions remain in
    *_prediction; reconciled labels are written to proposed_* columns.
    """
    raw_secondary = {name: bool(raw[name]) for name in SECONDARY_FIELDS}
    has_domain = any(raw_secondary.values())
    has_agentic = bool(raw["agentic_ai_health"])

    final_ai = bool(raw["ai_relevant"] or has_domain or has_agentic)
    final_health = bool(raw["health_relevant"] or has_domain or has_agentic)
    eligible = final_ai and final_health

    final_agentic = bool(eligible and has_agentic)
    final_non_agentic = bool(eligible and not final_agentic)
    final_secondary = {name: bool(eligible and raw_secondary[name]) for name in SECONDARY_FIELDS}

    adjustments: list[str] = []
    if final_ai and not raw["ai_relevant"]:
        triggers = [n for n in SECONDARY_FIELDS if raw_secondary[n]]
        if has_agentic:
            triggers.append("agentic_ai_health")
        adjustments.append("ai_relevant promoted by " + ", ".join(triggers))
    if final_health and not raw["health_relevant"]:
        triggers = [n for n in SECONDARY_FIELDS if raw_secondary[n]]
        if has_agentic:
            triggers.append("agentic_ai_health")
        adjustments.append("health_relevant promoted by " + ", ".join(triggers))

    secondary_labels = [name for name in SECONDARY_FIELDS if final_secondary[name]]
    result: dict[str, Any] = {
        "proposed_ai_label": final_ai,
        "proposed_health_label": final_health,
        "proposed_agentic_ai_health": final_agentic,
        "proposed_non_agentic_ai_health": final_non_agentic,
        "proposed_primary_label": (
            "agentic_ai_health" if final_agentic else
            "non_agentic_ai_health" if final_non_agentic else ""
        ),
        "proposed_secondary_labels": "|".join(secondary_labels),
        "consistency_adjustments": " | ".join(adjustments),
    }
    for name in SECONDARY_FIELDS:
        result[f"proposed_{name}"] = final_secondary[name]
    return result, adjustments


def output_fields(input_fields: list[str]) -> list[str]:
    derived_input_fields = {
        "proposed_ai_label", "proposed_health_label", "proposed_primary_label",
        "proposed_agentic_ai_health", "proposed_non_agentic_ai_health",
        "proposed_digital_health_ai", "proposed_clinical_medicine_ai",
        "proposed_laboratory_ai", "proposed_epidemics_public_health_ai",
        "proposed_drug_development_ai", "proposed_secondary_labels",
        "consistency_adjustments", "review_priority", "review_note",
    }
    fields = [c for c in input_fields if c not in derived_input_fields]
    fields += ["mode", "model", "taxonomy_version", "prompt_version", "systemone_threshold", "seconds"]
    for name in MODEL_FIELDS:
        fields += [
            f"{name}_score", f"{name}_prediction", f"{name}_confidence",
            f"{name}_reason", f"{name}_evidence",
        ]
    fields += [
        "proposed_ai_label", "proposed_health_label",
        "proposed_agentic_ai_health", "proposed_non_agentic_ai_health",
        "proposed_digital_health_ai", "proposed_clinical_medicine_ai",
        "proposed_laboratory_ai", "proposed_epidemics_public_health_ai",
        "proposed_drug_development_ai", "proposed_primary_label",
        "proposed_secondary_labels", "consistency_adjustments",
        "input_tokens", "output_tokens", "load_seconds", "prompt_eval_seconds",
        "eval_seconds", "raw_response", "error",
    ]
    return list(dict.fromkeys(fields))


def is_successful(row: dict[str, str], mode: str, model: str, threshold: float) -> bool:
    if row.get("error", "").strip() or row.get("mode") != mode or row.get("model") != model:
        return False
    if row.get("prompt_version") != PROMPT_VERSION or row.get("taxonomy_version") != TAXONOMY_VERSION:
        return False
    if mode == "systemone" and row.get("systemone_threshold") != str(threshold):
        return False
    for name in MODEL_FIELDS:
        if mode == "systemone":
            if not row.get(f"{name}_score", "").strip():
                return False
        elif row.get(f"{name}_prediction", "").strip().lower() not in {"true", "false"}:
            return False
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode", choices=["systemone", "ollama-chat"], required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--endpoint", default=None)
    ap.add_argument("--sample", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--systemone-threshold", type=float, default=0.5,
                    help="Provisional Noul threshold. Raw scores are always retained.")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-missing-ground-truth", action="store_true",
                    help="Allow missing human-label columns (not recommended for a benchmark).")
    args = ap.parse_args()

    endpoint = args.endpoint or (SYSTEMONE_ENDPOINT if args.mode == "systemone" else CHAT_ENDPOINT)
    try:
        rows = read_csv_rows(args.sample)
        required = {"article_id", "title", "abstract"}
        if not required.issubset(rows[0]):
            raise ValueError("Input CSV must contain: " + ", ".join(sorted(required)))
        ids = [r.get("article_id", "").strip() for r in rows]
        if any(not x for x in ids):
            raise ValueError("Blank article_id found.")
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate article_id values found.")
        gt_issues = validate_ground_truth(rows, require_labels=not args.allow_missing_ground_truth)
        if gt_issues:
            if args.allow_missing_ground_truth and len(gt_issues) == 1 and gt_issues[0].startswith(
                "Ground truth columns not all present;"
            ):
                print("WARNING: " + gt_issues[0], file=sys.stderr)
            else:
                preview = "\n".join("  - " + x for x in gt_issues[:20])
                more = f"\n  ... and {len(gt_issues)-20} more" if len(gt_issues) > 20 else ""
                raise ValueError("Ground-truth validation failed:\n" + preview + more)
    except Exception as exc:
        print(f"Input error: {exc}", file=sys.stderr)
        return 2

    input_fields = list(rows[0].keys())
    work = rows[:args.limit] if args.limit > 0 else rows
    fields = output_fields(input_fields)

    existing: dict[str, dict[str, str]] = {}
    if args.resume and args.output.exists():
        try:
            existing = {r["article_id"]: r for r in read_csv_rows(args.output) if r.get("article_id")}
        except Exception as exc:
            print(f"Could not read output for resume: {exc}", file=sys.stderr)
            return 2

    completed = {
        r["article_id"]: existing[r["article_id"]]
        for r in work
        if r["article_id"] in existing
        and is_successful(existing[r["article_id"]], args.mode, args.model, args.systemone_threshold)
    }

    print(f"Mode: {args.mode} | Model: {args.model} | Endpoint: {endpoint}")
    print(f"Articles: {len(rows)} | To process: {len(work) - len(completed)}")
    print(f"Taxonomy: {TAXONOMY_VERSION} | Prompt: {PROMPT_VERSION}")
    print(f"Output: {args.output.resolve()}")
    if args.mode == "systemone":
        questions = make_systemone_questions()
        q_chars = len(json.dumps(questions, ensure_ascii=False))
        print(f"SystemOne question payload: {q_chars:,} characters (~{q_chars/4:,.0f} tokens, rough estimate)")
        print(f"Noul threshold: {args.systemone_threshold:.3f} (provisional; raw scores retained)")
    if args.dry_run:
        print("DRY RUN: no model calls and no writes.")
        for row in work[:8]:
            print(f"  {row['article_id']} | {row['title'][:100]}")
        return 0

    results: dict[str, dict[str, Any]] = dict(completed)
    for i, row in enumerate(work, 1):
        aid = row["article_id"]
        if aid in results:
            print(f"[{i}/{len(work)}] {aid} — already complete, skipped")
            continue
        print(f"[{i}/{len(work)}] {aid} | {row['title'][:100]}")
        out: dict[str, Any] = {k: row.get(k, "") for k in input_fields if k in fields}
        out.update({
            "mode": args.mode,
            "model": args.model,
            "taxonomy_version": TAXONOMY_VERSION,
            "prompt_version": PROMPT_VERSION,
            "systemone_threshold": args.systemone_threshold if args.mode == "systemone" else "",
            "seconds": "",
            "input_tokens": "",
            "output_tokens": "",
            "load_seconds": "",
            "prompt_eval_seconds": "",
            "eval_seconds": "",
            "raw_response": "",
            "error": "",
            "consistency_adjustments": "",
        })
        for name in MODEL_FIELDS:
            out[f"{name}_score"] = ""
            out[f"{name}_prediction"] = ""
            out[f"{name}_confidence"] = ""
            out[f"{name}_reason"] = ""
            out[f"{name}_evidence"] = ""

        try:
            abstract = (row.get("abstract") or "(No abstract available.)")[:14000]
            if args.mode == "systemone":
                state = f"Title: {row['title']}\n\nAbstract:\n{abstract}"
                payload = {
                    "model": args.model,
                    "state": state,
                    "questions": make_systemone_questions(),
                }
                envelope, elapsed = request_json(endpoint, payload, args.timeout)
                answers = envelope.get("answers") or {}
                raw_values: dict[str, bool] = {}
                for name in MODEL_FIELDS:
                    score = (answers.get(name) or {}).get("noul")
                    if score is None or score == "":
                        raise RuntimeError(f"Missing Noul score for {name}: {json.dumps(envelope)[:1500]}")
                    score_f = float(score)
                    out[f"{name}_score"] = score_f
                    raw_values[name] = score_f >= args.systemone_threshold
                    out[f"{name}_prediction"] = raw_values[name]
                usage = envelope.get("usage") or {}
                out["input_tokens"] = usage.get("input_tokens", "")
                out["output_tokens"] = usage.get("output_tokens", "")
                out["raw_response"] = json.dumps(envelope, ensure_ascii=False)
            else:
                user_prompt = USER_TEMPLATE.format(
                    article_id=row["article_id"], title=row["title"], abstract=abstract
                )
                payload = {
                    "model": args.model,
                    "stream": False,
                    "format": make_chat_schema(),
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    "options": {"temperature": args.temperature},
                }
                envelope, elapsed = request_json(endpoint, payload, args.timeout)
                content = (envelope.get("message") or {}).get("content", "")
                if not content:
                    raise RuntimeError(f"Empty Ollama response: {json.dumps(envelope)[:1500]}")
                parsed = parse_chat_content(content)
                raw_values = {}
                for name in MODEL_FIELDS:
                    item = parsed[name]
                    raw_values[name] = item["relevant"]
                    out[f"{name}_prediction"] = item["relevant"]
                    out[f"{name}_confidence"] = item["confidence"]
                    out[f"{name}_reason"] = item["reason"]
                    out[f"{name}_evidence"] = item["evidence"]
                out["input_tokens"] = envelope.get("prompt_eval_count", "")
                out["output_tokens"] = envelope.get("eval_count", "")
                out["load_seconds"] = ns_to_seconds(envelope.get("load_duration"))
                out["prompt_eval_seconds"] = ns_to_seconds(envelope.get("prompt_eval_duration"))
                out["eval_seconds"] = ns_to_seconds(envelope.get("eval_duration"))
                out["raw_response"] = json.dumps(envelope, ensure_ascii=False)

            derived, adjustments = derive_labels(raw_values)
            out.update(derived)
            out["seconds"] = round(elapsed, 3)
            print(
                f"    raw AI={raw_values['ai_relevant']} Health={raw_values['health_relevant']} "
                f"-> final AI={derived['proposed_ai_label']} Health={derived['proposed_health_label']} "
                f"Primary={derived['proposed_primary_label'] or 'none'} "
                f"Secondary={derived['proposed_secondary_labels'] or 'none'} ({elapsed:.1f}s)"
            )
            if adjustments:
                print("    consistency: " + " | ".join(adjustments))
        except Exception as exc:
            out["error"] = str(exc)
            print(f"    ERROR: {exc}", file=sys.stderr)

        results[aid] = out
        ordered = [results.get(r["article_id"]) or existing.get(r["article_id"]) for r in work]
        ordered = [r for r in ordered if r is not None]
        write_csv_atomic(args.output, ordered, fields)

    errors = sum(bool(r.get("error", "")) for r in results.values())
    success = sum(is_successful(r, args.mode, args.model, args.systemone_threshold) for r in results.values())
    print(f"\nCompleted: {success}/{len(work)} successful | errors: {errors}")
    print(f"Results: {args.output.resolve()}")
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
