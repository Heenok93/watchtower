import re


def normalize_doi(doi: str | None) -> str | None:

    if not doi:
        return None

    doi = doi.strip().lower()

    doi = re.sub(
        r"^https?://(dx\.)?doi\.org/",
        "",
        doi
    )

    return doi