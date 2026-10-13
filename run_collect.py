from utils.config import load_yaml

from collectors.rss_collector import (
    collect_rss_feed
)

from storage.repositories import (
    save_article
)


sources = load_yaml("sources.yaml")

for source in sources["rss"]:

    print(
        f"Collecting {source['name']}"
    )

    articles = collect_rss_feed(
        source["url"]
    )

    print(
        f"Found {len(articles)} articles"
    )

    for article in articles:
        save_article(article)