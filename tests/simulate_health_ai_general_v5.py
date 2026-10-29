from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml


def find_project_root(start: Path) -> Path:
    """Find the Watchtower root without assuming a fixed script location."""
    for candidate in (start, *start.parents):
        if (
            (candidate / "models" / "schemas.py").is_file()
            and (candidate / "processing" / "deterministic_filter.py").is_file()
            and (candidate / "config" / "topics").is_dir()
        ):
            return candidate
    raise RuntimeError(
        "Impossible de trouver la racine Watchtower. Un dossier parent doit "
        "contenir models/schemas.py, processing/deterministic_filter.py et "
        "config/topics/."
    )


def text_or_none(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value if value else None


def json_cell(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def first_existing_column(row: dict[str, str], *names: str) -> str | None:
    for name in names:
        value = row.get(name)
        if value is not None and value != "":
            return value
    return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Simule le filtre Health & AI General v5 sur un CSV existant, "
            "sans pandas et sans modifier la base Watchtower."
        )
    )
    parser.add_argument(
        "--input",
        default="health_ai_general_v4_simulation.csv",
        help="CSV d'entrée (séparateur ';', UTF-8-SIG).",
    )
    parser.add_argument(
        "--yaml",
        default=None,
        help=(
            "YAML à tester. Par défaut : "
            "config/topics/health_ai_general_candidate_v5.yaml."
        ),
    )
    parser.add_argument(
        "--output",
        default="health_ai_general_v5_simulation.csv",
        help="CSV de sortie. Les colonnes v3/v4 existantes sont conservées.",
    )
    parser.add_argument(
        "--version",
        default="v5",
        choices=("v5", "v6", "test"),
        help="Préfixe des colonnes ajoutées (défaut : v5).",
    )
    args = parser.parse_args()

    base = find_project_root(Path(__file__).resolve().parent)
    sys.path.insert(0, str(base))

    from models.schemas import Article, TopicProfile
    from processing.deterministic_filter import filter_article

    csv_in = Path(args.input).expanduser().resolve()
    yaml_in = (
        Path(args.yaml).expanduser().resolve()
        if args.yaml
        else base / "config" / "topics" / "health_ai_general_candidate_v5.yaml"
    )
    csv_out = Path(args.output).expanduser().resolve()

    if not csv_in.is_file():
        print(f"ERREUR : CSV d'entrée introuvable : {csv_in}", file=sys.stderr)
        print("Utilise --input pour fournir le chemin correct.", file=sys.stderr)
        return 2
    if not yaml_in.is_file():
        print(f"ERREUR : YAML introuvable : {yaml_in}", file=sys.stderr)
        return 2

    with csv_in.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        if not reader.fieldnames:
            raise ValueError(f"CSV vide ou sans en-tête : {csv_in}")
        fieldnames = list(reader.fieldnames)
        input_rows = list(reader)

    required_columns = {
        "title", "abstract", "source", "journal", "doi", "pmid", "source_url"
    }
    missing_columns = sorted(required_columns - set(fieldnames))
    if missing_columns:
        raise ValueError(
            "Colonnes nécessaires absentes du CSV : " + ", ".join(missing_columns)
        )

    profile_data = yaml.safe_load(yaml_in.read_text(encoding="utf-8"))
    profile = TopicProfile.model_validate(profile_data)

    version = args.version
    result_fields = {
        f"{version}_filter_score": lambda result: result.score,
        f"{version}_decision": lambda result: result.decision,
        f"{version}_required_groups_satisfied": lambda result: result.required_groups_satisfied,
        f"{version}_matched_include": lambda result: json_cell(result.matched_include),
        f"{version}_matched_context": lambda result: json_cell(result.matched_context),
        f"{version}_matched_priority": lambda result: json_cell(result.matched_priority),
        f"{version}_matched_exclude": lambda result: json_cell(result.matched_exclude),
        f"{version}_matched_required_groups": lambda result: json_cell(result.matched_required_groups),
    }

    output_rows = []
    decisions = Counter()
    scores = Counter()
    transitions: dict[str, Counter] = defaultdict(Counter)
    transition_source = None

    for row_number, row in enumerate(input_rows, start=2):
        article = Article(
            title=text_or_none(row.get("title")) or "",
            abstract=text_or_none(row.get("abstract")),
            source=text_or_none(row.get("source")) or "unknown",
            journal=text_or_none(row.get("journal")),
            doi=text_or_none(row.get("doi")),
            pmid=text_or_none(row.get("pmid")),
            source_url=text_or_none(row.get("source_url")),
            publication_date=None,
        )
        try:
            result = filter_article(article, profile)
        except Exception as exc:
            raise RuntimeError(
                f"Erreur de simulation à la ligne CSV {row_number}: "
                f"{type(exc).__name__}: {exc}"
            ) from exc

        # Les colonnes v3/v4 sont laissées intactes ; seules les colonnes v5_* sont ajoutées.
        for column, getter in result_fields.items():
            row[column] = str(getter(result)) if column.endswith(("_score", "_decision", "_satisfied")) else getter(result)

        output_rows.append(row)
        decisions[str(result.decision)] += 1
        scores[str(result.score)] += 1

        # Préférer v4 pour comparer v4 -> v5 ; sinon retomber sur v3.
        old_decision = first_existing_column(
            row, "v4_decision", "v3_decision", "deterministic_decision"
        )
        if old_decision:
            if transition_source is None:
                transition_source = (
                    "v4_decision" if row.get("v4_decision") else
                    "v3_decision" if row.get("v3_decision") else
                    "deterministic_decision"
                )
            transitions[old_decision][str(result.decision)] += 1

    output_fields = list(fieldnames)
    for column in result_fields:
        if column not in output_fields:
            output_fields.append(column)

    csv_out.parent.mkdir(parents=True, exist_ok=True)
    with csv_out.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=output_fields,
            delimiter=";",
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(output_rows)

    print("Racine du projet :", base)
    print("CSV d'entrée     :", csv_in)
    print("YAML utilisé     :", yaml_in)
    print("Nombre de lignes :", len(input_rows))
    print(f"Décisions {version} :", dict(sorted(decisions.items())))
    print(
        f"Scores {version}    :",
        dict(sorted(scores.items(), key=lambda item: int(item[0]))),
    )

    if transitions:
        print(f"Matrice de transition {transition_source} -> {version}_decision :")
        old_labels = sorted(transitions)
        new_labels = sorted(
            {decision for per_old in transitions.values() for decision in per_old}
        )
        print(transition_source.ljust(24) + "".join(label.rjust(24) for label in new_labels))
        for old in old_labels:
            line = old.ljust(24)
            line += "".join(
                str(transitions[old].get(new, 0)).rjust(24) for new in new_labels
            )
            print(line)
    else:
        print("Aucune colonne de décision antérieure trouvée pour la matrice de transition.")

    print("CSV de sortie    :", csv_out)
    print("La base Watchtower n'a pas été modifiée.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
