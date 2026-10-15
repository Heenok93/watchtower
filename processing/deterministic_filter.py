import re
import unicodedata

from models.schemas import (
    Article,
    FilterResult,
    TopicProfile,
)


def normalize_filter_text(
    text: str | None,
) -> str:
    if not text:
        return ""

    text = unicodedata.normalize(
        "NFKD",
        text,
    )

    text = "".join(
        char
        for char in text
        if not unicodedata.combining(char)
    )

    text = text.lower()

    text = re.sub(
        r"[^a-z0-9]+",
        " ",
        text,
    )

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip()


def article_search_text(
    article: Article,
) -> str:
    parts = [
        article.title,
        article.abstract or "",
    ]

    return normalize_filter_text(
        " ".join(parts)
    )


def find_matches(
    text: str,
    terms: list[str],
) -> list[str]:
    matches = []

    for term in terms:
        normalized_term = normalize_filter_text(
            term
        )

        if not normalized_term:
            continue

        pattern = (
            r"(?<![a-z0-9])"
            + re.escape(normalized_term)
            + r"(?![a-z0-9])"
        )

        if re.search(pattern, text):
            matches.append(term)

    return matches


def match_required_groups(
    text: str,
    profile: TopicProfile,
) -> dict[str, list[str]]:
    matches = {}

    for group_name, group in profile.required_groups.items():
        matches[group_name] = find_matches(
            text,
            group.terms,
        )

    return matches


def all_required_groups_satisfied(
    matches: dict[str, list[str]],
) -> bool:
    if not matches:
        return True

    return all(
        len(group_matches) > 0
        for group_matches in matches.values()
    )


def filter_article(
    article: Article,
    profile: TopicProfile,
) -> FilterResult:
    text = article_search_text(article)

    matched_include = find_matches(
        text,
        profile.include.any,
    )

    matched_context = find_matches(
        text,
        profile.include.context,
    )

    matched_priority = find_matches(
        text,
        profile.priority.high,
    )

    matched_exclude = find_matches(
        text,
        profile.exclude.any,
    )

    matched_required_groups = match_required_groups(
        text,
        profile,
    )

    required_groups_satisfied = (
        all_required_groups_satisfied(
            matched_required_groups
        )
    )

    score = 0

    if matched_include:
        score += profile.scoring.include_match

    if matched_context:
        score += profile.scoring.context_match

    if matched_priority:
        score += profile.scoring.priority_match

    if matched_exclude:
        score += profile.scoring.exclude_match

    if matched_exclude:
        decision = "reject"

    elif required_groups_satisfied:
        decision = "candidate"

    elif score < profile.thresholds.reject_below:
        decision = "reject"

    else:
        decision = "llm_review"

    return FilterResult(
        topic_id=profile.id,
        score=score,
        decision=decision,
        matched_include=matched_include,
        matched_context=matched_context,
        matched_priority=matched_priority,
        matched_exclude=matched_exclude,
        matched_required_groups=matched_required_groups,
        required_groups_satisfied=required_groups_satisfied,
    )