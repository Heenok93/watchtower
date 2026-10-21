"""
WATCHTOWER - Complete pipeline orchestrator.

Runs:

1. database initialization or controlled reset;
2. RSS collection;
3. deterministic filtering;
4. optional LLM classification;
5. Markdown digest generation;
6. CSV export for manual review.

Examples:

    python main.py
    python main.py --skip-llm
    python main.py --llm-limit 5
    python main.py --fresh --llm-limit 5
    python main.py --include-llm-rejected
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import run_llm

from storage.database import (
    DB_PATH,
    init_database,
)
from storage.llm_audit_repository import (
    initialize_audit,
)


BASE_DIR = Path(__file__).resolve().parent
OUTPUTS_DIR = BASE_DIR / "outputs"
BACKUPS_DIR = BASE_DIR / "storage" / "backups"


def timestamp() -> str:
    """
    Return a filesystem-friendly timestamp.
    """
    return datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )


def display_path(
    path: Path,
) -> str:
    """
    Display project-relative paths when possible.
    """
    try:
        return str(
            path.resolve().relative_to(
                BASE_DIR.resolve()
            )
        )
    except ValueError:
        return str(
            path.resolve()
        )


def run_command(
    label: str,
    command: list[str],
) -> None:
    """
    Run one blocking pipeline command.

    A non-zero exit code is considered a blocking error.
    """
    print()
    print("=" * 80)
    print(label)
    print("=" * 80)
    print(
        "Command: "
        + " ".join(command)
    )
    print()

    completed = subprocess.run(
        command,
        cwd=BASE_DIR,
        check=False,
    )

    if completed.returncode != 0:
        raise RuntimeError(
            f"{label} failed with exit code "
            f"{completed.returncode}."
        )

    print()
    print(
        f"{label}: success"
    )


def backup_and_reset_database(
    run_timestamp: str,
) -> Path | None:
    """
    Back up the active database, delete it, and recreate
    the complete current schema.

    The reset occurs only when --fresh is explicitly used.
    """
    backup_path = None

    if DB_PATH.exists():
        BACKUPS_DIR.mkdir(
            parents=True,
            exist_ok=True,
        )

        backup_path = (
            BACKUPS_DIR
            / f"watchtower_{run_timestamp}.db"
        )

        if backup_path.exists():
            raise FileExistsError(
                f"Database backup already exists: "
                f"{backup_path}"
            )

        shutil.copy2(
            DB_PATH,
            backup_path,
        )

        print(
            f"Database backup: "
            f"{display_path(backup_path)}"
        )

        DB_PATH.unlink()

        print(
            f"Removed active database: "
            f"{display_path(DB_PATH)}"
        )

    else:
        print(
            "No existing database to back up."
        )

    init_database()
    initialize_audit()

    print(
        f"Fresh database initialized: "
        f"{display_path(DB_PATH)}"
    )

    return backup_path


def ensure_database() -> None:
    """
    Initialize missing database schema elements without
    deleting existing data.
    """
    init_database()
    initialize_audit()


def run_llm_step(
    limit: int | None,
) -> tuple[str, dict[str, Any]]:
    """
    Run the LLM classification step directly.

    Direct invocation preserves the structured summary returned
    by run_llm.main(), including interruption, errors, processed
    pairs, and the remaining queue.
    """
    print()
    print("=" * 80)
    print("LLM CLASSIFICATION")
    print("=" * 80)
    print()

    summary = run_llm.main(
        limit=limit
    )

    if summary["interrupted"]:
        status = "interrupted"

    elif summary["errors"]:
        status = "completed_with_errors"

    elif (
        summary[
            "remaining_from_initial_queue"
        ]
        > 0
    ):
        status = "partially_completed"

    else:
        status = "completed"

    return status, summary


def print_llm_pipeline_summary(
    summary: dict[str, Any],
) -> None:
    """
    Print the LLM section of the final pipeline summary.
    """
    print(
        f"{'LLM run ID:':<28}"
        f"{summary['run_id']}"
    )

    print(
        f"{'LLM initial queue:':<28}"
        f"{summary['queue_size']}"
    )

    print(
        f"{'LLM selected this run:':<28}"
        f"{summary['selected_count']}"
    )

    print(
        f"{'LLM processed:':<28}"
        f"{summary['processed']}"
    )

    print(
        f"{'LLM relevant:':<28}"
        f"{summary['relevant']}"
    )

    print(
        f"{'LLM not relevant:':<28}"
        f"{summary['not_relevant']}"
    )

    print(
        f"{'LLM errors:':<28}"
        f"{summary['errors']}"
    )

    print(
        f"{'LLM audit warnings:':<28}"
        f"{summary['audit_warnings']}"
    )

    print(
        f"{'LLM limited information:':<28}"
        f"{summary['limited_information']}"
    )

    print(
        f"{'LLM remaining:':<28}"
        f"{summary['remaining_from_initial_queue']}"
    )

    print(
        f"{'LLM interrupted:':<28}"
        f"{summary['interrupted']}"
    )


def build_parser() -> argparse.ArgumentParser:
    """
    Build the command-line argument parser.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Run the complete Watchtower pipeline."
        )
    )

    parser.add_argument(
        "--fresh",
        action="store_true",
        help=(
            "Back up and delete the current database "
            "before running the pipeline."
        ),
    )

    parser.add_argument(
        "--skip-llm",
        action="store_true",
        help=(
            "Skip LLM classification and generate "
            "outputs with pending review items."
        ),
    )

    parser.add_argument(
        "--llm-limit",
        type=int,
        default=None,
        help=(
            "Maximum number of pending LLM review "
            "pairs processed during this run."
        ),
    )

    parser.add_argument(
        "--include-llm-rejected",
        action="store_true",
        help=(
            "Include LLM-rejected article/topic pairs "
            "in the CSV export."
        ),
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help=(
            "Output directory. By default, an "
            "automatically timestamped directory is "
            "created under outputs/."
        ),
    )

    return parser


def resolve_output_directory(
    requested_path: Path | None,
    run_timestamp: str,
) -> Path:
    """
    Resolve and validate the output directory.

    A new directory is required to prevent accidental
    replacement of previous exports and manual annotations.
    """
    if requested_path is None:
        output_dir = (
            OUTPUTS_DIR
            / f"run_{run_timestamp}"
        )

    elif requested_path.is_absolute():
        output_dir = requested_path

    else:
        output_dir = (
            BASE_DIR
            / requested_path
        )

    output_dir.mkdir(
        parents=True,
        exist_ok=False,
    )

    return output_dir


def main() -> int:
    """
    Run the complete Watchtower pipeline.

    Returns
    -------
    int
        Process exit code.
    """
    parser = build_parser()
    args = parser.parse_args()

    if (
        args.llm_limit is not None
        and args.llm_limit < 1
    ):
        parser.error(
            "--llm-limit must be at least 1."
        )

    if (
        args.skip_llm
        and args.llm_limit is not None
    ):
        parser.error(
            "--skip-llm and --llm-limit "
            "cannot be used together."
        )

    run_timestamp = timestamp()

    try:
        output_dir = resolve_output_directory(
            requested_path=args.output_dir,
            run_timestamp=run_timestamp,
        )

    except Exception as exc:
        print(
            "OUTPUT DIRECTORY ERROR: "
            f"{type(exc).__name__}: {exc}"
        )

        return 1

    digest_path = (
        output_dir
        / "watchtower_digest.md"
    )

    csv_path = (
        output_dir
        / "watchtower_articles.csv"
    )

    print("=" * 80)
    print("WATCHTOWER COMPLETE PIPELINE")
    print("=" * 80)

    print(
        f"{'Run timestamp:':<24}"
        f"{run_timestamp}"
    )

    print(
        f"{'Database:':<24}"
        f"{display_path(DB_PATH)}"
    )

    print(
        f"{'Output folder:':<24}"
        f"{display_path(output_dir)}"
    )

    print(
        f"{'Fresh mode:':<24}"
        f"{args.fresh}"
    )

    print(
        f"{'Skip LLM:':<24}"
        f"{args.skip_llm}"
    )

    print(
        f"{'LLM limit:':<24}"
        f"{args.llm_limit}"
    )

    print(
        f"{'CSV includes rejects:':<24}"
        f"{args.include_llm_rejected}"
    )

    backup_path = None
    llm_status = "skipped"
    llm_summary = None

    collection_status = "not_started"
    filter_status = "not_started"
    digest_status = "not_started"
    csv_status = "not_started"

    try:
        if args.fresh:
            print()
            print("=" * 80)
            print("DATABASE RESET")
            print("=" * 80)

            backup_path = (
                backup_and_reset_database(
                    run_timestamp
                )
            )

        else:
            ensure_database()

        run_command(
            label="RSS COLLECTION",
            command=[
                sys.executable,
                "run_collect.py",
            ],
        )

        collection_status = "success"

        run_command(
            label="DETERMINISTIC FILTER",
            command=[
                sys.executable,
                "run_filter.py",
            ],
        )

        filter_status = "success"

        if not args.skip_llm:
            (
                llm_status,
                llm_summary,
            ) = run_llm_step(
                limit=args.llm_limit,
            )

        run_command(
            label="MARKDOWN DIGEST",
            command=[
                sys.executable,
                "generate_digest.py",
                "--output",
                str(digest_path),
            ],
        )

        digest_status = "success"

        csv_command = [
            sys.executable,
            "export_articles_csv.py",
            "--output",
            str(csv_path),
        ]

        if args.include_llm_rejected:
            csv_command.append(
                "--include-llm-rejected"
            )

        run_command(
            label="CSV EXPORT",
            command=csv_command,
        )

        csv_status = "success"

    except KeyboardInterrupt:
        print()
        print("=" * 80)
        print("WATCHTOWER PIPELINE INTERRUPTED")
        print("=" * 80)

        print(
            "The pipeline was interrupted outside "
            "the managed LLM classification loop."
        )

        print(
            "Completed database writes and outputs "
            "have been retained."
        )

        return 130

    except Exception as exc:
        print()
        print("=" * 80)
        print("WATCHTOWER PIPELINE FAILED")
        print("=" * 80)

        print(
            f"{type(exc).__name__}: "
            f"{exc}"
        )

        print(
            "Completed database writes and outputs "
            "have been retained."
        )

        return 1

    print()
    print("=" * 80)
    print("WATCHTOWER PIPELINE SUMMARY")
    print("=" * 80)

    print(
        f"{'Collection:':<28}"
        f"{collection_status}"
    )

    print(
        f"{'Deterministic filter:':<28}"
        f"{filter_status}"
    )

    print(
        f"{'LLM:':<28}"
        f"{llm_status}"
    )

    if llm_summary is not None:
        print_llm_pipeline_summary(
            llm_summary
        )

    print(
        f"{'Markdown digest:':<28}"
        f"{digest_status}"
    )

    print(
        f"{'CSV export:':<28}"
        f"{csv_status}"
    )

    print(
        f"{'Digest file:':<28}"
        f"{display_path(digest_path)}"
    )

    print(
        f"{'CSV file:':<28}"
        f"{display_path(csv_path)}"
    )

    if backup_path is not None:
        print(
            f"{'Database backup:':<28}"
            f"{display_path(backup_path)}"
        )

    print(
        f"{'Active database:':<28}"
        f"{display_path(DB_PATH)}"
    )

    print("=" * 80)

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
