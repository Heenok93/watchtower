import re

import feedparser

from models.schemas import Article


DOI_REGEX = r"10\.\d{4,9}/[-._;()/:A-Z0-9]+"


def extract_doi(text: str | None):

    if not text:
        return None

    match = re.search(
        DOI_REGEX,
        text,
        flags=re.IGNORECASE
    )

    if match:
        return match.group(0)

    return None


def collect_rss_feed(url: str):

    feed = feedparser.parse(url)

    records = []

    for entry in feed.entries:

        summary = getattr(
            entry,
            "summary",
            None
        )

        published = getattr(
            entry,
            "published",
            None
        )

        doi = extract_doi(summary)

        article = Article(
            title=entry.title,
            abstract=summary,
            doi=doi,
            source="rss",
            source_url=entry.link,
            publication_date=published
        )

        records.append(article)

    return records