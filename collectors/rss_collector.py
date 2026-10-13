import re
import feedparser

from models.schemas import Article


DOI_REGEX = r"10\.\d{4,9}/[-._;()/:A-Z0-9]+"

def extract_doi(text):

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
``

def collect_rss_feed(url):

    feed = feedparser.parse(url)

    records = []

    for entry in feed.entries:

        article = Article(
            title=entry.title,
            abstract=getattr(
                entry,
                "summary",
                None
            ),
            source="rss",
            source_url=entry.link
        )

        records.append(article)

    return records