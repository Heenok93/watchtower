"""Filtre deterministe V2.1 : signaux forts et ponts secondaires."""
import re
import unicodedata
from functools import lru_cache

from models.schemas import Article, FilterResult, TopicProfile


def normalize_filter_text(text: str | None) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


# Known journal/platform boilerplate observed at the beginning of abstracts.
# Applied only when a profile explicitly enables strip_editorial_prefixes.
_EDITORIAL_PREFIX_PATTERNS = (
    re.compile(
        r"^\s*DIGITAL\s+HEALTH,\s*Volume\s+\d+\s*,\s*[^.]{1,100}\.\s*",
        flags=re.IGNORECASE,
    ),
)


def article_search_text(
    article: Article,
    profile: TopicProfile | None = None,
) -> str:
    abstract = article.abstract or ""
    if profile is not None and profile.strip_editorial_prefixes:
        for pattern in _EDITORIAL_PREFIX_PATTERNS:
            abstract = pattern.sub("", abstract, count=1)
    return normalize_filter_text(" ".join([article.title, abstract]))


@lru_cache(maxsize=8192)
def _compiled_term_pattern(normalized_term: str) -> re.Pattern[str]:
    return re.compile(
        r"(?<![a-z0-9])"
        + re.escape(normalized_term)
        + r"(?![a-z0-9])"
    )


@lru_cache(maxsize=8192)
def _normalized_term(term: str) -> str:
    return normalize_filter_text(term)


def find_matches(text: str, terms: list[str]) -> list[str]:
    matches = []
    for term in terms:
        normalized_term = _normalized_term(term)
        if not normalized_term:
            continue
        if _compiled_term_pattern(normalized_term).search(text):
            matches.append(term)
    return matches


def match_required_groups(
    text: str,
    profile: TopicProfile,
) -> dict[str, list[str]]:
    return {
        name: find_matches(text, group.terms)
        for name, group in profile.required_groups.items()
    }


def match_secondary_groups(
    text: str,
    profile: TopicProfile,
) -> dict[str, list[str]]:
    unknown_groups = set(profile.secondary_groups) - set(profile.required_groups)
    if unknown_groups:
        raise ValueError(
            f"Profil '{profile.id}' : groupes secondaires inconnus : "
            + ", ".join(sorted(unknown_groups))
        )
    return {
        name: find_matches(text, group.terms)
        for name, group in profile.secondary_groups.items()
    }


def count_matched_required_groups(matches: dict[str, list[str]]) -> int:
    return sum(bool(terms) for terms in matches.values())


def all_required_groups_satisfied(matches: dict[str, list[str]]) -> bool:
    # Comportement historique conserve pour les profils sans groupes requis.
    return all(bool(terms) for terms in matches.values())


def has_cross_group_signal(matches: dict[str, list[str]]) -> bool:
    """Fonction historique conservee, non utilisee dans la decision V2.1."""
    if not matches:
        return True
    minimum = 1 if len(matches) == 1 else 2
    return count_matched_required_groups(matches) >= minimum


def has_secondary_bridge(
    required_matches: dict[str, list[str]],
    secondary_matches: dict[str, list[str]],
) -> bool:
    """Exige tous les groupes forts sauf un, puis un signal dans le manquant."""
    if len(required_matches) < 2:
        return False
    if count_matched_required_groups(required_matches) == 0:
        return False
    missing_groups = [
        name for name, terms in required_matches.items() if not terms
    ]
    if len(missing_groups) != 1:
        return False
    return bool(secondary_matches.get(missing_groups[0], []))


def filter_article(article: Article, profile: TopicProfile) -> FilterResult:
    text = article_search_text(article, profile)

    matched_include = find_matches(text, profile.include.any)
    matched_context = find_matches(text, profile.include.context)
    matched_priority = find_matches(text, profile.priority.high)
    matched_exclude = find_matches(text, profile.exclude.any)
    matched_required_groups = match_required_groups(text, profile)
    matched_secondary_groups = match_secondary_groups(text, profile)

    required_groups_satisfied = all_required_groups_satisfied(
        matched_required_groups
    )
    secondary_bridge = has_secondary_bridge(
        matched_required_groups,
        matched_secondary_groups,
    )

    # Chaque famille contribue une fois. Les secondaires ne changent pas le score.
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
        minimum_score = profile.min_candidate_score_for_candidate
        if minimum_score is not None and score < minimum_score:
            decision = profile.low_score_candidate_decision
        else:
            decision = "candidate"
    elif secondary_bridge:
        decision = "llm_review"
    else:
        decision = "reject"

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
