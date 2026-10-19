from models.schemas import Article, TopicProfile
from models.llm_results import LLMResult
from providers.ollama_provider import OllamaProvider


SYSTEM_PROMPT = """
You are a scientific literature relevance classifier.

Your task is to evaluate whether a scientific article is genuinely
relevant to a specific scientific monitoring topic.

The article has already been processed by deterministic rules.
You are only reviewing an ambiguous case.

Base your decision only on the article title and abstract provided.

Do not assume information that is not present in the article.

A relevant article must substantively address the scientific topic.
A superficial keyword match is not sufficient.

Return:
- relevant: true if the article is scientifically relevant to the topic,
  otherwise false.
- confidence: your confidence in the decision, between 0 and 1.
- reason: a concise explanation of the relevance decision.
- summary: a concise summary of the article based only on the provided
  title and abstract.

If the abstract is missing or provides insufficient information,
be conservative in your relevance decision and confidence score.
""".strip()


def _format_terms(terms: list[str]) -> str:
    """
    Convert a list of terms into a readable bullet list.
    """

    if not terms:
        return "- None"

    return "\n".join(f"- {term}" for term in terms)


def _format_required_groups(profile: TopicProfile) -> str:
    """
    Convert the topic profile required groups into readable text
    for the LLM prompt.
    """

    if not profile.required_groups:
        return "None"

    sections = []

    for group_name, group in profile.required_groups.items():
        section = (
            f"{group_name}:\n"
            f"{_format_terms(group.terms)}"
        )
        sections.append(section)

    return "\n\n".join(sections)


def build_user_prompt(
    article: Article,
    profile: TopicProfile,
) -> str:
    """
    Build the scientific classification prompt for one
    article/topic pair.
    """

    title = article.title or "Not available"
    abstract = article.abstract or "Not available"

    required_groups = _format_required_groups(profile)

    return f"""
SCIENTIFIC MONITORING TOPIC

Topic ID:
{profile.id}

Topic name:
{profile.name}

Topic description:
{profile.description}

The deterministic filter defines the following concept groups.
The article should substantively fit the scientific topic represented
by these groups.

Required concept groups:

{required_groups}


ARTICLE TO EVALUATE

Title:
{title}

Abstract:
{abstract}


TASK

Determine whether this article is genuinely relevant to the scientific
monitoring topic above.

Do not classify the article as relevant solely because individual
keywords happen to appear.

Consider the scientific meaning and relationship between the concepts
in the article.
""".strip()


def classify_article(
    article: Article,
    profile: TopicProfile,
    provider: OllamaProvider,
) -> LLMResult:
    """
    Classify one article against one topic profile using an LLM.

    The function does not persist anything to the database.
    It only performs scientific classification and returns
    a validated LLMResult.
    """

    user_prompt = build_user_prompt(
        article=article,
        profile=profile,
    )

    return provider.generate_structured(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        output_model=LLMResult,
    )