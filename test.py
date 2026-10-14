from datetime import date

from models.schemas import Article
from storage.repositories import save_article


test_article = Article(
    title="Watchtower test article",
    abstract="Synthetic article used to validate the Watchtower database.",
    authors=["Alice Example", "Bob Example"],
    publication_date=date(2026, 10, 14),
    doi="10.1234/watchtower.test",
    pmid=None,
    source="manual_test",
    source_url="https://example.org/watchtower-test",
    journal="Watchtower Test Journal",
)

article_id = save_article(test_article)

print(f"Inserted article ID: {article_id}")