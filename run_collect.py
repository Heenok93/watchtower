from collectors.rss_collector import collect_rss_feed

from processing.normalize import normalize_doi

from storage.repositories import (
    article_exists_by_doi,
    save_article,
    count_articles
)

from utils.config import load_yaml

from models.schemas import Article

test_article = Article(
    title="Watchtower test article",
    abstract="Test abstract",
    doi="10.9999/test",
    source="test",
    source_url="https://example.org"
)

save_article(test_article)

def main():

    sources = load_yaml("sources.yaml")

    total_inserted = 0

    total_skipped = 0

    rss_sources = sources.get(
        "rss",
        []
    )

    for source in rss_sources:

        print(
            f"\nCollecting: {source['name']}"
        )

        articles = collect_rss_feed(
            source["url"]
        )

        inserted = 0

        skipped = 0

        print(
            f"Found {len(articles)} articles"
        )

        for article in articles:

            doi = normalize_doi(
                article.doi
            )

            article.doi = doi

            if doi:

                if article_exists_by_doi(doi):

                    skipped += 1
                    continue

            save_article(article)

            inserted += 1

        total_inserted += inserted
        total_skipped += skipped

        print(
            f"Inserted: {inserted}"
        )

        print(
            f"Duplicates skipped: {skipped}"
        )

    print("\n==========")

    print(
        f"Total inserted: {total_inserted}"
    )

    print(
        f"Total skipped: {total_skipped}"
    )

    print(
        f"Total articles in DB: {count_articles()}"
    )


if __name__ == "__main__":

    main()