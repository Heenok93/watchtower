#!/usr/bin/env python3
"""Generate the consolidated article-level Watchtower digest (not legacy topic rows)."""
from __future__ import annotations
import argparse
from datetime import datetime
from pathlib import Path
from storage.database import get_connection, init_database
from models.classification import CLASSIFICATION_DIMENSIONS

LABELS = {
    "ai_relevant": "AI",
    "health_relevant": "Human health",
    "agentic_ai_health": "Agentic AI in health",
    "digital_health_ai": "Digital health AI",
    "clinical_medicine_ai": "Clinical medicine AI",
    "laboratory_ai": "Laboratory AI",
    "epidemics_public_health_ai": "Epidemics / public health AI",
    "drug_development_ai": "Drug development AI",
}

def generate_digest(output: str | Path = "outputs/watchtower_digest.md") -> Path:
    init_database()
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    with get_connection() as conn:
        final_rows = conn.execute("""
            SELECT a.id,a.title,a.abstract,a.publication_date,a.doi,a.source,
                   a.source_url,a.journal,c.labels_json,c.scores_json,c.review_status,
                   c.revision,c.adjustments_json
            FROM article_classifications c
            JOIN articles a ON a.id=c.article_id
            JOIN classification_queue q ON q.article_id=c.article_id AND q.is_eligible=1
            WHERE c.review_status='final'
            ORDER BY COALESCE(a.publication_date,'') DESC,a.id DESC
        """).fetchall()
        review_rows = conn.execute("""
            SELECT a.id,a.title,a.abstract,a.publication_date,a.doi,a.source,
                   a.source_url,a.journal,c.labels_json,c.review_status,c.revision
            FROM article_classifications c
            JOIN articles a ON a.id=c.article_id
            JOIN classification_queue q ON q.article_id=c.article_id AND q.is_eligible=1
            WHERE c.review_status='needs_review'
            ORDER BY COALESCE(a.publication_date,'') DESC,a.id DESC
        """).fetchall()
        pending_rows = conn.execute("""
            SELECT a.id,a.title,a.publication_date,a.source,q.status,
                   q.system2_review_dimensions_json
            FROM classification_queue q JOIN articles a ON a.id=q.article_id
            WHERE q.is_eligible=1 AND q.status NOT IN ('completed','obsolete')
            ORDER BY a.id
        """).fetchall()
    lines = [
        "# Watchtower — Scientific monitoring digest",
        "",
        f"Generated: {datetime.now().astimezone().isoformat(timespec='minutes')}",
        "",
        "> Article-level multilabel classification. Only records with `review_status=final` appear as validated candidates. Model scores are not calibrated probabilities; human verification remains necessary.",
        "",
        f"**Final candidates: {len(final_rows)}** · **Needs review: {len(review_rows)}** · **Pipeline pending: {len(pending_rows)}",
        "",
        "## Final candidates",
        "",
    ]
    if not final_rows:
        lines.append("No final candidates are currently available.")
    for row in final_rows:
        import json
        labels = json.loads(row["labels_json"])
        positives = [LABELS[d] for d in CLASSIFICATION_DIMENSIONS if labels.get(d)]
        title = (row["title"] or "Untitled").strip()
        lines += [f"### {title}", ""]
        meta = []
        if row["publication_date"]: meta.append(str(row["publication_date"]))
        if row["journal"]: meta.append(str(row["journal"]))
        if row["source"]: meta.append(str(row["source"]))
        meta.append(f"Article ID: {row['id']}")
        if row["doi"]: meta.append(f"DOI: {row['doi']}")
        lines += [" · ".join(meta), ""]
        lines += ["**Classification:** " + (", ".join(positives) if positives else "No positive dimension"), ""]
        if row["abstract"]:
            lines += [row["abstract"].strip(), ""]
        url = row["source_url"]
        if url:
            lines += [f"[Source]({url})", ""]
    lines += ["## Human review required", ""]
    if not review_rows:
        lines.append("No consolidated articles are currently marked `needs_review`.")
    for row in review_rows:
        lines += [f"- **{row['title']}** (article {row['id']}) — manual review pending."]
    lines += ["", "## Pipeline pending", ""]
    if not pending_rows:
        lines.append("No eligible queue items are pending.")
    for row in pending_rows:
        dims = row["system2_review_dimensions_json"] or "[]"
        lines += [f"- **{row['title']}** (article {row['id']}) — `{row['status']}`, System 2 dimensions: `{dims}`."]
    lines += ["", "---", "", "Watchtower is a scientific monitoring aid, not a systematic review or an automated assessment of clinical validity.", ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Digest written: {path} ({len(final_rows)} final, {len(review_rows)} needs review, {len(pending_rows)} pending)")
    return path

def cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="outputs/watchtower_digest.md")
    args = parser.parse_args()
    generate_digest(args.output)
    return 0

if __name__ == "__main__":
    raise SystemExit(cli())
