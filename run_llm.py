"""
Classification LLM des couples article/topic non traités.

Ce module peut être utilisé :

1. directement en ligne de commande ;
2. depuis l'orchestrateur main.py.

Exemples :

    python run_llm.py
    python run_llm.py --limit 5

Depuis main.py :

    import run_llm

    summary = run_llm.main(limit=5)
"""

from __future__ import annotations

import argparse
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml

from enrichment.enrichment_service import enrich_article
from models.schemas import Article, TopicProfile
from processing.abstract_quality import assess_abstract_quality
from processing.llm_classifier import classify_article
from processing.llm_run_support import (
    AuditedProvider,
    prepare_article,
)
from providers.groq_provider import GroqProvider
from storage.llm_audit_repository import (
    initialize_audit,
    update_attempt,
)
from storage.topic_result_repository import (
    get_llm_review_results,
    save_llm_result,
)

from dotenv import load_dotenv
load_dotenv()


DEFAULT_OLLAMA_MODEL = "qwen3-light:latest"
DEFAULT_GROQ_MODEL = "qwen/qwen3.8-27b"
TEMPERATURE = 0.0

# Étiquette humaine.
# Les prompts réels sont également sauvegardés et hachés
# dans la table d'audit.
PROMPT_VERSION = "semantic_scope_v2"

BASE_DIR = Path(__file__).resolve().parent
TOPICS_DIR = BASE_DIR / "config" / "topics"


def load_profile(
    topic_id: str,
) -> TopicProfile:
    """
    Load and validate one topic profile.

    The topic ID must correspond to a YAML file located in
    config/topics.
    """
    if not topic_id:
        raise ValueError(
            "Topic ID cannot be empty."
        )

    # Empêche un topic_id issu de la base de sortir du dossier prévu.
    if (
        Path(topic_id).name != topic_id
        or "/" in topic_id
        or "\\" in topic_id
    ):
        raise ValueError(
            f"Invalid topic ID: {topic_id!r}"
        )

    path = TOPICS_DIR / f"{topic_id}.yaml"

    if not path.exists():
        raise FileNotFoundError(
            f"Topic profile not found: {path}"
        )

    with path.open(
        "r",
        encoding="utf-8",
    ) as file:
        data = yaml.safe_load(file)

    if not data:
        raise ValueError(
            f"Empty topic profile: {path}"
        )

    profile = TopicProfile.model_validate(
        data
    )

    if profile.id != topic_id:
        raise ValueError(
            "Topic profile ID mismatch: "
            f"expected {topic_id!r}, "
            f"found {profile.id!r}."
        )

    return profile


def build_article(
    row,
) -> Article:
    """
    Rebuild an Article from one LLM queue row.
    """
    return Article(
        title=row["title"],
        abstract=row["abstract"],
        authors=[],
        publication_date=None,
        doi=row["doi"],
        pmid=row["pmid"],
        source=row["source"],
        source_url=row["source_url"],
        journal=row["journal"],
        content_type=row["content_type"],
    )


def new_profile_stats() -> dict[str, int]:
    """
    Return an empty statistics structure for one topic.
    """
    return {
        "found": 0,
        "processed": 0,
        "relevant": 0,
        "not_relevant": 0,
        "errors": 0,
        "limited_information": 0,
        "audit_warnings": 0,
    }


def print_profile_summary(
    topic_id: str,
    stats: dict[str, int],
) -> None:
    """
    Print the classification summary for one topic.
    """
    print()
    print("-" * 80)
    print(f"Profile: {topic_id}")
    print("-" * 80)

    for key, value in stats.items():
        print(f"{key:<24}{value}")


def normalize_limit(
    limit: int | None,
) -> int | None:
    """
    Validate the optional maximum number of pairs to process.

    None means that the entire queue can be processed.
    """
    if limit is None:
        return None

    if isinstance(limit, bool):
        raise ValueError(
            "LLM limit must be an integer."
        )

    if limit < 0:
        raise ValueError(
            "LLM limit cannot be negative."
        )

    return limit


def build_summary(
    *,
    run_id: str,
    queue_size: int,
    selected_count: int,
    stats,
    enrichment_stats: Counter,
    quality_before_counts: Counter,
    quality_after_counts: Counter,
    interrupted: bool,
    limit: int | None,
    provider_name: str,
    model_name: str,
) -> dict[str, Any]:
    """
    Build the structured result returned to main.py.
    """
    totals = {
        key: sum(
            profile_stats[key]
            for profile_stats in stats.values()
        )
        for key in new_profile_stats()
    }

    return {
        "run_id": run_id,
        "provider": provider_name,
        "model": model_name,
        "temperature": TEMPERATURE,
        "prompt_version": PROMPT_VERSION,
        "queue_size": queue_size,
        "selected_count": selected_count,
        "remaining_from_initial_queue": max(
            queue_size - totals["processed"],
            0,
        ),
        "limit": limit,
        "interrupted": interrupted,
        "processed": totals["processed"],
        "relevant": totals["relevant"],
        "not_relevant": totals["not_relevant"],
        "errors": totals["errors"],
        "limited_information": totals[
            "limited_information"
        ],
        "audit_warnings": totals[
            "audit_warnings"
        ],
        "profiles": {
            topic_id: dict(profile_stats)
            for topic_id, profile_stats
            in stats.items()
        },
        "enrichment": dict(enrichment_stats),
        "quality_before": dict(
            quality_before_counts
        ),
        "quality_after": dict(
            quality_after_counts
        ),
    }


def print_final_summary(
    *,
    summary: dict[str, Any],
    stats,
    enrichment_stats: Counter,
    quality_before_counts: Counter,
    quality_after_counts: Counter,
) -> None:
    """
    Print the final human-readable run summary.
    """
    print()
    print("=" * 80)
    print("RESULTS BY PROFILE")
    print("=" * 80)

    if stats:
        for topic_id in sorted(stats):
            print_profile_summary(
                topic_id,
                stats[topic_id],
            )
    else:
        print("No article/topic pair was processed.")

    print()
    print("=" * 80)
    print(
        "ENRICHMENT SUMMARY "
        "(unique articles, except cache_hits)"
    )
    print("=" * 80)

    for key in (
        "unique_articles",
        "already_usable",
        "enrichment_attempted",
        "enrichment_matched",
        "quality_improved",
        "limited_information",
        "candidate_discarded",
        "enrichment_errors",
        "cache_hits",
    ):
        print(
            f"{key:<24}"
            f"{enrichment_stats[key]}"
        )

    print()
    print("=" * 80)
    print("QUALITY COUNTS (unique articles)")
    print("=" * 80)

    qualities = sorted(
        set(quality_before_counts)
        | set(quality_after_counts)
    )

    if not qualities:
        print("No article quality assessment performed.")
    else:
        for quality in qualities:
            print(
                f"{quality:<20}"
                f"before="
                f"{quality_before_counts[quality]} "
                f"after="
                f"{quality_after_counts[quality]}"
            )

    print()
    print("=" * 80)
    print("TOTAL")
    print("=" * 80)

    print(
        f"{'Initial queue size:':<28}"
        f"{summary['queue_size']}"
    )

    print(
        f"{'Selected for this run:':<28}"
        f"{summary['selected_count']}"
    )

    print(
        f"{'Processed:':<28}"
        f"{summary['processed']}"
    )

    print(
        f"{'Relevant:':<28}"
        f"{summary['relevant']}"
    )

    print(
        f"{'Not relevant:':<28}"
        f"{summary['not_relevant']}"
    )

    print(
        f"{'Errors:':<28}"
        f"{summary['errors']}"
    )

    print(
        f"{'Limited information:':<28}"
        f"{summary['limited_information']}"
    )

    print(
        f"{'Audit warnings:':<28}"
        f"{summary['audit_warnings']}"
    )

    print(
        f"{'Remaining from initial queue:':<28}"
        f"{summary['remaining_from_initial_queue']}"
    )

    print(
        f"{'Interrupted:':<28}"
        f"{summary['interrupted']}"
    )

    print(
        f"{'Run ID:':<28}"
        f"{summary['run_id']}"
    )

    print("=" * 80)


def main(
    limit: int | None = None,
    provider_name: str | None = None,
    model: str | None = None,
    ollama_host: str | None = None,
) -> dict[str, Any]:
    """
    Classify unprocessed LLM review results.

    Parameters
    ----------
    limit:
        Maximum number of article/topic pairs to process.

        None processes the full current queue.
        0 processes nothing and returns a summary.
        A positive integer processes at most that number.

    Returns
    -------
    dict
        Structured summary intended for the pipeline orchestrator.

    Notes
    -----
    A KeyboardInterrupt is handled inside this function. Results
    persisted before the interruption remain available, and the
    function returns a summary with interrupted=True so that the
    orchestrator can continue to the digest and CSV exports.
    """
    limit = normalize_limit(
        limit
    )

    print("=" * 80)
    print("WATCHTOWER LLM CLASSIFIER V3")
    print("=" * 80)

    run_id = str(
        uuid4()
    )

    selected_provider = (provider_name or os.getenv("WATCHTOWER_LLM_PROVIDER", "ollama")).strip().lower()
    if selected_provider not in {"ollama", "groq"}:
        raise ValueError("LLM provider must be 'ollama' or 'groq'.")

    if model is None:
        model = os.getenv("WATCHTOWER_LLM_MODEL")
    if not model:
        model = DEFAULT_GROQ_MODEL if selected_provider == "groq" else DEFAULT_OLLAMA_MODEL

    if selected_provider == "groq":
        provider = GroqProvider(
            model=model,
            temperature=TEMPERATURE,
        )
    else:
        host = ollama_host or os.getenv(
            "WATCHTOWER_OLLAMA_HOST", "http://localhost:11434"
        )
        from providers.ollama_provider import OllamaProvider

        provider = OllamaProvider(
            model=model,
            host=host,
            temperature=TEMPERATURE,
        )

    provider_name = provider.get_provider_name()
    model_name = provider.get_model_name()

    # Idempotent initialization of the audit table.
    initialize_audit()

    print(
        f"Run: {run_id}"
    )

    print(
        f"Provider: {provider_name}"
    )

    print(
        f"Model: {model_name}"
    )

    print(
        f"Temperature: {TEMPERATURE}"
    )

    print(
        f"Prompt version: {PROMPT_VERSION}"
    )

    all_rows = get_llm_review_results(
        only_unprocessed=True
    )

    queue_size = len(
        all_rows
    )

    if limit is None:
        rows = all_rows
    else:
        rows = all_rows[:limit]

    selected_count = len(
        rows
    )

    print(
        f"Unprocessed LLM review results: "
        f"{queue_size}"
    )

    if limit is not None:
        print(
            f"Run limit: {limit}"
        )

        print(
            f"Selected for this run: "
            f"{selected_count}"
        )

    profiles = {}
    article_cache = {}

    stats = defaultdict(
        new_profile_stats
    )

    enrichment_stats = Counter()
    quality_before_counts = Counter()
    quality_after_counts = Counter()

    interrupted = False

    if not all_rows:
        print("Nothing to process.")

        summary = build_summary(
            run_id=run_id,
            queue_size=0,
            selected_count=0,
            stats=stats,
            enrichment_stats=enrichment_stats,
            quality_before_counts=(
                quality_before_counts
            ),
            quality_after_counts=(
                quality_after_counts
            ),
            interrupted=False,
            limit=limit,
            provider_name=provider_name,
            model_name=model_name,
        )

        print_final_summary(
            summary=summary,
            stats=stats,
            enrichment_stats=enrichment_stats,
            quality_before_counts=(
                quality_before_counts
            ),
            quality_after_counts=(
                quality_after_counts
            ),
        )

        return summary

    if not rows:
        print(
            "No pair selected for this run."
        )

        print(
            "The queue remains unchanged."
        )

        summary = build_summary(
            run_id=run_id,
            queue_size=queue_size,
            selected_count=0,
            stats=stats,
            enrichment_stats=enrichment_stats,
            quality_before_counts=(
                quality_before_counts
            ),
            quality_after_counts=(
                quality_after_counts
            ),
            interrupted=False,
            limit=limit,
            provider_name=provider_name,
            model_name=model_name,
        )

        print_final_summary(
            summary=summary,
            stats=stats,
            enrichment_stats=enrichment_stats,
            quality_before_counts=(
                quality_before_counts
            ),
            quality_after_counts=(
                quality_after_counts
            ),
        )

        return summary

    for index, row in enumerate(
        rows,
        start=1,
    ):
        article_id = row[
            "article_id"
        ]

        topic_id = row[
            "topic_id"
        ]

        current = stats[
            topic_id
        ]

        current[
            "found"
        ] += 1

        audited = None
        generated = False

        print()
        print("-" * 80)

        print(
            f"[{index}/{selected_count}] "
            f"Article: {article_id} | "
            f"Topic: {topic_id}"
        )

        print(
            f"Title: {row['title']}"
        )

        try:
            if topic_id not in profiles:
                profiles[
                    topic_id
                ] = load_profile(
                    topic_id
                )

            profile = profiles[
                topic_id
            ]

            if article_id not in article_cache:
                (
                    used_article,
                    preparation,
                ) = prepare_article(
                    build_article(
                        row
                    ),
                    enrich=enrich_article,
                    assess=assess_abstract_quality,
                )

                article_cache[
                    article_id
                ] = (
                    used_article,
                    preparation,
                )

                quality_before_counts[
                    preparation[
                        "quality_before"
                    ]
                ] += 1

                quality_after_counts[
                    preparation[
                        "quality_after"
                    ]
                ] += 1

                enrichment_stats[
                    "unique_articles"
                ] += 1

                for key in (
                    "enrichment_attempted",
                    "enrichment_matched",
                    "quality_improved",
                    "limited_information",
                    "candidate_discarded",
                ):
                    enrichment_stats[
                        key
                    ] += int(
                        preparation[key]
                    )

                enrichment_stats[
                    "already_usable"
                ] += int(
                    preparation[
                        "quality_before"
                    ]
                    == "usable"
                )

                enrichment_stats[
                    "enrichment_errors"
                ] += int(
                    preparation[
                        "enrichment_error"
                    ]
                    is not None
                )

            else:
                enrichment_stats[
                    "cache_hits"
                ] += 1

                print(
                    "Enrichment: cache hit"
                )

            (
                cached_article,
                preparation,
            ) = article_cache[
                article_id
            ]

            # A separate copy is provided for each topic
            # classification.
            article = cached_article.model_copy(
                deep=True
            )

            print(
                "Quality: "
                f"{preparation['quality_before']} "
                "-> "
                f"{preparation['quality_after']}"
            )

            if preparation[
                "enrichment_error"
            ]:
                print(
                    "ENRICHMENT WARNING: "
                    f"{preparation['enrichment_error']}"
                )

            if preparation[
                "candidate_discarded"
            ]:
                print(
                    "Enriched candidate discarded: "
                    "original text retained."
                )

            if preparation[
                "limited_information"
            ]:
                current[
                    "limited_information"
                ] += 1

                print(
                    "Warning: classification uses "
                    "limited information."
                )

            audited = AuditedProvider(
                provider,
                article=article,
                profile=profile,
                preparation=preparation,
                context={
                    "run_id": run_id,
                    "article_id": article_id,
                    "topic_id": topic_id,
                    "provider_name": provider_name,
                    "model_name": model_name,
                    "temperature": TEMPERATURE,
                    "prompt_version": PROMPT_VERSION,
                },
            )

            result = classify_article(
                article=article,
                profile=profile,
                provider=audited,
            )

            if audited.attempt_id is None:
                raise RuntimeError(
                    "Classifier did not use audited "
                    "generate_structured."
                )

            generated = True

            updated_rows = save_llm_result(
                article_id=article_id,
                topic_id=topic_id,
                result=result,
                provider_name=provider_name,
                model_name=model_name,
            )

            if updated_rows != 1:
                raise RuntimeError(
                    "Expected one updated llm_review "
                    "row, got "
                    f"{updated_rows!r}."
                )

            # The historical result was successfully saved.
            # An audit update problem must not make the
            # persisted classification appear unsuccessful.
            current[
                "processed"
            ] += 1

            decision = (
                "relevant"
                if result.relevant
                else "not_relevant"
            )

            current[
                decision
            ] += 1

            try:
                update_attempt(
                    audited.attempt_id,
                    "persisted",
                )

            except Exception as exc:
                current[
                    "audit_warnings"
                ] += 1

                print(
                    "AUDIT WARNING: decision saved, "
                    "audit remains generated: "
                    f"{type(exc).__name__}: {exc}"
                )

            print(
                f"Decision: {decision}"
            )

            print(
                f"Confidence: "
                f"{result.confidence}"
            )

            print(
                f"Reason: {result.reason}"
            )

            print(
                f"Summary: {result.summary}"
            )

            print(
                "Persistence: success | "
                f"Audit ID: {audited.attempt_id}"
            )

        except KeyboardInterrupt:
            interrupted = True

            if (
                audited is not None
                and audited.attempt_id is not None
            ):
                try:
                    update_attempt(
                        audited.attempt_id,
                        "interrupted",
                        error=(
                            "KeyboardInterrupt; verify "
                            "persistence if interrupted "
                            "during save."
                        ),
                    )

                except Exception as exc:
                    current[
                        "audit_warnings"
                    ] += 1

                    print(
                        "AUDIT WARNING: "
                        f"{type(exc).__name__}: {exc}"
                    )

            print()
            print(
                "Interrupted. Existing saved "
                "decisions are retained."
            )

            print(
                "The pipeline may continue with "
                "the digest and CSV exports."
            )

            break

        except Exception as exc:
            current[
                "errors"
            ] += 1

            if (
                generated
                and audited is not None
                and audited.attempt_id is not None
            ):
                try:
                    update_attempt(
                        audited.attempt_id,
                        "persistence_error",
                        error=(
                            f"{type(exc).__name__}: "
                            f"{exc}"
                        ),
                    )

                except Exception as audit_exc:
                    current[
                        "audit_warnings"
                    ] += 1

                    print(
                        "AUDIT WARNING: "
                        f"{type(audit_exc).__name__}: "
                        f"{audit_exc}"
                    )

            print(
                "PROCESSING ERROR: "
                f"{type(exc).__name__}: "
                f"{exc}"
            )

    summary = build_summary(
        run_id=run_id,
        queue_size=queue_size,
        selected_count=selected_count,
        stats=stats,
        enrichment_stats=enrichment_stats,
        quality_before_counts=(
            quality_before_counts
        ),
        quality_after_counts=(
            quality_after_counts
        ),
        interrupted=interrupted,
        limit=limit,
        provider_name=provider_name,
        model_name=model_name,
    )

    print_final_summary(
        summary=summary,
        stats=stats,
        enrichment_stats=enrichment_stats,
        quality_before_counts=(
            quality_before_counts
        ),
        quality_after_counts=(
            quality_after_counts
        ),
    )

    return summary


def parse_args() -> argparse.Namespace:
    """
    Parse command-line arguments.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Classify unprocessed Watchtower "
            "article/topic pairs with the configured LLM."
        )
    )

    parser.add_argument(
        "--provider",
        choices=("ollama", "groq"),
        default=None,
        help="LLM provider (default: WATCHTOWER_LLM_PROVIDER or ollama).",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model ID; defaults to WATCHTOWER_LLM_MODEL or the provider default.",
    )
    parser.add_argument(
        "--ollama-host",
        default=None,
        help="Ollama server URL (default: WATCHTOWER_OLLAMA_HOST or localhost).",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help=(
            "Maximum number of article/topic pairs "
            "to process. By default, process the "
            "entire current queue."
        ),
    )

    return parser.parse_args()


def cli() -> int:
    """
    Command-line entry point.

    The function returns zero after normal completion,
    including a deliberate Ctrl+C handled during the
    classification loop. Already persisted results remain
    valid and the pipeline can continue later.
    """
    args = parse_args()

    try:
        summary = main(
            limit=args.limit,
            provider_name=args.provider,
            model=args.model,
            ollama_host=args.ollama_host,
        )

    except Exception as exc:
        print()
        print(
            "FATAL LLM ERROR: "
            f"{type(exc).__name__}: "
            f"{exc}"
        )

        return 1

    if summary[
        "errors"
    ]:
        print(
            "LLM processing completed with "
            f"{summary['errors']} article-level error(s)."
        )

        # The digest and CSV remain usable despite
        # article-level classification failures.
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(
        cli()
    )