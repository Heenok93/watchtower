from datetime import datetime, timezone

from storage.database import get_connection


def start_processing_run(
    source: str,
) -> int:

    started_at = datetime.now(
        timezone.utc
    ).isoformat()

    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO processing_runs (
                source,
                started_at,
                status
            )
            VALUES (?, ?, ?)
            """,
            (
                source,
                started_at,
                "running",
            ),
        )

        conn.commit()

        return cursor.lastrowid


def finish_processing_run(
    run_id: int,
    items_found: int,
    items_inserted: int,
    duplicate_reasons: dict[str, int],
    errors: int,
    status: str,
) -> None:

    finished_at = datetime.now(
        timezone.utc
    ).isoformat()

    with get_connection() as conn:
        conn.execute(
            """
            UPDATE processing_runs
            SET
                finished_at = ?,
                items_found = ?,
                items_inserted = ?,
                duplicates_doi = ?,
                duplicates_pmid = ?,
                duplicates_source_url = ?,
                duplicates_fingerprint = ?,
                errors = ?,
                status = ?
            WHERE id = ?
            """,
            (
                finished_at,
                items_found,
                items_inserted,
                duplicate_reasons.get("doi", 0),
                duplicate_reasons.get("pmid", 0),
                duplicate_reasons.get("source_url", 0),
                duplicate_reasons.get("fingerprint", 0),
                errors,
                status,
                run_id,
            ),
        )

        conn.commit()


def get_recent_processing_runs(
    limit: int = 10,
) -> list:

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM processing_runs
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    return rows