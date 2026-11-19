#!/usr/bin/env python3
"""Apply human label corrections from a Watchtower CSV/XLSX export.

Only consolidated labels are adjudicated. Scores and raw System 1/System 2
predictions are never changed: updates go through adjudicate_article.adjudicate().

Expected columns:
  article_id
  correction                 optional; only rows equal to 1 are processed
  <label>_label              current exported label
  corr_<dimension>           desired human label; blank means do not touch

Supported corrections:
  corr_ai       -> ai_relevant
  corr_health   -> health_relevant
  corr_agentic  -> agentic_ai_health
  corr_digit    -> digital_health_ai
  corr_clinic   -> clinical_medicine_ai
  corr_lab      -> laboratory_ai
  corr_epi      -> epidemics_public_health_ai
  corr_drug     -> drug_development_ai
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Any

from adjudicate_article import adjudicate

CORRECTION_COLUMNS = {
    "corr_ai": ("ai_relevant", "ai_relevant_label"),
    "corr_health": ("health_relevant", "health_relevant_label"),
    "corr_agentic": ("agentic_ai_health", "agentic_ai_health_label"),
    "corr_digit": ("digital_health_ai", "digital_health_ai_label"),
    "corr_clinic": ("clinical_medicine_ai", "clinical_medicine_ai_label"),
    "corr_lab": ("laboratory_ai", "laboratory_ai_label"),
    "corr_epi": ("epidemics_public_health_ai", "epidemics_public_health_ai_label"),
    "corr_drug": ("drug_development_ai", "drug_development_ai_label"),
}

TRUE_VALUES = {"1", "true", "t", "yes", "y", "oui", "vrai"}
FALSE_VALUES = {"0", "false", "f", "no", "n", "non", "faux"}


def parse_bool(value: Any, *, allow_blank: bool = True) -> bool | None:
    if value is None:
        return None if allow_blank else False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    text = str(value).strip().lower()
    if not text:
        return None if allow_blank else False
    if text in TRUE_VALUES:
        return True
    if text in FALSE_VALUES:
        return False
    raise ValueError(f"Not a boolean value: {value!r}")


def load_rows(path: Path) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    if suffix == ".xlsx":
        try:
            from openpyxl import load_workbook
        except ImportError as exc:
            raise RuntimeError("Reading .xlsx requires openpyxl. Export the sheet as CSV instead.") from exc
        wb = load_workbook(path, read_only=True, data_only=True)
        ws = wb.active
        values = ws.iter_rows(values_only=True)
        headers = [str(v).strip() if v is not None else "" for v in next(values)]
        return [dict(zip(headers, row)) for row in values]
    raise ValueError("Input must be .csv or .xlsx")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Annotated Watchtower .csv or .xlsx")
    parser.add_argument("--reviewer", default="Thomas ROEDERER")
    parser.add_argument(
        "--reason",
        default="Human review of Watchtower digest/export: corrected consolidated label",
    )
    parser.add_argument(
        "--all-rows",
        action="store_true",
        help="Process all rows, not only correction=1 rows",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show planned label changes without writing to the database",
    )
    args = parser.parse_args()

    rows = load_rows(args.input)
    if not rows:
        print("No rows found.")
        return 0
    if "article_id" not in rows[0]:
        raise ValueError("Missing required column: article_id")

    planned = 0
    applied = 0
    unchanged = 0
    errors = 0

    for line_no, row in enumerate(rows, start=2):
        try:
            if not args.all_rows and "correction" in row:
                flagged = parse_bool(row.get("correction"))
                if flagged is not True:
                    continue

            article_id = int(row["article_id"])
            for corr_col, (dimension, exported_label_col) in CORRECTION_COLUMNS.items():
                if corr_col not in row:
                    continue
                desired = parse_bool(row.get(corr_col))
                if desired is None:  # blank explicitly means do not alter this dimension
                    continue

                current = None
                if exported_label_col in row:
                    current = parse_bool(row.get(exported_label_col))
                if current is not None and current == desired:
                    unchanged += 1
                    continue

                planned += 1
                decision = "true" if desired else "false"
                print(f"article={article_id}  {dimension}: {current} -> {desired}")
                if not args.dry_run:
                    revision = adjudicate(
                        article_id=article_id,
                        dimension=dimension,
                        decision=decision,
                        reason=args.reason,
                        reviewer=args.reviewer,
                    )
                    applied += 1
                    print(f"  saved revision={revision}")
        except Exception as exc:
            errors += 1
            print(f"ERROR row={line_no} article={row.get('article_id')!r}: {exc}")

    print("\nSummary")
    print(f"  planned changes : {planned}")
    print(f"  applied changes : {applied}")
    print(f"  already matching: {unchanged}")
    print(f"  errors          : {errors}")
    if args.dry_run:
        print("  DRY RUN: database was not modified")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
