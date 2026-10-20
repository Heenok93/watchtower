"""Qualite, cache par article et interception des prompts effectifs."""
from storage.llm_audit_repository import start_attempt, update_attempt

QUALITY_RANK = {"missing": 0, "metadata_only": 1, "short": 2, "usable": 3}


def quality_improved(before, after):
    return (before.quality in QUALITY_RANK and after.quality in QUALITY_RANK
            and QUALITY_RANK[after.quality] > QUALITY_RANK[before.quality])


def prepare_article(article, *, enrich, assess):
    original = article.model_copy(deep=True)
    before = assess(abstract=original.abstract, title=original.title)
    used = original.model_copy(deep=True)
    matched = []
    error = None
    candidate_quality = None
    discarded = False
    attempted = before.quality != "usable"
    if attempted:
        try:
            candidate, results = enrich(original.model_copy(deep=True))
            matched = [r.provider for r in results if r.matched]
            candidate_quality = assess(abstract=candidate.abstract, title=candidate.title)
            old_rank = QUALITY_RANK.get(before.quality)
            new_rank = QUALITY_RANK.get(candidate_quality.quality)
            # Une qualite inconnue ou inferieure ne remplace pas le texte initial.
            discarded = old_rank is None or new_rank is None or new_rank < old_rank
            if not discarded:
                used = candidate.model_copy(deep=True)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
    after = assess(abstract=used.abstract, title=used.title)
    return used, {
        "quality_before": before.quality,
        "quality_after": after.quality,
        "informative_words_before": before.informative_word_count,
        "informative_words_after": after.informative_word_count,
        "quality_improved": quality_improved(before, after),
        "limited_information": after.quality != "usable",
        "enrichment_attempted": attempted,
        "enrichment_matched": bool(matched),
        "enrichment_providers": matched,
        "enrichment_error": error,
        "candidate_quality": None if candidate_quality is None else candidate_quality.quality,
        "candidate_discarded": discarded,
        "article_original": original.model_dump(mode="json"),
    }


class AuditedProvider:
    """Capture les arguments reels sans modifier le prompt du classifier."""
    def __init__(self, provider, *, context, article, profile, preparation):
        self.provider = provider
        self.context = context
        self.article = article
        self.profile = profile
        self.preparation = preparation
        self.attempt_id = None

    def __getattr__(self, name):
        return getattr(self.provider, name)

    def generate_structured(self, *, system_prompt, user_prompt, output_model):
        if self.attempt_id is not None:
            raise RuntimeError("One audited provider instance is required per classification")
        payload = {
            **self.preparation,
            "article_used": self.article.model_dump(mode="json"),
            "profile": self.profile.model_dump(mode="json"),
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "output_schema": output_model.model_json_schema(),
        }
        self.attempt_id = start_attempt(payload=payload, **self.context)
        try:
            result = self.provider.generate_structured(
                system_prompt=system_prompt, user_prompt=user_prompt,
                output_model=output_model,
            )
            update_attempt(self.attempt_id, "generated", result=result)
            return result
        except BaseException as exc:
            status = "interrupted" if isinstance(exc, (KeyboardInterrupt, SystemExit)) else "failed"
            try:
                update_attempt(self.attempt_id, status, error=f"{type(exc).__name__}: {exc}")
            except Exception as audit_exc:
                print(f"AUDIT UPDATE ERROR: {audit_exc}")
            raise
