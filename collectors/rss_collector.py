import html
import re
from datetime import date, datetime
from time import struct_time

import feedparser

from models.schemas import Article


DOI_REGEX = r"10\.\d{4,9}/[-._;()/:A-Z0-9]+"

HTML_TAG_REGEX = re.compile(
    r"<[^>]+>"
)

WHITESPACE_REGEX = re.compile(
    r"\s+"
)

PUBLICATION_DATE_REGEX = re.compile(
    r"Publication date:\s*([^<\n]+)",
    flags=re.IGNORECASE,
)

AUTHORS_REGEX = re.compile(
    r"Author\(s\):\s*([^<\n]+)",
    flags=re.IGNORECASE,
)


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


def clean_text(text: str | None) -> str | None:
    """
    Convert RSS HTML into simple readable text.

    This is intentionally lightweight and does not try
    to behave like a complete HTML parser.
    """

    if not text:
        return None

    text = html.unescape(text)

    text = HTML_TAG_REGEX.sub(
        " ",
        text,
    )

    text = html.unescape(text)

    text = WHITESPACE_REGEX.sub(
        " ",
        text,
    ).strip()

    return text or None


def parse_standard_publication_date(
    entry,
) -> date | None:
    """
    Prefer dates already parsed by feedparser.
    """

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


def parse_date_text(
    value: str | None,
) -> date | None:
    """
    Parse the simple publication-date formats observed
    in RSS metadata fallbacks.

    This is deliberately conservative.
    """

    if not value:
        return None

    value = value.strip()

    formats = [
        "%Y-%m-%d",
        "%Y",
        "%d %B %Y",
        "%d %b %Y",
        "%B %d, %Y",
        "%b %d, %Y",
    ]

    prefixes = [
        "Available online ",
        "Published online: ",
        "Published online ",
    ]

    for prefix in prefixes:
        if value.lower().startswith(
            prefix.lower()
        ):
            value = value[
                len(prefix):
            ].strip()

    for date_format in formats:
        try:
            parsed = datetime.strptime(
                value,
                date_format,
            )

            return parsed.date()

        except ValueError:
            continue

    return None


def extract_metadata_date(
    raw_summary: str | None,
) -> date | None:
    """
    Fallback for feeds such as ScienceDirect that put
    publication metadata inside the RSS description.
    """

    if not raw_summary:
        return None

    decoded = html.unescape(
        raw_summary
    )

    match = PUBLICATION_DATE_REGEX.search(
        decoded
    )

    if not match:
        return None

    return parse_date_text(
        match.group(1)
    )


def parse_publication_date(
    entry,
    raw_summary: str | None = None,
) -> date | None:
    """
    First use structured RSS date fields.

    If unavailable, try a conservative metadata fallback
    from the RSS summary.
    """

    publication_date = (
        parse_standard_publication_date(
            entry
        )
    )

    if publication_date:
        return publication_date

    return extract_metadata_date(
        raw_summary
    )


def extract_standard_authors(
    entry,
) -> list[str]:
    """
    Extract authors from standard feedparser fields.
    """

    authors = getattr(
        entry,
        "authors",
        None,
    )

    if authors:
        names = []

        for author in authors:
            name = author.get("name")

            if name:
                names.append(
                    name.strip()
                )

        if names:
            return names

    author = getattr(
        entry,
        "author",
        None,
    )

    if author:
        return [
            author.strip()
        ]

    return []


def extract_metadata_authors(
    raw_summary: str | None,
) -> list[str]:
    """
    Fallback for RSS descriptions containing an
    'Author(s): ...' metadata block.
    """

    if not raw_summary:
        return []

    decoded = html.unescape(
        raw_summary
    )

    match = AUTHORS_REGEX.search(
        decoded
    )

    if not match:
        return []

    raw_authors = match.group(1)

    authors = [
        author.strip()
        for author in raw_authors.split(",")
        if author.strip()
    ]

    return authors


def extract_authors(
    entry,
    raw_summary: str | None = None,
) -> list[str]:
    """
    Prefer structured RSS author fields.

    Fall back to textual metadata only when structured
    authors are unavailable.
    """

    authors = extract_standard_authors(
        entry
    )

    if authors:
        return authors

    return extract_metadata_authors(
        raw_summary
    )


def extract_summary(
    entry,
) -> str | None:
    """
    Return a cleaned RSS summary.

    It is not assumed to be a true scientific abstract.
    Quality assessment is intentionally handled elsewhere.
    """

    summary = getattr(
        entry,
        "summary",
        None,
    )

    if summary:
        return clean_text(summary)

    content = getattr(
        entry,
        "content",
        None,
    )

    if content:
        for item in content:
            value = item.get("value")

            if value:
                return clean_text(value)

    return None


def collect_rss_feed(
    url: str,
    source_name: str = "rss",
    content_type: str = "unknown",
    journal: str | None = None,
) -> list[Article]:
    feed = feedparser.parse(url)

    if feed.bozo:
        print(
            f"Warning: RSS parsing issue for "
            f"{source_name}: "
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

        raw_summary = getattr(
            entry,
            "summary",
            None,
        )

        abstract = extract_summary(
            entry
        )

        source_url = getattr(
            entry,
            "link",
            None,
        )

        publication_date = parse_publication_date(
            entry=entry,
            raw_summary=raw_summary,
        )

        authors = extract_authors(
            entry=entry,
            raw_summary=raw_summary,
        )

        doi = None

        for candidate in [
            getattr(entry, "id", None),
            source_url,
            raw_summary,
        ]:
            doi = extract_doi(
                candidate
            )

            if doi:
                break

        article = Article(
            title=clean_text(title) or title,
            abstract=abstract,
            authors=authors,
            publication_date=publication_date,
            doi=doi,
            pmid=None,
            source=source_name,
            source_url=source_url,
            journal=journal,
            content_type=content_type,
        )

        records.append(article)

    return records