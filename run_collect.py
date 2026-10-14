from collectors.rss_collector import collect_rss_feed

from processing.deduplicate import (
    build_article_fingerprint,
    get_duplicate_reason,
)

from processing.normalize import normalize_doi

from storage.repositories import (
    save_article,
    count_articles,
)

from storage.run_repository import (
    start_processing_run,
    finish_processing_run,
)

from utils.config import load_yaml


def main():
    sources = load_yaml("sources.yaml")

    total_found = 0
    total_inserted = 0
    total_skipped = 0
    total_errors = 0

    rss_sources = sources.get("rss", [])

    for source in rss_sources:
        source_name = source["name"]
        source_url = source["url"]

        print(f"\nCollecting: {source_name}")

        run_id = start_processing_run(
            source=source_name,
        )

        found = 0
        inserted = 0
        skipped = 0
        errors = 0

        duplicate_reasons = {
            "doi": 0,
            "pmid": 0,
            "source_url": 0,
            "fingerprint": 0,
        }

        try:
            articles = collect_rss_feed(
                url=source_url,
                source_name=source_name,
            )

            found = len(articles)

            print(f"Found: {found}")

            for article in articles:
                try:
                    article.doi = normalize_doi(
                        article.doi
                    )

                    duplicate_reason = (
                        get_duplicate_reason(article)
                    )

                    if duplicate_reason:
                        skipped += 1
                        duplicate_reasons[
                            duplicate_reason
                        ] += 1
                        continue

                    fingerprint = (
                        build_article_fingerprint(
                            article
                        )
                    )

                    save_article(
                        article=article,
                        fingerprint=fingerprint,
                    )

                    inserted += 1

                except Exception as exc:
                    errors += 1

                    print(
                        f"Error processing "
                        f"'{article.title}': {exc}"
                    )

            if errors == 0:
                status = "success"
            else:
                status = "partial"

        except Exception as exc:
            errors += 1
            status = "failed"

            print(
                f"Collection failed: {exc}"
            )

        finish_processing_run(
            run_id=run_id,
            items_found=found,
            items_inserted=inserted,
            duplicate_reasons=duplicate_reasons,
            errors=errors,
            status=status,
        )

        total_found += found
        total_inserted += inserted
        total_skipped += skipped
        total_errors += errors

        print(f"Inserted: {inserted}")
        print(f"Duplicates skipped: {skipped}")

        if skipped > 0:
            print("Duplicate reasons:")

            for reason, count in duplicate_reasons.items():
                if count > 0:
                    print(f"  {reason}: {count}")

        print(f"Errors: {errors}")
        print(f"Status: {status}")
        print(f"Processing run ID: {run_id}")

    print("\n==========")
    print(f"Total found: {total_found}")
    print(f"Total inserted: {total_inserted}")
    print(f"Total skipped: {total_skipped}")
    print(f"Total errors: {total_errors}")
    print(f"Total articles in DB: {count_articles()}")


if __name__ == "__main__":
    main()