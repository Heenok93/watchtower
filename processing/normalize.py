import re


def normalize_doi(doi: str | None) -> str | None:
    """Return a canonical DOI without a doi.org URL prefix."""
    if not doi:
        return None

    value = doi.strip().lower()
    value = re.sub(r"^https?://(dx\.)?doi\.org/", "", value)
    value = value.strip()
    return value or None


def normalize_pmid(pmid: str | None) -> str | None:
    """Return a PMID without common labels or PubMed URL wrappers."""
    if not pmid:
        return None

    value = pmid.strip()
    value = re.sub(
        r"^https?://pubmed\.ncbi\.nlm\.nih\.gov/",
        "",
        value,
        flags=re.IGNORECASE,
    ).strip("/")
    value = re.sub(r"^PMID:\s*", "", value, flags=re.IGNORECASE)
    return value or None
