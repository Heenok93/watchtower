#!/usr/bin/env python3
"""Export one row per article with consolidated labels, scores and provenance."""
from __future__ import annotations
import argparse,csv,json
from pathlib import Path
from storage.database import get_connection,init_database
from models.classification import CLASSIFICATION_DIMENSIONS

def export_classifications(output: str | Path = "outputs/watchtower_classifications.csv",
                           include_needs_review: bool = False) -> Path:
    init_database()
    path=Path(output); path.parent.mkdir(parents=True,exist_ok=True)
    fields=["article_id","title","publication_date","doi","source","source_url","journal",
            "review_status","revision","system1_prediction_id","system2_prediction_id",
            "taxonomy_version","adjustments_json","review_topic_ids_json"]
    fields += [f"{d}_label" for d in CLASSIFICATION_DIMENSIONS]
    fields += [f"{d}_score" for d in CLASSIFICATION_DIMENSIONS]
    with get_connection() as conn:
        sql="""SELECT a.id AS article_id,a.title,a.publication_date,a.doi,a.source,a.source_url,a.journal,
                      c.review_status,c.revision,c.system1_prediction_id,c.system2_prediction_id,
                      c.taxonomy_version,c.adjustments_json,c.labels_json,c.scores_json,
                      q.review_topic_ids_json
               FROM article_classifications c JOIN articles a ON a.id=c.article_id
               JOIN classification_queue q ON q.article_id=a.id AND q.is_eligible=1"""
        if include_needs_review: sql += " WHERE c.review_status IN ('final','needs_review')"
        else: sql += " WHERE c.review_status='final'"
        sql += " ORDER BY a.id"
        rows=conn.execute(sql).fetchall()
    with path.open("w",encoding="utf-8-sig",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=fields,delimiter=";")
        writer.writeheader()
        for row in rows:
            labels=json.loads(row["labels_json"]); scores=json.loads(row["scores_json"])
            item={k:row[k] for k in fields if k in row.keys()}
            item["adjustments_json"]=row["adjustments_json"]
            for d in CLASSIFICATION_DIMENSIONS:
                item[f"{d}_label"]=labels[d]
                item[f"{d}_score"]=scores[d]
            writer.writerow(item)
    print(f"CSV written: {path} ({len(rows)} articles)")
    return path

def cli():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output",default="outputs/watchtower_classifications.csv")
    p.add_argument("--include-needs-review",action="store_true")
    a=p.parse_args(); export_classifications(a.output,a.include_needs_review); return 0
if __name__=="__main__": raise SystemExit(cli())
