from storage.run_repository import (
    get_recent_processing_runs,
)


def main():
    runs = get_recent_processing_runs(
        limit=10
    )

    if not runs:
        print(
            "No processing runs found."
        )
        return

    for run in runs:
        print("=" * 60)
        print(f"Run ID: {run['id']}")
        print(f"Source: {run['source']}")
        print(f"Started: {run['started_at']}")
        print(f"Finished: {run['finished_at']}")
        print(f"Found: {run['items_found']}")
        print(f"Inserted: {run['items_inserted']}")

        print(
            f"Duplicates DOI: "
            f"{run['duplicates_doi']}"
        )

        print(
            f"Duplicates PMID: "
            f"{run['duplicates_pmid']}"
        )

        print(
            f"Duplicates URL: "
            f"{run['duplicates_source_url']}"
        )

        print(
            f"Duplicates fingerprint: "
            f"{run['duplicates_fingerprint']}"
        )

        print(f"Errors: {run['errors']}")
        print(f"Status: {run['status']}")


if __name__ == "__main__":
    main()