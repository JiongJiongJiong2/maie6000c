"""Results shared between the web finder and the isolated sticker lookup service."""

from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator

MAX_SCREENSHOT_BYTES = 5 * 1024 * 1024
LOOKUP_SECONDS = 55


class StickerSource(BaseModel):
    title: str = Field(min_length=1, max_length=250)
    url: HttpUrl
    channel: str = Field(default="", max_length=80)
    publisher: str = Field(default="", max_length=150)
    evidence_url: HttpUrl | None = None
    match_basis: Literal["artwork", "text"] = "artwork"

    @field_validator("url", "evidence_url")
    @classmethod
    def require_https(cls, value):
        if value and (value.scheme != "https" or value.username or value.password):
            raise ValueError("Public sticker sources must use HTTPS")
        return value


class WebStickerSearch(BaseModel):
    state: Literal["matched", "candidates", "no_match", "unavailable", "busy"]
    links: list[StickerSource] = Field(default_factory=list, max_length=3)
    leads: list[StickerSource] = Field(default_factory=list, max_length=5)
