#!/usr/bin/env python3
"""Benchmark Watchtower decision models and Ollama chat LLMs on one fixed 50-article set.

First create the sample once:
  uv run python benchmark_watchtower_50.py --prepare-sample watchtower_articles.csv watchtower_rejected.csv

Then use the same manifest for every model:
  uv run python benchmark_watchtower_50.py --mode ollama-chat --model phi4-mini --output benchmark_phi4_50.csv
  uv run python benchmark_watchtower_50.py --mode systemone --model tev1 --output benchmark_tev1_50.csv

The sample manifest is never changed by a benchmark run. No SQLite writes are performed.
"""

from __future__ import annotations
import argparse
import csv
import json
import random
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_SAMPLE = Path("watchtower_benchmark_50.csv")
CHAT_ENDPOINT = "http://localhost:11434/api/chat"
SYSTEMONE_ENDPOINT = "http://localhost:11434/v1/systemone"
SEED = 20261029

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "agentic_health_ai": {"type": "object", "properties": {
            "relevant": {"type": "boolean"},
            "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
            "reason": {"type": "string"}},
            "required": ["relevant", "confidence", "reason"]},
        "digital_health_ai": {"type": "object", "properties": {
            "relevant": {"type": "boolean"},
            "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
            "reason": {"type": "string"}},
            "required": ["relevant", "confidence", "reason"]},
    },
    "required": ["agentic_health_ai", "digital_health_ai"],
}

SYSTEM_PROMPT = """You are a careful scientific-literature classifier for Watchtower.
Classify the article independently for each category. Multiple categories may be true.

Category definitions:
1. agentic_health_ai:
TRUE only when the article substantively concerns agentic/autonomous AI systems
applied to human health, healthcare, medicine, clinical practice, or medical research.
Look for agents that plan, use tools, coordinate actions, perform multi-step tasks, or
operate with meaningful autonomy. Merely using a large language model, a chatbot,
a conventional classifier, an automated workflow, or the word "agent" in an unrelated
sense is not sufficient. General agent benchmarks are not relevant just because they
include medical examples in a mixed-domain dataset.
Exclude drug discovery, omics, molecular biology, and computational biology unless the
central contribution is an agentic system for healthcare or clinical medicine.

2. digital_health_ai:
TRUE when the article substantively concerns AI applied to digital health or digital
healthcare, such as digital health interventions, telehealth, digital clinical workflows,
patient-facing health applications, remote monitoring, or healthcare information systems.
Do not mark TRUE merely because an article uses AI or an LLM in a medical context.
An article may be relevant to both categories, one category, or neither.

Use only the supplied title and abstract. Do not infer missing facts. If evidence is
insufficient, choose the best-supported boolean and set confidence to low. Return only
the requested JSON object. Keep each reason to one concise sentence grounded in the text."""

USER_TEMPLATE = """Classify this scientific article.

Article ID: {article_id}
Title: {title}

Abstract:
{abstract}

For each category, return:
- relevant: true or false
- confidence: low, medium, or high
- reason: one concise sentence grounded in the title/abstract.
"""

QUESTIONS = {
    "agentic_health_ai": {
        "type": "noul",
        "instructions": (
            "Does this article substantially concern agentic or autonomous "
            "AI applied to human health, healthcare, or medicine?"
        ),
        "criteria": {
            "true": (
                "The article substantially concerns agentic or autonomous AI "
                "applied to human health, healthcare, or medicine."
            ),
            "false": (
                "The article does not substantially concern agentic or "
                "autonomous AI applied to human health, healthcare, or medicine."
            ),
        },
    },
    "digital_health_ai": {
        "type": "noul",
        "instructions": (
            "Does this article substantially concern AI applied to digital "
            "health, digital healthcare, or digital clinical workflows?"
        ),
        "criteria": {
            "true": (
                "The article substantially concerns AI applied to digital "
                "health, digital healthcare, or digital clinical workflows."
            ),
            "false": (
                "The article does not substantially concern AI applied to "
                "digital health, digital healthcare, or digital clinical workflows."
            ),
        },
    },
}

def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        sample = f.read(16384)
        f.seek(0)
        header = sample.splitlines()[0] if sample.splitlines() else ""
        delimiter = max([",", ";", "\t", "|"], key=lambda d: header.count(d))
        dialect = csv.excel
        dialect.delimiter = delimiter
        rows = list(csv.DictReader(f, dialect=dialect))
    if not rows:
        raise ValueError(f"No rows found in {path}")
    return [{(k or "").lstrip("\ufeff").strip(): (v or "").strip() for k, v in r.items() if k is not None and not isinstance(v, list)} for r in rows]

def prepare_sample(articles_path: Path, rejected_path: Path, output: Path, seed: int = SEED) -> None:
    articles, rejected = read_csv_rows(articles_path), read_csv_rows(rejected_path)
    candidates = [r for r in articles if r.get("selection_status") == "deterministic_candidate" and r.get("title")]
    pending = [r for r in articles if r.get("selection_status") == "pending_llm_review" and r.get("title")]
    if len(candidates) < 14 or len(pending) < 18 or len(rejected) < 18:
        raise ValueError("Not enough source rows: need at least 14 candidates, 18 pending, and 18 rejected.")
    rng = random.Random(seed)
    rng.shuffle(pending)
    rng.shuffle(rejected)
    rows = []
    for r in candidates[:14]:
        rows.append(normalize_row(r, "C-", "deterministic_candidate"))
    for r in pending[:18]:
        rows.append(normalize_row(r, "P-", "pending_llm_review"))
    for r in rejected[:18]:
        rows.append(normalize_row(r, "R-", "deterministic_rejected"))
    random.Random(seed + 1).shuffle(rows)
    fields = ["article_id", "original_article_id", "benchmark_source", "selection_status", "topic_id", "title", "abstract"]
    with output.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, delimiter=";")
        writer.writeheader()
        writer.writerows(rows)
    print(f"Created {output.resolve()} with {len(rows)} articles (14 candidates, 18 pending, 18 rejected). Seed={seed}")

def normalize_row(row: dict[str, str], prefix: str, status: str) -> dict[str, str]:
    return {
        "article_id": prefix + row.get("article_id", ""),
        "original_article_id": row.get("article_id", ""),
        "benchmark_source": status,
        "selection_status": status,
        "topic_id": row.get("topic_id", "agentic_health_ai"),
        "title": row.get("title", ""),
        "abstract": row.get("abstract", ""),
    }

def request_json(endpoint: str, payload: dict[str, Any], timeout: int) -> tuple[dict[str, Any], float]:
    request = urllib.request.Request(endpoint, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach endpoint {endpoint}: {exc.reason}") from exc
    elapsed = time.perf_counter() - started
    try:
        envelope = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Endpoint returned invalid JSON: {body[:500]}") from exc
    return envelope, elapsed

def parse_chat_content(content: str) -> dict[str, Any]:
    try:
        result = json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, flags=re.S)
        if not match:
            raise RuntimeError(f"Model response was not valid JSON: {content[:1000]}")
        result = json.loads(match.group(0))
    for category in ("agentic_health_ai", "digital_health_ai"):
        value = result.get(category)
        if not isinstance(value, dict) or not isinstance(value.get("relevant"), bool):
            raise RuntimeError(f"Missing/invalid '{category}.relevant': {content[:1000]}")
        if value.get("confidence") not in {"low", "medium", "high"}:
            value["confidence"] = ""
        if not isinstance(value.get("reason"), str):
            value["reason"] = ""
    return result

def call_chat(endpoint: str, model: str, row: dict[str, str], timeout: int, temperature: float):
    user_prompt = USER_TEMPLATE.format(article_id=row["article_id"], title=row["title"],
        abstract=(row.get("abstract") or "(No abstract available.)")[:12000])
    payload = {"model": model, "stream": False, "format": OUTPUT_SCHEMA,
        "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                     {"role": "user", "content": user_prompt}],
        "options": {"temperature": temperature}}
    envelope, elapsed = request_json(endpoint, payload, timeout)
    result = parse_chat_content((envelope.get("message") or {}).get("content", ""))
    usage = {"prompt_eval_count": envelope.get("prompt_eval_count", ""),
             "eval_count": envelope.get("eval_count", ""),
             "load_duration": envelope.get("load_duration", ""),
             "done_reason": envelope.get("done_reason", "")}
    return result, elapsed, usage

def call_systemone(endpoint: str, model: str, row: dict[str, str], timeout: int):
    state = f"Title: {row['title']}\n\nAbstract: {row.get('abstract') or '(No abstract available.)'}"
    payload = {"model": model, "state": state, "questions": QUESTIONS}
    envelope, elapsed = request_json(endpoint, payload, timeout)
    answers = envelope.get("answers") or {}
    return answers, elapsed, {
        "input_tokens": (envelope.get("usage") or {}).get("input_tokens", ""),
        "raw_response": json.dumps(envelope, ensure_ascii=False),
    }

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["ollama-chat", "systemone"], default="ollama-chat")
    parser.add_argument("--model", default="phi4-mini")
    parser.add_argument("--endpoint", default=None)
    parser.add_argument("--sample", type=Path, default=DEFAULT_SAMPLE)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--timeout", type=int, default=600, help="Per-article timeout, seconds")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--prepare-sample", nargs=2, metavar=("ARTICLES_CSV", "REJECTED_CSV"), type=Path)
    parser.add_argument("--sample-output", type=Path, default=DEFAULT_SAMPLE)
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args()

    if args.prepare_sample:
        try:
            prepare_sample(args.prepare_sample[0], args.prepare_sample[1], args.sample_output, args.seed)
            return 0
        except Exception as exc:
            print(f"Could not prepare sample: {exc}", file=sys.stderr)
            return 2

    endpoint = args.endpoint or (CHAT_ENDPOINT if args.mode == "ollama-chat" else SYSTEMONE_ENDPOINT)
    if not args.sample.exists():
        print(f"Sample CSV not found: {args.sample}. Run --prepare-sample first.", file=sys.stderr)
        return 2
    try:
        rows = read_csv_rows(args.sample)
    except Exception as exc:
        print(f"Could not read sample: {exc}", file=sys.stderr)
        return 2
    required = {"article_id", "title", "abstract", "selection_status"}
    if not required.issubset(rows[0]):
        print(f"Sample CSV needs columns: {', '.join(sorted(required))}", file=sys.stderr)
        return 2

    safe_model = re.sub(r"[^a-zA-Z0-9_-]+", "_", args.model)
    output = args.output or Path(f"benchmark_{safe_model}_50.csv")
    print(f"Mode: {args.mode}\nModel: {args.model}\nEndpoint: {endpoint}\nArticles: {len(rows)}")
    print("Same fixed sample manifest for all models; no database writes.")
    print("First request may include model-loading time. Keep machine conditions similar between runs.\\n")

    output_rows, durations = [], []
    for i, row in enumerate(rows, 1):
        aid, title = row["article_id"], row["title"]
        print(f"[{i}/{len(rows)}] {aid} [{row.get('selection_status','')}]: {title[:100]}")
        base = {"article_id": aid, "original_article_id": row.get("original_article_id", ""),
                "benchmark_source": row.get("benchmark_source", row.get("selection_status", "")),
                "selection_status": row.get("selection_status", ""), "title": title}
        try:
            if args.mode == "ollama-chat":
                result, elapsed, usage = call_chat(endpoint, args.model, row, args.timeout, args.temperature)
                durations.append(elapsed)
                a, d = result["agentic_health_ai"], result["digital_health_ai"]
                base.update({
                    "seconds": round(elapsed, 2),
                    "agentic_health_ai_relevant": a["relevant"],
                    "agentic_health_ai_confidence": a["confidence"],
                    "agentic_health_ai_reason": a["reason"],
                    "digital_health_ai_relevant": d["relevant"],
                    "digital_health_ai_confidence": d["confidence"],
                    "digital_health_ai_reason": d["reason"],
                    "prompt_eval_count": usage["prompt_eval_count"],
                    "eval_count": usage["eval_count"],
                    "load_duration": usage["load_duration"],
                    "done_reason": usage["done_reason"],
                    "agentic_health_ai_score": "",
                    "digital_health_ai_score": "",
                    "input_tokens": "",
                    "error": "",
                })
                print(f"    {elapsed:.1f}s | agentic={a['relevant']} ({a['confidence']}) | digital_health={d['relevant']} ({d['confidence']})")
            else:
                answers, elapsed, usage = call_systemone(endpoint, args.model, row, args.timeout)
                durations.append(elapsed)
                a = (answers.get("agentic_health_ai") or {}).get("noul", "")
                d = (answers.get("digital_health_ai") or {}).get("noul", "")
                base.update({
                    "seconds": round(elapsed, 2),
                    "agentic_health_ai_relevant": "",
                    "agentic_health_ai_confidence": "",
                    "agentic_health_ai_reason": "",
                    "digital_health_ai_relevant": "",
                    "digital_health_ai_confidence": "",
                    "digital_health_ai_reason": "",
                    "prompt_eval_count": "",
                    "eval_count": "",
                    "load_duration": "",
                    "done_reason": "",
                    "agentic_health_ai_score": a,
                    "digital_health_ai_score": d,
                    "input_tokens": usage["input_tokens"],
                    "raw_response": usage["raw_response"],
                    "error": "",
                })
                print(f"    {elapsed:.1f}s | agentic_score={a} | digital_health_score={d}")
        except Exception as exc:
            print(f"    ERROR: {exc}")
            base.update({"seconds": "", "agentic_health_ai_relevant": "", "agentic_health_ai_confidence": "",
                "agentic_health_ai_reason": "", "digital_health_ai_relevant": "", "digital_health_ai_confidence": "",
                "digital_health_ai_reason": "", "prompt_eval_count": "", "eval_count": "", "load_duration": "",
                "done_reason": "", "agentic_health_ai_score": "", "digital_health_ai_score": "",
                "input_tokens": "", "raw_response": "", "error": str(exc)})
        output_rows.append(base)

    fields = ["article_id", "original_article_id", "benchmark_source", "selection_status", "title", "seconds",
        "agentic_health_ai_relevant", "agentic_health_ai_confidence", "agentic_health_ai_reason",
        "digital_health_ai_relevant", "digital_health_ai_confidence", "digital_health_ai_reason",
        "agentic_health_ai_score", "digital_health_ai_score", "input_tokens",
        "prompt_eval_count", "eval_count", "load_duration", "done_reason", "raw_response", "error"]
    try:
        with output.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields, delimiter=";")
            writer.writeheader()
            writer.writerows(output_rows)
    except OSError as exc:
        print(f"Could not write results: {exc}", file=sys.stderr)
        return 2
    print(f"\\nResults saved to: {output.resolve()}")
    print(f"Successful requests: {len(durations)}/{len(rows)}")
    if durations:
        mean = sum(durations) / len(durations)
        print(f"Total inference time: {sum(durations):.1f}s ({sum(durations)/60:.1f} min)")
        print(f"Mean per article: {mean:.1f}s")
        print(f"Estimated 272 articles at this mean: {mean*272/3600:.2f} hours (for 272 articles)")
    return 0 if len(durations) == len(rows) else 1

if __name__ == "__main__":
    raise SystemExit(main())
