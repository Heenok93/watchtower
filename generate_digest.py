"""WATCHTOWER - Markdown digest generator.

Uses classification results already stored in SQLite.
No LLM calls, enrichment calls, or database writes.

Inclusion rules:
1. candidate: included.
2. llm_review with relevant LLM decision: included.
3. llm_review with another LLM decision: excluded.
4. llm_review without an LLM decision: pending, excluded.

Usage:
    python generate_digest.py
    python generate_digest.py --output watchtower_digest.md
    python generate_digest.py --topic automated_reviews
    python generate_digest.py --max-per-topic 20
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from storage.database import get_connection

DEFAULT_OUTPUT = "watchtower_digest.md"
DEFAULT_MAX_PER_TOPIC = 20
ABSTRACT_MAX_LENGTH = 900


def safe_json_loads(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


def clean_text(value: Any) -> str:
    return "" if value is None else " ".join(str(value).split())


def truncate_text(value: Any, max_length: int) -> str:
    text = clean_text(value)
    if len(text) <= max_length:
        return text
    truncated = text[:max_length]
    if " " in truncated:
        truncated = truncated.rsplit(" ", 1)[0]
    return truncated.rstrip() + "..."


def quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def table_columns(connection: sqlite3.Connection, table_name: str) -> set[str]:
    rows = connection.execute(
        f"PRAGMA table_info({quote_identifier(table_name)})"
    ).fetchall()
    # PRAGMA returns the column name at index 1, with or without sqlite3.Row.
    return {row[1] for row in rows}


def choose_column(columns: set[str], candidates: list[str]) -> str | None:
    return next((name for name in candidates if name in columns), None)


def article_field(column: str | None, alias: str) -> str:
    if column is None:
        return f"NULL AS {quote_identifier(alias)}"
    return f"a.{quote_identifier(column)} AS {quote_identifier(alias)}"


def format_authors(value: Any) -> str:
    if value is None:
        return ""
    authors = safe_json_loads(value, value)
    if isinstance(authors, list):
        names = []
        for author in authors:
            if isinstance(author, dict):
                name = clean_text(author.get("name"))
                if not name:
                    name = clean_text(
                        f"{author.get('given', '')} {author.get('family', '')}"
                    )
            else:
                name = clean_text(author)
            if name:
                names.append(name)
        return ", ".join(names[:3]) + (", et al." if len(names) > 3 else "")
    return clean_text(authors)


def format_date(value: Any) -> str:
    text = clean_text(value)
    if not text:
        return ""
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return text


def human_topic_name(topic_id: str) -> str:
    known_names = {
        "automated_reviews": "Automated Evidence Reviews",
        "agentic_epidemiology": "Advanced AI in Epidemiology",
    }
    return known_names.get(topic_id, topic_id.replace("_", " ").strip().title())


def decision_label(row: dict[str, Any]) -> str:
    if row["decision"] == "candidate":
        return "Deterministic candidate"
    if (row["decision"] == "llm_review"
            and clean_text(row.get("llm_decision")).lower() == "relevant"):
        return "LLM validated"
    return clean_text(row.get("decision"))


def article_summary(row: dict[str, Any]) -> str:
    # A candidate is included deterministically, not on a previous LLM decision.
    if row["decision"] == "llm_review":
        summary = clean_text(row.get("llm_summary"))
        if summary:
            return summary
    return (truncate_text(row.get("abstract"), ABSTRACT_MAX_LENGTH)
            or "No abstract or generated summary available.")


def article_url(row: dict[str, Any]) -> str:
    for key in ("url", "source_url"):
        value = clean_text(row.get(key))
        if value.lower().startswith(("https://", "http://")):
            return value
    doi = clean_text(row.get("doi"))
    for prefix in ("https://doi.org/", "http://doi.org/",
                   "https://dx.doi.org/", "http://dx.doi.org/", "doi:"):
        if doi.lower().startswith(prefix):
            doi = doi[len(prefix):].strip()
            break
    return "https://doi.org/" + doi if doi else ""


def escape_markdown(value: str) -> str:
    for character in ("\\", "`", "*", "_", "[", "]", "<", ">"):
        value = value.replace(character, "\\" + character)
    return value


def build_query(connection: sqlite3.Connection,
                topic_id: str | None) -> tuple[str, list[Any]]:
    article_columns = table_columns(connection, "articles")
    result_columns = table_columns(connection, "article_topic_results")
    required_article = {"id"}
    required_result = {"article_id", "topic_id", "decision", "score"}
    missing_article = required_article - article_columns
    missing_result = required_result - result_columns
    if missing_article or missing_result:
        raise RuntimeError(
            "SQLite schema incompatible. Missing columns: "
            f"articles={sorted(missing_article)}, "
            f"article_topic_results={sorted(missing_result)}"
        )

    fields = [f"r.{quote_identifier(name)} AS {quote_identifier(name)}"
              for name in ("article_id", "topic_id", "score", "decision")]
    optional_result = (
        "required_groups_satisfied", "matched_include", "matched_context",
        "matched_priority", "matched_exclude", "matched_required_groups",
        "processed_at", "llm_decision", "llm_confidence", "llm_reason",
        "llm_summary", "llm_provider", "llm_model", "llm_processed_at",
    )
    for name in optional_result:
        fields.append(
            f"r.{quote_identifier(name)} AS {quote_identifier(name)}"
            if name in result_columns else f"NULL AS {quote_identifier(name)}"
        )
    article_candidates = {
        "title": ["title"],
        "source": ["source"],
        "abstract": ["abstract", "summary", "description", "content"],
        "authors": ["authors", "author"],
        "published_at": ["published_at", "published_date", "publication_date", "date"],
        "doi": ["doi"],
        "url": ["url", "article_url", "link"],
        "source_url": ["source_url"],
    }
    for alias, candidates in article_candidates.items():
        fields.append(article_field(choose_column(article_columns, candidates), alias))

    where = "r.decision IN ('candidate', 'llm_review')"
    parameters: list[Any] = []
    if topic_id:
        where += " AND r.topic_id = ?"
        parameters.append(topic_id)
    llm_decision = 'r."llm_decision"' if "llm_decision" in result_columns else "NULL"
    llm_confidence = 'r."llm_confidence"' if "llm_confidence" in result_columns else "NULL"
    query = f"""
        SELECT {', '.join(fields)}
        FROM article_topic_results AS r
        JOIN articles AS a ON a.id = r.article_id
        WHERE {where}
        ORDER BY r.topic_id,
            CASE
                WHEN r.decision = 'candidate' THEN 0
                WHEN LOWER(TRIM({llm_decision})) = 'relevant' THEN 1
                ELSE 2
            END,
            r.score DESC, {llm_confidence} DESC, r.article_id
    """
    return query, parameters


def load_digest_rows(connection: sqlite3.Connection,
                     topic_id: str | None) -> list[dict[str, Any]]:
    query, parameters = build_query(connection, topic_id)
    cursor = connection.execute(query, parameters)
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def classify_rows(rows: list[dict[str, Any]]) -> tuple[
    list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]
]:
    included: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    rejected_by_llm: list[dict[str, Any]] = []
    for row in rows:
        if row["decision"] == "candidate":
            included.append(row)
        elif row["decision"] == "llm_review":
            decision = clean_text(row.get("llm_decision")).lower()
            if not decision:
                pending.append(row)
            elif decision == "relevant":
                included.append(row)
            else:
                rejected_by_llm.append(row)
    return included, pending, rejected_by_llm


def render_article(row: dict[str, Any]) -> list[str]:
    title = escape_markdown(clean_text(row.get("title")) or "Untitled article")
    source = escape_markdown(clean_text(row.get("source")) or "unknown source")
    authors = escape_markdown(format_authors(row.get("authors")))
    published = format_date(row.get("published_at"))
    url = article_url(row)
    # Angle brackets protect parentheses in Markdown link destinations.
    url = url.replace("<", "%3C").replace(">", "%3E").replace(" ", "%20")
    lines = [f"#### [{title}](<{url}>)" if url else f"#### {title}"]
    metadata = [source]
    if published:
        metadata.append(published)
    if authors:
        metadata.append(authors)
    lines.extend(["*" + " \u00b7 ".join(metadata) + "*", "", article_summary(row), ""])
    decision_text = f"**Watchtower:** {decision_label(row)}"
    if row["decision"] == "llm_review" and row.get("llm_confidence") is not None:
        try:
            decision_text += f" \u00b7 confidence {float(row['llm_confidence']):.2f}"
        except (TypeError, ValueError):
            pass
    lines.append(decision_text)
    reason = clean_text(row.get("llm_reason"))
    if row["decision"] == "llm_review" and reason:
        lines.extend(["", f"**Why selected:** {reason}"])
    lines.extend(["", f"`article_id={row['article_id']}` `score={row['score']}`", ""])
    return lines


def build_digest(included: list[dict[str, Any]],
                 pending: list[dict[str, Any]],
                 rejected_by_llm: list[dict[str, Any]],
                 max_per_topic: int) -> str:
    if max_per_topic < 1:
        raise ValueError("max_per_topic must be at least 1")
    included_by_topic: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in included:
        included_by_topic[row["topic_id"]].append(row)
    displayed = sum(min(len(rows), max_per_topic) for rows in included_by_topic.values())
    lines = [
        "# Watchtower Scientific Digest", "",
        "Generated: " + datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "",
        "## Overview", "",
        f"- Selected article-topic pairs: **{len(included)}**",
        f"- Unique selected articles: **{len({row['article_id'] for row in included})}**",
        f"- Displayed article-topic pairs: **{displayed}**",
        f"- Pending LLM review: **{len(pending)}**",
        f"- Excluded after LLM review: **{len(rejected_by_llm)}**", "",
    ]
    if not included:
        lines.extend(["No relevant articles are currently available for this digest.", ""])
    for topic_id in sorted(included_by_topic):
        topic_rows = included_by_topic[topic_id]
        lines.extend(["---", "", "## " + human_topic_name(topic_id), "",
                      f"Selected: **{len(topic_rows)}**", ""])
        counts = Counter(clean_text(row.get("source")) or "unknown" for row in topic_rows)
        summary = ", ".join(f"{escape_markdown(source)}: {count}"
                            for source, count in counts.most_common())
        lines.extend([f"Sources: {summary}", ""])
        shown_rows = topic_rows[:max_per_topic]
        sections = (
            (
                "Candidats du filtre déterministe",
                "Correspondance lexicale forte, sans validation sémantique LLM.",
                [row for row in shown_rows if row["decision"] == "candidate"],
            ),
            (
                "Articles retenus par le LLM",
                "Décision du modèle : relevant. Pertinence à vérifier ; "
                "la confiance du modèle n'est pas une garantie.",
                [row for row in shown_rows if row["decision"] == "llm_review"],
            ),
        )
        for heading, note, section_rows in sections:
            lines.extend([f"### {heading}", "", note, "",
                          f"Affichés : **{len(section_rows)}**", ""])
            if not section_rows:
                lines.extend(["Aucun article affiché dans cette section.", ""])
            for row in section_rows:
                lines.extend(render_article(row))
        hidden = len(topic_rows) - len(shown_rows)
        if hidden:
            lines.extend([f"*{hidden} additional article(s) omitted because of the per-topic limit.*", ""])
    if pending:
        lines.extend(["---", "", "## Pending LLM review", "",
                      "These articles are not included in the digest yet.", ""])
        for row in pending:
            title = escape_markdown(clean_text(row.get("title")) or "Untitled article")
            lines.append(f"- `{row['article_id']}` [{escape_markdown(row['topic_id'])}] {title}")
        lines.append("")
    lines.extend(["---", "", "_Generated automatically by Watchtower._", ""])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a Markdown digest from Watchtower classification results."
    )
    parser.add_argument("--output", default=DEFAULT_OUTPUT,
                        help=f"Output Markdown file (default: {DEFAULT_OUTPUT})")
    parser.add_argument("--topic", default=None,
                        help="Optional topic ID, for example automated_reviews.")
    parser.add_argument("--max-per-topic", type=int, default=DEFAULT_MAX_PER_TOPIC,
                        help="Maximum number of selected articles shown per topic.")
    args = parser.parse_args()
    if args.max_per_topic < 1:
        parser.error("--max-per-topic must be at least 1")
    connection = get_connection()
    try:
        rows = load_digest_rows(connection, args.topic)
    finally:
        connection.close()
    included, pending, rejected_by_llm = classify_rows(rows)
    digest = build_digest(included, pending, rejected_by_llm, args.max_per_topic)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(digest, encoding="utf-8")
    print("=" * 80)
    print("WATCHTOWER DIGEST")
    print("=" * 80)
    if args.topic:
        print(f"Topic: {args.topic}")
    print(f"Selected pairs:     {len(included)}")
    print(f"Unique articles:    {len({row['article_id'] for row in included})}")
    print(f"Pending LLM review: {len(pending)}")
    print(f"Excluded by LLM:    {len(rejected_by_llm)}")
    print(f"Digest written to:  {output_path}")
    print("=" * 80)


if __name__ == "__main__":
    main()
