# SQLite migrations

`storage/migration_runner.py` is the active migration runner. It is invoked by
`storage.database.init_database()` and records applied versions in
`schema_migrations`.

The SQL files `001`–`007` are legacy design artefacts; they were not used by the
current database initializer. The first additive migration managed by the new
runner is version `8` (`classification_v2`). It adds metadata columns to
`article_topic_results` and creates the immutable model-prediction store plus
current/history tables for article-level multilabel classifications.

Migrations must remain additive. Never delete or rewrite historical model
predictions or classification history during a schema migration.


## Deterministic filter V2.2

`run_filter.py` discovers YAML profiles recursively under `config/topics/`.
Each profile is evaluated independently. Results are skipped when the YAML
profile hash, searchable article-text hash, profile version, and filter-engine
version are unchanged.

Useful options:

- `--dry-run`: calculate decisions without writing topic results (the script
  still calls `init_database()`, so pending additive migrations may be applied).
- `--force`: recompute every article/profile pair.
- `--profile-id <id>`: restrict processing to one profile; repeatable.

A changed profile/text/engine archives any legacy per-topic LLM output in
`article_topic_llm_history`, clears the obsolete legacy LLM columns, and marks
the current article-level classification as stale. Historical raw predictions
and classification revisions are retained.


Migration `010` creates `classification_queue`, a persistent one-row-per-article
queue for the union of configured `llm_review` results. Queue provenance stores
all triggering profile IDs. Changes in article text, taxonomy version, or System 1
prompt version reset the queue item to `pending`; prior model predictions remain
append-only in `model_predictions`.
