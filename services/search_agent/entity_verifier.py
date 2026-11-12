from .meme_providers import vision_client
from .meme_deepseek import DeepSeekWeb
from .meme_types import PipelineError


def verify_entities(analysis, frames, settings, ledger):
    if not settings.verify_entities or not any(
        e.status in {"unknown", "uncertain"} or e.confidence < 0.8
        for e in analysis.entity_hypotheses
    ):
        return analysis, []
    warnings = []
    evidence = []
    try:
        query = " ".join(
            [
                # Keep the visual hypothesis within the search API's 128-char
                # limit; long observations previously truncated every name.
                " ".join(e.name for e in analysis.entity_hypotheses)[:64],
                *analysis.observations[:3],
                analysis.ocr_text,
            ]
        )[:128].strip()
        if not query:
            return analysis, ["entity_verification_no_visible_query"]
        evidence = DeepSeekWeb(settings, ledger).verify(query)
        if evidence:
            corrected = vision_client(settings, ledger).analyze(
                frames, analysis.user_text, evidence
            )
            # Provider adapter binds assessments to real retrieved IDs/URLs.
            corrected.sampled_frames = analysis.sampled_frames
            ledger.note(
                "entity_verification",
                before=[e.model_dump() for e in analysis.entity_hypotheses],
                after=[e.model_dump() for e in corrected.entity_hypotheses],
                evidence=corrected.evidence,
            )
            return corrected, warnings
    except PipelineError as exc:
        warnings.append(exc.code)
    analysis.evidence = evidence
    return analysis, warnings
