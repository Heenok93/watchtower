import feedparser

from models.schemas import Article


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