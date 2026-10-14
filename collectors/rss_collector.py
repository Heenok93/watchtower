import re
from datetime import date
from time import struct_time

import feedparser

from models.schemas import Article


DOI_REGEX = r"10\.\d{4,9}/[-._;()/:A-Z0-9]+"


def extract_doi(text: str | None) -> str | None:
    if not text:
        return None

    match = re.search(
        DOI_REGEX,
        text,
        flags=re.IGNORECASE,
    )

    if match:
        return match.group(0)

    return None


def parse_publication_date(entry) -> date | None:
    published_parsed: struct_time | None = getattr(
        entry,
        "published_parsed",
        None,
    )

    if published_parsed:
        return date(
            published_parsed.tm_year,
            published_parsed.tm_mon,
            published_parsed.tm_mday,
        )

    updated_parsed: struct_time | None = getattr(
        entry,
        "updated_parsed",
        None,
    )

    if updated_parsed:
        return date(
            updated_parsed.tm_year,
            updated_parsed.tm_mon,
            updated_parsed.tm_mday,
        )

    return None


def extract_authors(entry) -> list[str]:
    authors = getattr(entry, "authors", None)

    if authors:
        names = []

        for author in authors:
            name = author.get("name")

            if name:
                names.append(name)

        return names

    author = getattr(entry, "author", None)

    if author:
        return [author]

    return []


def collect_rss_feed(
    url: str,
    source_name: str = "rss",
) -> list[Article]:

    feed = feedparser.parse(url)

    if feed.bozo:
        print(
            f"Warning: RSS parsing issue for {source_name}: "
            f"{feed.bozo_exception}"
        )

    records = []

    for entry in feed.entries:
        title = getattr(
            entry,
            "title",
            None,
        )

        if not title:
            continue

        summary = getattr(
            entry,
            "summary",
            None,
        )

        source_url = getattr(
            entry,
            "link",
            None,
        )

        publication_date = parse_publication_date(
            entry
        )

        authors = extract_authors(
            entry
        )

        # Search for a DOI in several RSS fields.
        doi = None

        for candidate in [
            getattr(entry, "id", None),
            source_url,
            summary,
        ]:
            doi = extract_doi(candidate)

            if doi:
                break

        article = Article(
            title=title,
            abstract=summary,
            authors=authors,
            publication_date=publication_date,
            doi=doi,
            pmid=None,
            source=source_name,
            source_url=source_url,
            journal=None,
        )

        records.append(article)

    return records