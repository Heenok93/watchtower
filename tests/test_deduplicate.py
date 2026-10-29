"""Unit tests for article deduplication; no production database is accessed."""
import unittest
from datetime import date
from unittest.mock import patch

from models.schemas import Article
from processing.deduplicate import (
    build_article_fingerprint,
    get_duplicate_reason,
    normalize_pmid,
    normalize_text,
)


def make_article(**overrides):
    values = {
        "title": "A Study of Disease Surveillance",
        "authors": ["Doe, Jane"],
        "publication_date": date(2025, 4, 12),
        "doi": None,
        "pmid": None,
        "source": "test feed",
        "source_url": "https://example.org/article/1",
    }
    values.update(overrides)
    return Article(**values)


class NormalizeTests(unittest.TestCase):
    def test_normalize_text_ignores_case_accents_and_punctuation(self):
        self.assertEqual(
            normalize_text("  ÉPIDÉMIOLOGY: A Study! "),
            "epidemiology a study",
        )

    def test_normalize_text_empty_values(self):
        self.assertEqual(normalize_text(None), "")
        self.assertEqual(normalize_text("   "), "")

    def test_normalize_pmid_accepts_plain_prefixed_and_url_forms(self):
        self.assertEqual(normalize_pmid("12345"), "12345")
        self.assertEqual(normalize_pmid("PMID: 12345"), "12345")
        self.assertEqual(
            normalize_pmid("https://pubmed.ncbi.nlm.nih.gov/12345/"),
            "12345",
        )
        self.assertIsNone(normalize_pmid("  "))


class FingerprintTests(unittest.TestCase):
    def test_fingerprint_is_stable_for_text_variants(self):
        first = make_article(title="Épidémiology: A Study!")
        second = make_article(title="epidemiology a study")
        self.assertEqual(
            build_article_fingerprint(first),
            build_article_fingerprint(second),
        )

    def test_fingerprint_includes_first_author_and_date(self):
        baseline = build_article_fingerprint(make_article())
        other_author = build_article_fingerprint(
            make_article(authors=["Smith, John"])
        )
        other_date = build_article_fingerprint(
            make_article(publication_date=date(2025, 4, 13))
        )
        self.assertNotEqual(baseline, other_author)
        self.assertNotEqual(baseline, other_date)

    def test_fingerprint_is_none_for_empty_title(self):
        self.assertIsNone(build_article_fingerprint(make_article(title="   ")))

    def test_fingerprint_is_sha256_hex(self):
        fingerprint = build_article_fingerprint(make_article())
        self.assertEqual(len(fingerprint), 64)
        int(fingerprint, 16)  # Raises if the result is not hexadecimal.


class DuplicateReasonTests(unittest.TestCase):
    @patch("processing.deduplicate.article_exists_by_fingerprint", return_value=False)
    @patch("processing.deduplicate.article_exists_by_source_url", return_value=False)
    @patch("processing.deduplicate.article_exists_by_pmid", return_value=False)
    @patch("processing.deduplicate.article_exists_by_doi", return_value=True)
    def test_doi_has_highest_priority_and_is_normalized(
        self, exists_doi, exists_pmid, exists_url, exists_fingerprint
    ):
        article = make_article(doi="https://doi.org/10.1234/ABC")
        self.assertEqual(get_duplicate_reason(article), "doi")
        exists_doi.assert_called_once_with("10.1234/abc")
        exists_pmid.assert_not_called()
        exists_url.assert_not_called()
        exists_fingerprint.assert_not_called()

    @patch("processing.deduplicate.article_exists_by_fingerprint", return_value=False)
    @patch("processing.deduplicate.article_exists_by_source_url", return_value=False)
    @patch("processing.deduplicate.article_exists_by_pmid", return_value=True)
    @patch("processing.deduplicate.article_exists_by_doi", return_value=False)
    def test_pmid_is_normalized_and_checked_after_doi(
        self, exists_doi, exists_pmid, exists_url, exists_fingerprint
    ):
        article = make_article(pmid="PMID: 12345")
        self.assertEqual(get_duplicate_reason(article), "pmid")
        exists_pmid.assert_called_once_with("12345")
        exists_url.assert_not_called()
        exists_fingerprint.assert_not_called()

    @patch("processing.deduplicate.article_exists_by_fingerprint", return_value=False)
    @patch("processing.deduplicate.article_exists_by_source_url", return_value=True)
    @patch("processing.deduplicate.article_exists_by_pmid", return_value=False)
    @patch("processing.deduplicate.article_exists_by_doi", return_value=False)
    def test_source_url_reason(
        self, exists_doi, exists_pmid, exists_url, exists_fingerprint
    ):
        self.assertEqual(get_duplicate_reason(make_article()), "source_url")
        exists_fingerprint.assert_not_called()

    @patch("processing.deduplicate.article_exists_by_fingerprint", return_value=True)
    @patch("processing.deduplicate.article_exists_by_source_url", return_value=False)
    @patch("processing.deduplicate.article_exists_by_pmid", return_value=False)
    @patch("processing.deduplicate.article_exists_by_doi", return_value=False)
    def test_fingerprint_reason(
        self, exists_doi, exists_pmid, exists_url, exists_fingerprint
    ):
        self.assertEqual(get_duplicate_reason(make_article()), "fingerprint")
        exists_fingerprint.assert_called_once_with(
            build_article_fingerprint(make_article())
        )

    @patch("processing.deduplicate.article_exists_by_fingerprint", return_value=False)
    @patch("processing.deduplicate.article_exists_by_source_url", return_value=False)
    @patch("processing.deduplicate.article_exists_by_pmid", return_value=False)
    @patch("processing.deduplicate.article_exists_by_doi", return_value=False)
    def test_returns_none_when_no_criterion_matches(
        self, exists_doi, exists_pmid, exists_url, exists_fingerprint
    ):
        self.assertIsNone(get_duplicate_reason(make_article()))

    @patch("processing.deduplicate.article_exists_by_fingerprint", return_value=False)
    @patch("processing.deduplicate.article_exists_by_source_url", return_value=False)
    @patch("processing.deduplicate.article_exists_by_pmid", return_value=False)
    @patch("processing.deduplicate.article_exists_by_doi", return_value=False)
    def test_empty_identifiers_do_not_trigger_lookup_errors(
        self, exists_doi, exists_pmid, exists_url, exists_fingerprint
    ):
        article = make_article(title=" ", doi=" ", pmid=" ", source_url=None)
        self.assertIsNone(get_duplicate_reason(article))
        exists_doi.assert_not_called()
        exists_pmid.assert_not_called()
        exists_url.assert_not_called()
        exists_fingerprint.assert_not_called()


if __name__ == "__main__":
    unittest.main()
