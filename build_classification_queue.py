#!/usr/bin/env python3
"""Build the deduplicated article-level union of all current llm_review decisions."""
from __future__ import annotations

import argparse
from pathlib import Path

from run_filter import discover_profile_files, load_profiles
from storage.classification_queue_repository import build_classification_queue
from storage.database import get_connection, init_database
from processing.system1_classifier import PROMPT_VERSION, TAXONOMY_VERSION


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Count the union without persisting it.")
    args = parser.parse_args()

    init_database()
    profiles = load_profiles(discover_profile_files())
    topic_ids = [profile.id for _, profile, _ in profiles]

    if args.dry_run:
        placeholders = ",".join("?" for _ in topic_ids)
        with get_connection() as conn:
            row = conn.execute(
                f"""SELECT COUNT(DISTINCT article_id) AS n
                    FROM article_topic_results
                    WHERE decision = 'llm_review' AND topic_id IN ({placeholders})""",
                topic_ids,
            ).fetchone()
        print(f"Profiles: {len(topic_ids)}")
        print(f"Unique articles in llm_review union: {int(row['n'])}")
        return 0

    counts = build_classification_queue(
        taxonomy_version=TAXONOMY_VERSION,
        prompt_version=PROMPT_VERSION,
        topic_ids=topic_ids,
    )
    print("WATCHTOWER — CLASSIFICATION QUEUE")
    print(f"Profiles included:          {len(topic_ids)}")
    for key, value in counts.items():
        print(f"{key.replace('_', ' ').title():<28}{value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
