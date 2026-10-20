"""Tests isoles : doubles de test, sans Ollama ni base de production."""
import importlib
from contextlib import closing
import json
import sqlite3
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
# Le module de production n'est jamais importe dans ces tests.
database_stub = types.ModuleType("storage.database")
sys.modules["storage.database"] = database_stub


class ArticleStub(BaseModel):
    title: str = "Test title"
    abstract: str | None = None


class ResultStub(BaseModel):
    relevant: bool = True
    confidence: float = 0.8
    reason: str = "Test reason"
    summary: str = "Test summary"


def assess(*, abstract, title):
    quality = "missing" if not abstract else abstract
    return SimpleNamespace(quality=quality, informative_word_count=0)


class PatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "test.sqlite"
        self.connections = []

        class TrackedConnection(sqlite3.Connection):
            closed = False

            def close(connection):
                try:
                    super(TrackedConnection, connection).close()
                finally:
                    connection.closed = True

        def connect():
            connection = sqlite3.connect(self.path, factory=TrackedConnection)
            self.connections.append(connection)
            return connection

        database_stub.get_connection = connect
        self.addCleanup(self.close_tracked_connections)
        self.audit = importlib.import_module("storage.llm_audit_repository")
        self.support = importlib.import_module("processing.llm_run_support")
        self.audit.get_connection = database_stub.get_connection
        self.audit.initialize_audit()

    def close_tracked_connections(self):
        leaked = [c for c in self.connections if not c.closed]
        for connection in leaked:
            connection.close()
        self.assertEqual(len(leaked), 0, "Audit connections were not closed")

    def test_improvement_and_degradation(self):
        q = lambda s: SimpleNamespace(quality=s)
        self.assertTrue(self.support.quality_improved(q("short"), q("usable")))
        self.assertFalse(self.support.quality_improved(q("short"), q("missing")))
        self.assertFalse(self.support.quality_improved(q("short"), q("short")))
        self.assertFalse(self.support.quality_improved(q("unknown"), q("usable")))

    def test_no_enrichment_when_usable(self):
        def forbidden(article):
            raise AssertionError("Must not enrich usable text")
        used, info = self.support.prepare_article(ArticleStub(abstract="usable"), enrich=forbidden, assess=assess)
        self.assertFalse(info["enrichment_attempted"])
        self.assertFalse(info["limited_information"])

    def test_degraded_candidate_discarded(self):
        original = ArticleStub(abstract="short")
        def enrich(article):
            article.abstract = None
            return article, []
        used, info = self.support.prepare_article(original, enrich=enrich, assess=assess)
        self.assertEqual(used.abstract, "short")
        self.assertEqual(original.abstract, "short")
        self.assertTrue(info["candidate_discarded"])
        self.assertFalse(info["quality_improved"])

    def test_enrichment_error_fallback(self):
        def enrich(article):
            raise RuntimeError("test failure")
        used, info = self.support.prepare_article(ArticleStub(abstract="short"), enrich=enrich, assess=assess)
        self.assertEqual(used.abstract, "short")
        self.assertIn("test failure", info["enrichment_error"])
        self.assertTrue(info["limited_information"])

    def make_provider(self, delegate):
        return self.support.AuditedProvider(delegate, article=ArticleStub(abstract="usable"),
            profile=ArticleStub(title="Topic"), preparation={"quality_after": "usable"},
            context=dict(run_id="test", article_id=1, topic_id="topic", provider_name="test",
                         model_name="test", temperature=0.0, prompt_version="test"))

    def test_actual_prompts_result_and_status(self):
        class Delegate:
            def generate_structured(self, **kwargs):
                return ResultStub()
        provider = self.make_provider(Delegate())
        provider.generate_structured(system_prompt="actual system", user_prompt="actual user", output_model=ResultStub)
        self.audit.update_attempt(provider.attempt_id, "persisted")
        with closing(sqlite3.connect(self.path)) as c:
            row = c.execute("SELECT status,payload_json,result_json,prompt_hash FROM llm_classification_audit").fetchone()
        self.assertEqual(row[0], "persisted")
        self.assertEqual(json.loads(row[1])["system_prompt"], "actual system")
        self.assertEqual(json.loads(row[1])["user_prompt"], "actual user")
        self.assertTrue(json.loads(row[2])["relevant"])
        self.assertEqual(len(row[3]), 64)

    def test_provider_error_audited(self):
        class Delegate:
            def generate_structured(self, **kwargs):
                raise RuntimeError("provider test failure")
        provider = self.make_provider(Delegate())
        with self.assertRaises(RuntimeError):
            provider.generate_structured(system_prompt="s", user_prompt="u", output_model=ResultStub)
        with closing(sqlite3.connect(self.path)) as c:
            row = c.execute("SELECT status,error FROM llm_classification_audit").fetchone()
        self.assertEqual(row[0], "failed")
        self.assertIn("provider test failure", row[1])

    def test_migration_idempotent(self):
        self.audit.initialize_audit()
        self.audit.initialize_audit()
        with closing(sqlite3.connect(self.path)) as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM llm_classification_audit").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
