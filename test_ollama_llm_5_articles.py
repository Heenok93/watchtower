#!/usr/bin/env python3
"""Benchmark general-purpose Ollama chat models on the same Watchtower articles.

Examples:
  uv run python test_ollama_llm_5_articles.py watchtower_articles.csv --model lfm3
  uv run python test_ollama_llm_5_articles.py watchtower_articles.csv --model phi4-mini --output benchmark_phi4_mini.csv

Isolated benchmark: it does not write to Watchtower's SQLite database.
"""
from __future__ import annotations
import argparse, csv, json, random, re, sys, time, urllib.error, urllib.request
from pathlib import Path
from typing import Any

DEFAULT_ENDPOINT = "http://localhost:11434/api/chat"
DEFAULT_MODEL = "lfm3"
DEFAULT_IDS = ["9877", "5914", "10184", "5620", "6512"]
RANDOM_SEED = 42

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
the requested JSON object. Keep each reason to one concise sentence."""

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

def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        sample = f.read(16384); f.seek(0)
        try: dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except csv.Error: dialect = csv.excel
        rows = list(csv.DictReader(f, dialect=dialect))
    if not rows: raise ValueError(f"No rows found in {path}")
    return [{(k or "").lstrip("\ufeff").strip(): (v or "").strip() for k, v in row.items()} for row in rows]

def field(row: dict[str, str], aliases: list[str]) -> str:
    lowered = {k.lower().strip(): v for k, v in row.items()}
    for alias in aliases:
        if lowered.get(alias.lower()): return lowered[alias.lower()]
    return ""

def article_id(row): return field(row, ["article_id", "id", "article id", "item_id", "paper_id"])
def title_of(row): return field(row, ["title", "article_title", "paper_title", "name"])
def abstract_of(row): return field(row, ["abstract", "summary", "description", "article_abstract"])
def status_of(row): return field(row, ["selection_status", "decision", "status", "filter_status"])

def choose_sample(rows, count, ids):
    valid = [r for r in rows if title_of(r)]
    if ids:
        by_id = {article_id(r): r for r in valid}
        missing = [x for x in ids if x not in by_id]
        if missing:
            raise ValueError("Could not find article IDs in CSV: " + ", ".join(missing) +
                             ". Check the ID column or use --random-sample.")
        return [by_id[x] for x in ids]
    if len(valid) < count: raise ValueError(f"Only {len(valid)} rows have titles; cannot sample {count}.")
    candidates = [r for r in valid if status_of(r).lower() in {"candidate", "deterministic_candidate"}]
    pending = [r for r in valid if "pending" in status_of(r).lower() or "review" in status_of(r).lower()]
    rng = random.Random(RANDOM_SEED); rng.shuffle(candidates); rng.shuffle(pending)
    selected = candidates[:min(3, count, len(candidates))]
    selected += pending[:max(0, min(count-len(selected), 2, len(pending)))]
    remaining = count-len(selected)
    if remaining:
        used = {article_id(r) for r in selected}
        rest = [r for r in valid if article_id(r) not in used]
        rng.shuffle(rest); selected += rest[:remaining]
    return selected[:count]

def call_ollama(endpoint, model, row, timeout, temperature):
    aid, title = article_id(row) or "unknown", title_of(row)
    abstract = (abstract_of(row) or "(No abstract available.)")[:12000]
    user_prompt = USER_TEMPLATE.format(article_id=aid, title=title, abstract=abstract)
    payload = {"model": model, "stream": False, "format": OUTPUT_SCHEMA,
        "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                     {"role": "user", "content": user_prompt}],
        "options": {"temperature": temperature}}
    request = urllib.request.Request(endpoint, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach Ollama at {endpoint}: {exc.reason}. Is Ollama running?") from exc
    elapsed = time.perf_counter()-start
    try: envelope = json.loads(body)
    except json.JSONDecodeError as exc: raise RuntimeError(f"Ollama returned invalid JSON: {body[:500]}") from exc
    content = (envelope.get("message") or {}).get("content", "")
    try: result = json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, flags=re.S)
        if not match: raise RuntimeError(f"Model response was not valid JSON: {content[:1000]}")
        try: result = json.loads(match.group(0))
        except json.JSONDecodeError as exc: raise RuntimeError(f"Could not parse model JSON: {content[:1000]}") from exc
    for category in ("agentic_health_ai", "digital_health_ai"):
        value = result.get(category)
        if not isinstance(value, dict) or not isinstance(value.get("relevant"), bool):
            raise RuntimeError(f"Missing/invalid '{category}.relevant': {content[:1000]}")
        if value.get("confidence") not in {"low", "medium", "high"}: value["confidence"] = ""
        if not isinstance(value.get("reason"), str): value["reason"] = ""
    usage = {"prompt_eval_count": envelope.get("prompt_eval_count", ""),
             "eval_count": envelope.get("eval_count", ""),
             "done_reason": envelope.get("done_reason", ""),
             "load_duration_ns": envelope.get("load_duration", "")}
    return result, elapsed, usage

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--count", type=int, default=5)
    parser.add_argument("--ids", default=",".join(DEFAULT_IDS),
        help="Comma-separated IDs; defaults to same five as the System 1 benchmark")
    parser.add_argument("--random-sample", action="store_true",
        help="Ignore --ids and select a deterministic mixed sample")
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    if not args.csv_path.exists():
        print(f"CSV not found: {args.csv_path}", file=sys.stderr); return 2
    try:
        rows = read_csv_rows(args.csv_path)
        ids = None if args.random_sample else [x.strip() for x in args.ids.split(",") if x.strip()]
        sample = choose_sample(rows, args.count, ids)
    except Exception as exc:
        print(f"Could not prepare sample: {exc}", file=sys.stderr); return 2
    safe_model = re.sub(r"[^a-zA-Z0-9_-]+", "_", args.model)
    output_path = args.output or Path(f"benchmark_{safe_model}.csv")
    print(f"Model: {args.model}\nEndpoint: {args.endpoint}\nArticles: {len(sample)}")
    print("Same five IDs as the System 1 benchmark unless --random-sample is specified.")
    print("One chat request per article; two independent category labels.")
    print("First request may include model-loading time.\n")
    output_rows, durations = [], []
    for i, row in enumerate(sample, 1):
        aid, title = article_id(row), title_of(row)
        print(f"[{i}/{len(sample)}] ID {aid}: {title[:110]}")
        try:
            result, elapsed, usage = call_ollama(args.endpoint, args.model, row, args.timeout, args.temperature)
            durations.append(elapsed)
            a, d = result["agentic_health_ai"], result["digital_health_ai"]
            print(f"    {elapsed:.1f}s | agentic={a['relevant']} ({a['confidence']}) | "
                  f"digital_health={d['relevant']} ({d['confidence']})")
            output_rows.append({
                "article_id": aid, "selection_status": status_of(row), "title": title,
                "seconds": round(elapsed, 2),
                "agentic_health_ai_relevant": a["relevant"], "agentic_health_ai_confidence": a["confidence"],
                "agentic_health_ai_reason": a["reason"], "digital_health_ai_relevant": d["relevant"],
                "digital_health_ai_confidence": d["confidence"], "digital_health_ai_reason": d["reason"],
                "prompt_eval_count": usage["prompt_eval_count"], "eval_count": usage["eval_count"],
                "done_reason": usage["done_reason"], "load_duration_ns": usage["load_duration_ns"], "error": ""})
        except Exception as exc:
            print(f"    ERROR: {exc}")
            output_rows.append({"article_id": aid, "selection_status": status_of(row), "title": title,
                "seconds": "", "agentic_health_ai_relevant": "", "agentic_health_ai_confidence": "",
                "agentic_health_ai_reason": "", "digital_health_ai_relevant": "",
                "digital_health_ai_confidence": "", "digital_health_ai_reason": "",
                "prompt_eval_count": "", "eval_count": "", "done_reason": "", "load_duration_ns": "",
                "error": str(exc)})
    fields = ["article_id", "selection_status", "title", "seconds",
        "agentic_health_ai_relevant", "agentic_health_ai_confidence", "agentic_health_ai_reason",
        "digital_health_ai_relevant", "digital_health_ai_confidence", "digital_health_ai_reason",
        "prompt_eval_count", "eval_count", "done_reason", "load_duration_ns", "error"]
    try:
        with output_path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields); writer.writeheader(); writer.writerows(output_rows)
    except OSError as exc:
        print(f"Could not write output CSV: {exc}", file=sys.stderr); return 2
    print(f"\nResults saved to: {output_path.resolve()}")
    if durations:
        total, mean = sum(durations), sum(durations)/len(durations)
        print(f"Successful requests: {len(durations)}/{len(sample)}")
        print(f"Total inference time: {total:.1f}s ({total/60:.1f} min)")
        print(f"Mean per article: {mean:.1f}s")
        print(f"Estimated 272 articles at this mean: {mean*272/3600:.2f} hours")
    return 0 if len(durations) == len(sample) else 1

if __name__ == "__main__":
    raise SystemExit(main())
