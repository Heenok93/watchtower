import html
import re
from datetime import date, datetime
from time import struct_time

import feedparser
import requests

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
    """Extract author names across common feedparser representations."""
    authors = getattr(entry, "authors", None)
    if authors:
        if isinstance(authors, (str, dict)):
            authors = [authors]
        names: list[str] = []
        for author in authors:
            if isinstance(author, str):
                name = author
            elif isinstance(author, dict) or hasattr(author, "get"):
                name = author.get("name")
            else:
                name = None
            if isinstance(name, str):
                name = name.strip()
                if name and name not in names:
                    names.append(name)
        if names:
            return names

    author = getattr(entry, "author", None)
    if isinstance(author, str):
        author = author.strip()
        if author:
            return [author]
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
    diagnostics: dict | None = None,
) -> list[Article]:
    """Fetch and parse a feed, recording diagnostics when requested."""
    # Fetch explicitly so HTTP failures (403/404/410/429, etc.) are surfaced
    # as transport/access errors rather than being confused with XML parse errors.
    try:
        response = requests.get(
            url,
            headers={
                "User-Agent": "WatchtowerRSSCollector/1.0 (+RSS feed reader)",
                "Accept": (
                    "application/rss+xml, application/atom+xml, "
                    "application/xml, text/xml, */*"
                ),
            },
            timeout=30,
            allow_redirects=True,
        )
    except requests.RequestException as exc:
        # DNS, TLS, timeout and connection failures may have no HTTP response.
        response = getattr(exc, "response", None)
        if diagnostics is not None:
            diagnostics.update({
                "http_status": getattr(response, "status_code", None),
                "response_url": getattr(response, "url", url),
                "response_content_type": (
                    response.headers.get("Content-Type")
                    if response is not None else None
                ),
                "response_bytes": (
                    len(response.content) if response is not None else None
                ),
                "fetch_error_type": type(exc).__name__,
                "fetch_error": str(exc),
            })
        raise

    # Record response metadata before raise_for_status(), including HTTP errors.
    response_url = response.url
    content_type_header = response.headers.get("Content-Type")
    response_bytes = len(response.content)

    if diagnostics is not None:
        diagnostics.update({
            "http_status": response.status_code,
            "response_url": response_url,
            "response_content_type": content_type_header,
            "response_bytes": response_bytes,
            "fetch_error_type": None,
            "fetch_error": None,
        })

    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        message = (
            f"HTTP {response.status_code} while fetching RSS feed "
            f"{response.url} (Content-Type={content_type_header!r}, "
            f"bytes={response_bytes})"
        )
        if diagnostics is not None:
            diagnostics.update({
                "fetch_error_type": type(exc).__name__,
                "fetch_error": message,
            })
        raise

    feed = feedparser.parse(response.content)

    # Targeted recovery for Nature/NPJ RDF feeds that declare US-ASCII but
    # contain UTF-8 characters. Only retry when parsing yielded no entries and
    # the payload is valid UTF-8; do not repair arbitrary malformed XML.
    entries = list(getattr(feed, "entries", []) or [])
    exception_text = str(getattr(feed, "bozo_exception", "") or "").lower()
    needs_encoding_retry = (
        not entries
        and bool(getattr(feed, "bozo", False))
        and any(
            token in exception_text
            for token in ("not well-formed", "invalid token", "encoding", "ascii")
        )
    )
    if needs_encoding_retry:
        try:
            response.content.decode("utf-8")
            corrected = re.sub(
                br'(?i)(encoding\s*=\s*["\\\'])us-ascii(["\\\'])',
                br'\1utf-8\2',
                response.content,
                count=1,
            )
            retry_feed = feedparser.parse(corrected)
            if getattr(retry_feed, "entries", None):
                feed = retry_feed
        except UnicodeDecodeError:
            # Keep the original parser result if the response is not UTF-8.
            pass

    if diagnostics is not None:
        diagnostics.update({
            "bozo": bool(getattr(feed, "bozo", False)),
            "bozo_exception": (
                str(getattr(feed, "bozo_exception", None))
                if getattr(feed, "bozo_exception", None) else None
            ),
            "http_status": response.status_code,
            "feed_title": getattr(feed, "feed", {}).get("title"),
            "feed_version": getattr(feed, "version", None),
            "entries_received": len(getattr(feed, "entries", []) or []),
            "entries_without_title": 0,
            "encoding_retry_used": bool(
                needs_encoding_retry and not getattr(feed, "bozo", False)
            ),
            "response_url": response_url,
            "response_content_type": content_type_header,
            "response_bytes": response_bytes,
            "encoding_retry_error": None,
        })

    if feed.bozo:
        print(
            f"Warning: RSS parsing issue for "
            f"{source_name}: "
            f"{feed.bozo_exception}"
        )

    records = []
    entries_without_title = 0

    for entry in feed.entries:
        title = getattr(
            entry,
            "title",
            None,
        )

        if not title:
            entries_without_title += 1
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

    if diagnostics is not None:
        diagnostics["entries_without_title"] = entries_without_title
        diagnostics["valid_entries"] = len(records)

    return records