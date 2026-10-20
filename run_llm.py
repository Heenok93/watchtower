"""Classification normale : uniquement les couples non traites."""
from collections import Counter, defaultdict
from pathlib import Path
from uuid import uuid4

import yaml
from enrichment.enrichment_service import enrich_article
from models.schemas import Article, TopicProfile
from processing.abstract_quality import assess_abstract_quality
from processing.llm_classifier import classify_article
from processing.llm_run_support import AuditedProvider, prepare_article
from providers.ollama_provider import OllamaProvider
from storage.llm_audit_repository import initialize_audit, update_attempt
from storage.topic_result_repository import get_llm_review_results, save_llm_result

MODEL = "qwen3-light:latest"
TEMPERATURE = 0.0
# Etiquette humaine. Les prompts reels sont aussi sauvegardes et hashes.
PROMPT_VERSION = "semantic_short_v1"
BASE_DIR = Path(__file__).resolve().parent
TOPICS_DIR = BASE_DIR / "config" / "topics"


def load_profile(topic_id):
    path = TOPICS_DIR / f"{topic_id}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Topic profile not found: {path}")
    with path.open(encoding="utf-8") as file:
        return TopicProfile.model_validate(yaml.safe_load(file))


def build_article(row):
    return Article(
        title=row["title"], abstract=row["abstract"], authors=[],
        publication_date=None, doi=row["doi"], pmid=row["pmid"],
        source=row["source"], source_url=row["source_url"],
        journal=row["journal"], content_type=row["content_type"],
    )


def new_profile_stats():
    return {"found": 0, "processed": 0, "relevant": 0,
            "not_relevant": 0, "errors": 0, "limited_information": 0,
            "audit_warnings": 0}


def print_profile_summary(topic_id, stats):
    print(f"\nProfile: {topic_id}")
    for key, value in stats.items():
        print(f"{key:<24}{value}")


def main():
    print("=" * 80)
    print("WATCHTOWER LLM CLASSIFIER V3")
    run_id = str(uuid4())
    provider = OllamaProvider(model=MODEL, temperature=TEMPERATURE)
    provider_name = provider.get_provider_name()
    model_name = provider.get_model_name()
    initialize_audit()
    print(f"Run: {run_id}\nProvider: {provider_name}\nModel: {model_name}")
    print(f"Temperature: {TEMPERATURE}\nPrompt version: {PROMPT_VERSION}")
    rows = get_llm_review_results(only_unprocessed=True)
    print(f"Unprocessed LLM review results: {len(rows)}")
    if not rows:
        print("Nothing to process.")
        return

    profiles = {}
    article_cache = {}
    stats = defaultdict(new_profile_stats)
    enrichment_stats = Counter()
    quality_before_counts = Counter()
    quality_after_counts = Counter()
    interrupted = False

    for index, row in enumerate(rows, start=1):
        article_id, topic_id = row["article_id"], row["topic_id"]
        current = stats[topic_id]
        current["found"] += 1
        audited = None
        generated = False
        print("\n" + "-" * 80)
        print(f"[{index}/{len(rows)}] Article: {article_id} | Topic: {topic_id}")
        print(f"Title: {row['title']}")
        try:
            if topic_id not in profiles:
                profiles[topic_id] = load_profile(topic_id)
            profile = profiles[topic_id]
            if article_id not in article_cache:
                used, preparation = prepare_article(
                    build_article(row), enrich=enrich_article,
                    assess=assess_abstract_quality,
                )
                article_cache[article_id] = (used, preparation)
                quality_before_counts[preparation["quality_before"]] += 1
                quality_after_counts[preparation["quality_after"]] += 1
                enrichment_stats["unique_articles"] += 1
                for key in ("enrichment_attempted", "enrichment_matched",
                            "quality_improved", "limited_information", "candidate_discarded"):
                    enrichment_stats[key] += int(preparation[key])
                enrichment_stats["already_usable"] += int(preparation["quality_before"] == "usable")
                enrichment_stats["enrichment_errors"] += int(preparation["enrichment_error"] is not None)
            else:
                enrichment_stats["cache_hits"] += 1
                print("Enrichment: cache hit")
            cached_article, preparation = article_cache[article_id]
            article = cached_article.model_copy(deep=True)
            print(f"Quality: {preparation['quality_before']} -> {preparation['quality_after']}")
            if preparation["enrichment_error"]:
                print(f"ENRICHMENT WARNING: {preparation['enrichment_error']}")
            if preparation["candidate_discarded"]:
                print("Enriched candidate discarded: original text retained.")
            if preparation["limited_information"]:
                current["limited_information"] += 1
                print("Warning: classification uses limited information.")
            audited = AuditedProvider(
                provider, article=article, profile=profile, preparation=preparation,
                context=dict(run_id=run_id, article_id=article_id, topic_id=topic_id,
                             provider_name=provider_name, model_name=model_name,
                             temperature=TEMPERATURE, prompt_version=PROMPT_VERSION),
            )
            result = classify_article(article=article, profile=profile, provider=audited)
            if audited.attempt_id is None:
                raise RuntimeError("Classifier did not use audited generate_structured")
            generated = True
            updated_rows = save_llm_result(
                article_id=article_id, topic_id=topic_id, result=result,
                provider_name=provider_name, model_name=model_name,
            )
            if updated_rows != 1:
                raise RuntimeError(f"Expected one updated llm_review row, got {updated_rows!r}")
            # La sauvegarde historique a reussi. Un echec d'audit ne doit pas
            # faire croire que la decision n'a pas ete sauvegardee.
            current["processed"] += 1
            decision = "relevant" if result.relevant else "not_relevant"
            current[decision] += 1
            try:
                update_attempt(audited.attempt_id, "persisted")
            except Exception as exc:
                current["audit_warnings"] += 1
                print(f"AUDIT WARNING: decision saved, audit remains generated: {exc}")
            print(f"Decision: {decision}\nConfidence: {result.confidence}")
            print(f"Reason: {result.reason}\nSummary: {result.summary}")
            print(f"Persistence: success | Audit ID: {audited.attempt_id}")
        except KeyboardInterrupt:
            interrupted = True
            if audited is not None and audited.attempt_id is not None:
                try:
                    update_attempt(audited.attempt_id, "interrupted", error="KeyboardInterrupt; verify persistence if interrupted during save")
                except Exception as exc:
                    print(f"AUDIT WARNING: {exc}")
            print("Interrupted. Existing saved decisions are retained.")
            break
        except Exception as exc:
            current["errors"] += 1
            if generated and audited is not None:
                try:
                    update_attempt(audited.attempt_id, "persistence_error",
                                   error=f"{type(exc).__name__}: {exc}")
                except Exception as audit_exc:
                    print(f"AUDIT WARNING: {audit_exc}")
            print(f"PROCESSING ERROR: {type(exc).__name__}: {exc}")

    print("\n" + "=" * 80 + "\nRESULTS BY PROFILE (article/topic pairs)")
    for topic_id in sorted(stats):
        print_profile_summary(topic_id, stats[topic_id])
    print("\nENRICHMENT SUMMARY (unique articles, except cache_hits)")
    for key in ("unique_articles", "already_usable", "enrichment_attempted",
                "enrichment_matched", "quality_improved", "limited_information",
                "candidate_discarded", "enrichment_errors", "cache_hits"):
        print(f"{key:<24}{enrichment_stats[key]}")
    print("\nQUALITY COUNTS (unique articles)")
    for quality in sorted(set(quality_before_counts) | set(quality_after_counts)):
        print(f"{quality:<20}before={quality_before_counts[quality]} after={quality_after_counts[quality]}")
    print("\nTOTAL")
    print(f"Queue size: {len(rows)}")
    for key in new_profile_stats():
        print(f"{key:<24}{sum(s[key] for s in stats.values())}")
    print(f"Interrupted: {interrupted}\nRun ID: {run_id}")
    print("=" * 80)


if __name__ == "__main__":
    main()