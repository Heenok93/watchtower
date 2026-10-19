from collectors.rss_collector import collect_rss_feed


TEST_SOURCES = [
    {
        "name": "ai_open",
        "url": (
            "https://rss.sciencedirect.com/"
            "publication/science/26666510"
        ),
        "content_type": "mixed",
        "journal": "AI Open",
    },
    {
        "name": "patterns",
        "url": (
            "https://rss.sciencedirect.com/"
            "publication/science/26663899"
        ),
        "content_type": "mixed",
        "journal": "Patterns",
    },
]


SAMPLES_PER_SOURCE = 5


def print_article(article, index):
    print()
    print("-" * 80)
    print(f"[{index}]")
    print("-" * 80)

    print(f"Title:        {article.title}")
    print(f"Date:         {article.publication_date}")
    print(f"Authors:      {article.authors}")
    print(f"DOI:          {article.doi}")
    print(f"Journal:      {article.journal}")
    print(f"Content type: {article.content_type}")

    abstract = article.abstract

    if abstract:
        print(
            f"Abstract len: {len(abstract)} characters"
        )
        print()
        print("ABSTRACT")
        print(abstract)
    else:
        print("Abstract:     None")

    print()
    print(f"URL:          {article.source_url}")


def main():
    print("=" * 80)
    print("WATCHTOWER RSS METADATA TEST")
    print("=" * 80)

    total_errors = 0

    for source in TEST_SOURCES:
        print()
        print("=" * 80)
        print(f"SOURCE: {source['name']}")
        print("=" * 80)

        try:
            articles = collect_rss_feed(
                url=source["url"],
                source_name=source["name"],
                content_type=source["content_type"],
                journal=source["journal"],
            )

        except Exception as exc:
            total_errors += 1

            print(
                f"COLLECTION ERROR: "
                f"{type(exc).__name__}: {exc}"
            )

            continue

        print(
            f"Articles returned: "
            f"{len(articles)}"
        )

        if not articles:
            print("No articles returned.")
            continue

        sample = articles[
            :SAMPLES_PER_SOURCE
        ]

        dates_found = 0
        authors_found = 0
        dois_found = 0
        abstracts_found = 0

        for index, article in enumerate(
            sample,
            start=1,
        ):
            if article.publication_date:
                dates_found += 1

            if article.authors:
                authors_found += 1

            if article.doi:
                dois_found += 1

            if (
                article.abstract
                and article.abstract.strip()
            ):
                abstracts_found += 1

            print_article(
                article=article,
                index=index,
            )

        print()
        print("SAMPLE SUMMARY")
        print("-" * 80)
        print(
            f"Sample size:       "
            f"{len(sample)}"
        )
        print(
            f"Dates extracted:   "
            f"{dates_found}/{len(sample)}"
        )
        print(
            f"Authors extracted: "
            f"{authors_found}/{len(sample)}"
        )
        print(
            f"DOIs extracted:    "
            f"{dois_found}/{len(sample)}"
        )
        print(
            f"Abstracts present: "
            f"{abstracts_found}/{len(sample)}"
        )

    print()
    print("=" * 80)

    if total_errors == 0:
        print("TEST COMPLETED")
    else:
        print(
            f"TEST COMPLETED WITH "
            f"{total_errors} SOURCE ERROR(S)"
        )

    print("=" * 80)


if __name__ == "__main__":
    main()