import html
import re
from dataclasses import dataclass
from typing import Literal


AbstractQuality = Literal[
    "missing",
    "metadata_only",
    "short",
    "usable",
]


@dataclass(frozen=True)
class AbstractQualityResult:
    quality: AbstractQuality
    text_length: int
    word_count: int
    metadata_signals: int
    title_overlap: float
    informative_text_length: int
    informative_word_count: int
    reason: str


WORD_REGEX = re.compile(
    r"\b[\w'-]+\b",
    flags=re.UNICODE,
)


HTML_TAG_REGEX = re.compile(
    r"<[^>]+>"
)


METADATA_SIGNAL_PATTERNS = [
    r"\bpublication date\s*:",
    r"\bpublished online\s*:",
    r"\bavailable online\b",
    r"\bsource\s*:",
    r"\bauthor\(s\)\s*:",
    r"\bvolume\s+\d+\b",
    r"\bissue\s+\d+\b",
    r"\bdoi\s*:",
]


METADATA_BLOCK_PATTERNS = [
    r"publication date\s*:[^.]+",
    r"source\s*:[^.]+",
    r"author\(s\)\s*:[^.]+",
]


def normalize_text(
    text: str | None,
) -> str:
    if not text:
        return ""

    text = html.unescape(
        text
    )

    text = HTML_TAG_REGEX.sub(
        " ",
        text,
    )

    text = html.unescape(
        text
    )

    return " ".join(
        text.strip().split()
    )


def get_words(
    text: str,
) -> list[str]:
    return WORD_REGEX.findall(
        text.lower()
    )


def metadata_signal_count(
    text: str,
) -> int:
    return sum(
        bool(
            re.search(
                pattern,
                text,
                flags=re.IGNORECASE,
            )
        )
        for pattern in METADATA_SIGNAL_PATTERNS
    )


def title_overlap_ratio(
    title: str | None,
    text: str,
) -> float:
    if not title:
        return 0.0

    title_words = set(
        get_words(title)
    )

    text_words = get_words(
        text
    )

    if not title_words or not text_words:
        return 0.0

    repeated = sum(
        word in title_words
        for word in text_words
    )

    return repeated / len(
        text_words
    )


def remove_title_repetition(
    text: str,
    title: str | None,
) -> str:
    """
    Remove an exact title repetition from the available
    RSS text.

    This is useful for feeds that provide metadata followed
    only by the article title.
    """

    if not title:
        return text

    normalized_title = normalize_text(
        title
    )

    if not normalized_title:
        return text

    if text.lower().endswith(
        normalized_title.lower()
    ):
        text = text[
            :-len(normalized_title)
        ].strip()

    return text


def extract_informative_text(
    abstract: str | None,
    title: str | None = None,
) -> str:
    """
    Remove obvious RSS bibliographic metadata and exact
    title repetition.

    The returned text is used only for quality assessment.
    The original abstract is never modified.
    """

    text = normalize_text(
        abstract
    )

    if not text:
        return ""

    # ScienceDirect-style metadata.
    for pattern in METADATA_BLOCK_PATTERNS:
        text = re.sub(
            pattern,
            " ",
            text,
            flags=re.IGNORECASE,
        )

    # Springer Nature-style prefix:
    #
    # Nature, Published online: 14 October 2026;
    # doi:10....
    text = re.sub(
        r"^[^.;]{0,100},?\s*"
        r"published online\s*:\s*"
        r"[^;]+;\s*",
        " ",
        text,
        flags=re.IGNORECASE,
    )

    text = re.sub(
        r"\bdoi\s*:\s*"
        r"10\.\d{4,9}/\S+",
        " ",
        text,
        flags=re.IGNORECASE,
    )

    text = " ".join(
        text.split()
    )

    text = remove_title_repetition(
        text=text,
        title=title,
    )

    return " ".join(
        text.split()
    )


def assess_abstract_quality(
    abstract: str | None,
    title: str | None = None,
) -> AbstractQualityResult:
    text = normalize_text(
        abstract
    )

    if not text:
        return AbstractQualityResult(
            quality="missing",
            text_length=0,
            word_count=0,
            metadata_signals=0,
            title_overlap=0.0,
            informative_text_length=0,
            informative_word_count=0,
            reason=(
                "No abstract or summary text is available."
            ),
        )

    words = get_words(
        text
    )

    metadata_signals = (
        metadata_signal_count(
            text
        )
    )

    title_overlap = (
        title_overlap_ratio(
            title=title,
            text=text,
        )
    )

    informative_text = (
        extract_informative_text(
            abstract=abstract,
            title=title,
        )
    )

    informative_words = get_words(
        informative_text
    )

    informative_word_count = len(
        informative_words
    )

    informative_text_length = len(
        informative_text
    )

    # Nothing meaningful remains after removing
    # metadata and exact title repetition.
    if informative_word_count < 5:
        return AbstractQualityResult(
            quality="metadata_only",
            text_length=len(text),
            word_count=len(words),
            metadata_signals=metadata_signals,
            title_overlap=title_overlap,
            informative_text_length=(
                informative_text_length
            ),
            informative_word_count=(
                informative_word_count
            ),
            reason=(
                "After removing bibliographic metadata "
                "and title repetition, almost no "
                "informative text remains."
            ),
        )

    # Very small teaser.
    if informative_word_count < 15:
        return AbstractQualityResult(
            quality="short",
            text_length=len(text),
            word_count=len(words),
            metadata_signals=metadata_signals,
            title_overlap=title_overlap,
            informative_text_length=(
                informative_text_length
            ),
            informative_word_count=(
                informative_word_count
            ),
            reason=(
                "Some informative text remains, but it "
                "contains fewer than 15 words."
            ),
        )

    # Short but potentially useful summary.
    if (
        informative_word_count < 60
        or informative_text_length < 350
    ):
        return AbstractQualityResult(
            quality="short",
            text_length=len(text),
            word_count=len(words),
            metadata_signals=metadata_signals,
            title_overlap=title_overlap,
            informative_text_length=(
                informative_text_length
            ),
            informative_word_count=(
                informative_word_count
            ),
            reason=(
                "The feed contains informative text, "
                "but substantially less than a typical "
                "scientific abstract."
            ),
        )

    return AbstractQualityResult(
        quality="usable",
        text_length=len(text),
        word_count=len(words),
        metadata_signals=metadata_signals,
        title_overlap=title_overlap,
        informative_text_length=(
            informative_text_length
        ),
        informative_word_count=(
            informative_word_count
        ),
        reason=(
            "Enough informative non-metadata text remains "
            "for semantic classification."
        ),
    )


def can_classify_with_llm(
    result: AbstractQualityResult,
) -> bool:
    return result.quality in {
        "short",
        "usable",
    }


def needs_enrichment(
    result: AbstractQualityResult,
) -> bool:
    return result.quality in {
        "missing",
        "metadata_only",
    }