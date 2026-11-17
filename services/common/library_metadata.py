from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

Tag = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]
Tags = Annotated[list[Tag], Field(max_length=8)]
CATEGORIES = ("subject_tags", "action_tags", "emotion_tags", "tone_tags")


class Annotation(BaseModel):
    ocr_text: str = Field(max_length=2000)
    ocr_uncertain: bool = False
    caption_zh: str = Field(max_length=300)
    caption_en: str | None = Field(default=None, max_length=300)
    subject_tags: Tags
    action_tags: Tags
    emotion_tags: Tags
    tone_tags: Tags = Field(default_factory=list)


class MetadataEdit(BaseModel):
    title: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
        | None
    ) = None
    tags: Tags | None = None
    subject_tags: Tags | None = None
    action_tags: Tags | None = None
    emotion_tags: Tags | None = None
    tone_tags: Tags | None = None
    ocr_text: str | None = Field(default=None, max_length=2000)


def annotation_version(model: str) -> str:
    return f"hkust/{model}/library-prompt-v1/playback-midpoints-v1"


def effective_labels(manual: dict, annotation: dict) -> dict:
    return {key: manual.get(key, annotation.get(key, [])) for key in CATEGORIES}
