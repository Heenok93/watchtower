#!/usr/bin/env python3
"""Incremental deterministic filtering for all independent Watchtower topic profiles.

Profiles are discovered recursively under config/topics. A result is recalculated
only when its profile hash, filter-engine version, or searchable article text changes.
The database is never reset by this script.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from contextlib import closing
from pathlib import Path
from typing import Any

import yaml

from models.schemas import Article, TopicProfile
from processing.deterministic_filter import (
    filter_article, article_search_text, compile_profile_matcher,
)
from storage.database import get_connection, init_database
from storage.topic_result_repository import (
    count_topic_results,
    get_topic_result_metadata,
    save_topic_results_batch,
)

BASE_DIR = Path(__file__).resolve().parent
TOPICS_DIR = BASE_DIR / "config" / "topics"
FILTER_ENGINE_VERSION = "2.2.0"


def sha256_json(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def discover_profile_files() -> list[Path]:
    """Discover YAML profiles recursively, including subcategories/."""
    if not TOPICS_DIR.is_dir():
        raise FileNotFoundError(f"Topics directory not found: {TOPICS_DIR}")
    paths = sorted(path for path in TOPICS_DIR.rglob("*.yaml") if path.is_file())
    if not paths:
        raise RuntimeError(f"No topic profiles found in {TOPICS_DIR}")
    return paths


def load_profiles(paths: list[Path]) -> list[tuple[Path, TopicProfile, str]]:
    """Load profiles, validate schemas, and reject duplicate topic IDs."""
    loaded = []
    seen: dict[str, Path] = {}
    for path in paths:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"Invalid or empty YAML profile: {path}")
        profile = TopicProfile.model_validate(data)
        if profile.id in seen:
            raise ValueError(
                f"Duplicate topic id '{profile.id}' in {seen[profile.id]} and {path}"
            )
        seen[profile.id] = path
        profile_hash = sha256_json(profile.model_dump(mode="json"))
        loaded.append((path, profile, profile_hash))
    return loaded


def load_articles() -> list[tuple[int, Article]]:
    """Load all collected articles; only title/abstract affect the text filter."""
    with closing(get_connection()) as conn:
        # The deterministic filter currently reads only title and abstract.
        # Avoid fetching/decoding metadata that cannot affect its decision.
        rows = conn.execute(
            """
            SELECT id, title, abstract
            FROM articles
            ORDER BY id
            """
        ).fetchall()

    articles = []
    for row in rows:
        # This is a deliberately partial Article instance. `filter_article`
        # and `article_search_text` only access title/abstract. model_construct
        # avoids expensive validation/parsing of dates and metadata for every
        # row in a large corpus. Do not pass these partial instances to other
        # pipeline stages that require fully validated Article objects.
        article = Article.model_construct(
            title=row["title"] or "",
            abstract=row["abstract"],
        )
        articles.append((int(row["id"]), article))
    return articles


def process_profile(
    articles: list[tuple[int, Article]],
    profile: TopicProfile,
    profile_hash: str,
    existing: dict[tuple[int, str], dict[str, Any]],
    *,
    force: bool = False,
    dry_run: bool = False,
) -> dict[str, int]:
    counts = {
        "candidate": 0, "llm_review": 0, "reject": 0, "errors": 0,
        "processed": 0, "skipped": 0, "would_process": 0,
    }
    pending = []
    matcher = compile_profile_matcher(profile)

    for article_id, article in articles:
        try:
            normalized_text = article_search_text(article, profile)
            input_hash = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()
            current = existing.get((article_id, profile.id))
            unchanged = (
                current is not None
                and current.get("profile_hash") == profile_hash
                and current.get("profile_version") == profile.version
                and current.get("filter_engine_version") == FILTER_ENGINE_VERSION
                and current.get("input_hash") == input_hash
            )
            if unchanged and not force:
                counts["skipped"] += 1
                decision = current["decision"]
                counts[decision] += 1
                continue

            result = filter_article(
                article, profile, matcher=matcher, normalized_text=normalized_text
            )
            counts[result.decision] += 1
            counts["would_process"] += 1
            if not dry_run:
                pending.append({
                    "article_id": article_id,
                    "result": result,
                    "profile_hash": profile_hash,
                    "profile_version": profile.version,
                    "filter_engine_version": FILTER_ENGINE_VERSION,
                    "input_hash": input_hash,
                })
        except Exception as exc:
            counts["errors"] += 1
            print(
                f"ERROR article={article_id} profile={profile.id}: "
                f"{type(exc).__name__}: {exc}"
            )

    if not dry_run:
        counts["processed"] = save_topic_results_batch(pending)
    else:
        counts["processed"] = 0

    return counts


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Incremental Watchtower deterministic filter.")
    parser.add_argument("--force", action="store_true", help="Recompute all article/profile pairs.")
    parser.add_argument("--dry-run", action="store_true", help="Compute decisions without writing SQLite.")
    parser.add_argument("--profile-id", action="append", default=None,
                        help="Restrict execution to a topic ID; may be repeated.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    print("=" * 88)
    print("WATCHTOWER — DETERMINISTIC FILTER")
    print("=" * 88)
    print(f"Topics directory: {TOPICS_DIR}")
    print(f"Filter engine version: {FILTER_ENGINE_VERSION}")
    print(f"Force recomputation: {args.force}")
    print(f"Dry run: {args.dry_run}")

    # Apply additive schema migrations before using version metadata/history tables.
    init_database()

    profiles = load_profiles(discover_profile_files())
    if args.profile_id:
        requested = set(args.profile_id)
        available = {profile.id for _, profile, _ in profiles}
        missing = requested - available
        if missing:
            raise ValueError(f"Unknown profile IDs: {', '.join(sorted(missing))}")
        profiles = [item for item in profiles if item[1].id in requested]

    print(f"Independent YAML profiles discovered: {len(profiles)}")
    for path, profile, _ in profiles:
        print(f"  - {profile.id:<36} ({path.relative_to(BASE_DIR)})")

    articles = load_articles()
    print(f"Articles loaded: {len(articles)}")
    if not articles:
        print("No articles found. Nothing to do.")
        return 0

    existing = get_topic_result_metadata()
    configured_ids = {profile.id for _, profile, _ in profiles}
    obsolete_ids = sorted({key[1] for key in existing} - configured_ids)
    if obsolete_ids and not args.profile_id:
        print("WARNING: existing database topic IDs without a YAML profile (left untouched): "
              + ", ".join(obsolete_ids))

    totals = {key: 0 for key in (
        "candidate", "llm_review", "reject", "errors", "processed", "skipped", "would_process"
    )}
    for path, profile, profile_hash in profiles:
        print("\n" + "-" * 88)
        print(f"Profile: {profile.name} [{profile.id}]")
        result = process_profile(
            articles, profile, profile_hash, existing,
            force=args.force, dry_run=args.dry_run,
        )
        for key, value in result.items():
            totals[key] += value
        print(
            f"candidate={result['candidate']} | llm_review={result['llm_review']} | "
            f"reject={result['reject']} | processed={result['processed']} | "
            f"skipped={result['skipped']} | errors={result['errors']}"
        )

    print("\n" + "=" * 88)
    print("SUMMARY")
    print("=" * 88)
    print(f"Articles:                 {len(articles)}")
    print(f"Profiles:                 {len(profiles)}")
    print(f"Pairs processed/written:  {totals['processed']}")
    print(f"Pairs skipped unchanged:  {totals['skipped']}")
    if args.dry_run:
        print(f"Pairs that would process: {totals['would_process']}")
    print(f"Candidate decisions:      {totals['candidate']}")
    print(f"LLM review decisions:     {totals['llm_review']}")
    print(f"Rejected decisions:       {totals['reject']}")
    print(f"Errors:                   {totals['errors']}")
    if not args.dry_run:
        print(f"Total persisted results:  {count_topic_results()}")
    print("=" * 88)
    return 1 if totals["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
