from models.schemas import Article
from processing.abstract_quality import (
    assess_abstract_quality,
)
from enrichment.enrichment_service import (
    enrich_article,
)


TEST_ARTICLES = [
    Article(
        title=(
            "Factors associated with cholera outbreaks, "
            "Nairobi County, July 2017: a case control study"
        ),
        abstract=(
            "Background Cholera affects populations globally. "
            "This study investigated factors associated with "
            "cholera outbreaks in Nairobi County and examined "
            "epidemiological characteristics and control measures."
        ),
        authors=[],
        publication_date=None,
        doi="10.1101/674549v1",
        source="test_biorxiv",
        source_url=None,
        journal="bioRxiv",
        content_type="preprint",
    ),

    Article(
        title=(
            "Extending synthetic medical education: "
            "generating OSCE cases with LLMs"
        ),
        abstract=(
            "npj Digital Medicine, Published online: "
            "19 October 2026; "
            "doi:10.1038/s41746-026-03421-8 "
            "Extending synthetic medical education: "
            "generating OSCE cases with LLMs"
        ),
        authors=[],
        publication_date=None,
        doi="10.1038/s41746-026-03421-8",
        source="test_npj",
        source_url=None,
        journal="npj Digital Medicine",
        content_type="mixed",
    ),

    Article(
        title=(
            "LLMKG＋: Systematically improving knowledge "
            "quality and coverage in KGs using LLMs – "
            "A case study in medical domain"
        ),
        abstract=(
            "Publication date: 2025 "
            "Source: AI Open, Volume 6 "
            "Author(s): Xincan Feng, Hejie Cui, "
            "Kazuki Hayashi"
        ),
        authors=[],
        publication_date=None,
        doi=None,
        source="test_ai_open",
        source_url=None,
        journal="AI Open",
        content_type="mixed",
    ),
]


def print_quality(
    label,
    article,
):
    quality = assess_abstract_quality(
        abstract=article.abstract,
        title=article.title,
    )

    print()
    print(label)
    print("-" * 80)

    print(
        f"Quality:           "
        f"{quality.quality}"
    )

    print(
        f"Informative words: "
        f"{quality.informative_word_count}"
    )

    print(
        f"Reason:            "
        f"{quality.reason}"
    )

    if article.abstract:
        preview = " ".join(
            article.abstract.split()
        )

        if len(preview) > 500:
            preview = (
                preview[:500]
                + "..."
            )

        print(
            f"Abstract:          "
            f"{preview}"
        )
    else:
        print("Abstract:          None")


def print_article_metadata(
    article,
):
    print(f"DOI:               {article.doi}")
    print(f"PMID:              {article.pmid}")
    print(
        f"Publication date:  "
        f"{article.publication_date}"
    )
    print(f"Journal:           {article.journal}")
    print(f"Authors:           {article.authors}")


def run_test(
    index,
    article,
):
    print()
    print("=" * 80)
    print(f"TEST {index}")
    print("=" * 80)

    print(f"Title: {article.title}")
    print()

    print("BEFORE ENRICHMENT")
    print("=" * 80)

    print_article_metadata(
        article
    )

    print_quality(
        label="ABSTRACT QUALITY",
        article=article,
    )

    print()
    print("RUNNING ENRICHMENT...")
    print("=" * 80)

    try:
        enriched, results = enrich_article(
            article
        )

    except Exception as exc:
        print(
            f"ENRICHMENT ERROR: "
            f"{type(exc).__name__}: {exc}"
        )
        return

    print()
    print("PROVIDER RESULTS")
    print("=" * 80)

    if not results:
        print("No provider result returned.")

    for result in results:
        print()
        print(
            f"Provider:     "
            f"{result.provider}"
        )
        print(
            f"Matched:      "
            f"{result.matched}"
        )
        print(
            f"Match method: "
            f"{result.match_method}"
        )
        print(
            f"Title:        "
            f"{result.title}"
        )
        print(
            f"DOI:          "
            f"{result.doi}"
        )
        print(
            f"PMID:         "
            f"{result.pmid}"
        )
        print(
            f"Date:         "
            f"{result.publication_date}"
        )
        print(
            f"Journal:      "
            f"{result.journal}"
        )
        print(
            f"Authors:      "
            f"{len(result.authors)}"
        )

        if result.abstract:
            print(
                f"Abstract len: "
                f"{len(result.abstract)}"
            )
        else:
            print("Abstract len: 0")

    print()
    print("AFTER ENRICHMENT")
    print("=" * 80)

    print_article_metadata(
        enriched
    )

    print_quality(
        label="ABSTRACT QUALITY",
        article=enriched,
    )


def main():
    print("=" * 80)
    print("WATCHTOWER ENRICHMENT TEST")
    print("=" * 80)

    print(
        f"Test articles: "
        f"{len(TEST_ARTICLES)}"
    )

    for index, article in enumerate(
        TEST_ARTICLES,
        start=1,
    ):
        run_test(
            index=index,
            article=article,
        )

    print()
    print("=" * 80)
    print("TEST COMPLETED")
    print("=" * 80)


if __name__ == "__main__":
    main()