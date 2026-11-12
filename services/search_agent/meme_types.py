"""meme50-v2 contracts; legacy three-GIF contracts remain unchanged."""

import time
from threading import Lock
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, AliasChoices, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from services.common.media import MediaMetadata
from services.search_agent.models import Source, Candidate


class MemeSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", env_prefix="MEME50_", populate_by_name=True
    )
    vision_model: str = "gemini-3.8-flash"
    provider_policy: Literal["hkust-deepseek-v1"] = "hkust-deepseek-v1"
    vision_provider: Literal["gemini", "hkust"] = "hkust"
    deepseek_model: str = Field(
        default="deepseek-flash",
        validation_alias=AliasChoices("deepseek_model", "MEME50_DEEPSEEK_MODEL", "DEEPSEEK_MODEL"),
    )
    deepseek_api_key: SecretStr = Field(
        default_factory=lambda: SecretStr(""),
        repr=False,
        exclude=True,
        validation_alias=AliasChoices(
            "deepseek_api_key", "MEME50_DEEPSEEK_API_KEY", "DEEPSEEK_API_KEY"
        ),
    )
    hkust_model: str = "gemini-2.5-flash-lite"
    hkust_api_key: str = Field(
        default="",
        repr=False,
        exclude=True,
        validation_alias=AliasChoices("hkust_api_key", "MEME50_HKUST_API_KEY", "HKUST_API_KEY"),
    )
    gemini_api_key: str = Field(
        default="",
        repr=False,
        exclude=True,
        validation_alias=AliasChoices(
            "gemini_api_key", "MEME50_GEMINI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"
        ),
    )
    google_vision_api_key: str = Field(
        default="",
        repr=False,
        exclude=True,
        validation_alias=AliasChoices(
            "google_vision_api_key", "MEME50_GOOGLE_VISION_API_KEY", "GOOGLE_VISION_API_KEY"
        ),
    )
    brave_api_key: str = Field(
        default="",
        repr=False,
        exclude=True,
        validation_alias=AliasChoices("brave_api_key", "MEME50_BRAVE_API_KEY", "BRAVE_API_KEY"),
    )
    keyword_provider: Literal["deepseek"] = "deepseek"
    reverse_image_provider: Literal["disabled"] = "disabled"
    verify_entities: bool = True
    target_count: int = Field(default=50, ge=1, le=50)
    timeout_seconds: float = Field(default=180, gt=0, le=300)
    call_timeout_seconds: float = Field(default=18, gt=0, le=40)
    max_search_calls: int = Field(default=16, ge=1, le=16)
    max_model_calls: int = Field(default=3, ge=1, le=3)
    max_queries: int = Field(default=6, ge=1, le=6)
    max_sources: int = Field(default=500, ge=1, le=500)
    max_previews: int = Field(default=250, ge=0, le=250)
    max_originals: int = Field(default=120, ge=1, le=120)
    max_pages: int = Field(default=40, ge=0, le=40)
    max_bytes: int = Field(default=512 * 1024 * 1024, gt=0, le=512 * 1024 * 1024)
    max_redirects: int = Field(default=120, ge=0, le=120)
    max_disk_bytes: int = Field(default=512 * 1024 * 1024, gt=0, le=512 * 1024 * 1024)
    concurrency: int = Field(default=6, ge=1, le=6)
    dns_mode: Literal["system", "doh"] = "system"
    minimum_score: float = Field(default=0.55, ge=-1, le=1, allow_inf_nan=False)
    scoring_version: str = "meme50-rank-dev-v1-unvalidated"
    dedup_version: str = "meme50-temporal-local-v6"

    @property
    def effective_vision_model(self):
        return self.hkust_model if self.vision_provider == "hkust" else self.vision_model


class EntityHypothesis(BaseModel):
    name: str = Field(max_length=120)
    confidence: float = Field(ge=0, le=1)
    status: Literal["uncertain", "supported", "conflicting", "unknown"] = "uncertain"


class Query(BaseModel):
    text: str = Field(min_length=1, max_length=350)
    angle: str = Field(max_length=100)
    language: str = Field(default="en", max_length=20)


class VisualAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")
    observations: list[str] = Field(default_factory=list, max_length=12)
    ocr_text: str = Field(default="", max_length=2000)
    entity_hypotheses: list[EntityHypothesis] = Field(default_factory=list, max_length=8)
    emotion_tags: list[str] = Field(default_factory=list, max_length=12)
    action_tags: list[str] = Field(default_factory=list, max_length=12)
    user_text: str = Field(default="", max_length=500)
    evidence: list[dict] = Field(default_factory=list, max_length=20)
    queries: list[Query] = Field(default_factory=list, max_length=6)
    analysis_version: str = Field(default="unavailable", max_length=180)
    sampled_frames: list[dict] = Field(default_factory=list, max_length=4)
    ocr_provider: str = "unavailable"
    planner_version: str = "unavailable"


class MediaSource(Source):
    media_url: str | None = None
    preview_url: str | None = None
    source_type: str = "page"
    source_rank: int = Field(default=1, ge=1)
    channel: str = "keyword"
    recall_channels: list[str] = Field(default_factory=list)
    fusion_score: float = 0
    format_hint: str | None = None

    def checked(self):
        for url in [self.media_url, self.preview_url]:
            if url:
                Source.public_reference(url)
        return self


class PreparedMedia(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(pattern=r"^[a-f0-9]{64}$")
    relative_path: str
    preview_relative_path: str
    metadata: MediaMetadata
    source_url: str = Field(max_length=4096)
    media_url: str = Field(max_length=4096)
    provider: str = Field(max_length=50)
    score: float = Field(allow_inf_nan=False)
    content_group_id: str = Field(max_length=64)
    signals: dict = Field(default_factory=dict)

    def validate_paths(self):
        Candidate.relative_file(self.relative_path)
        Candidate.relative_file(self.preview_relative_path)
        Source.public_reference(self.source_url)
        Source.public_reference(self.media_url)
        if self.key != self.metadata.sha256:
            raise ValueError("Candidate key/SHA mismatch")
        return self


class RunnerEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    seq: int = Field(ge=1)
    type: Literal["stage", "analysis_ready", "candidate_ready", "progress", "final", "error"]
    payload: dict


class PipelineError(RuntimeError):
    def __init__(self, code, diagnostic=None):
        super().__init__(code)
        self.code = code
        self.diagnostic = diagnostic or {}


class Ledger:
    LIMIT_FIELDS = {
        "search_calls": "max_search_calls",
        "model_calls": "max_model_calls",
        "queries": "max_queries",
        "preview_attempts": "max_previews",
        "media_attempts": "max_originals",
        "page_attempts": "max_pages",
        "response_bytes": "max_bytes",
        "redirects": "max_redirects",
        "disk_bytes": "max_disk_bytes",
    }

    def __init__(self, settings, clock=time.monotonic):
        self.settings, self.clock = settings, clock
        self.started = clock()
        self.deadline = self.started + settings.timeout_seconds
        self.counts = {k: 0 for k in self.LIMIT_FIELDS}
        self.counts.update(dns_queries=0, connections=0, rerank_model_calls=0)
        self.reservations = {"response_bytes": 0, "redirects": 0}
        self.lock = Lock()
        self.trace = []

    def take(self, kind, amount=1):
        with self.lock:
            if self.clock() >= self.deadline:
                raise PipelineError("deadline")
            limit = (
                getattr(self.settings, self.LIMIT_FIELDS[kind])
                if kind in self.LIMIT_FIELDS
                else None
            )
            if (
                limit is not None
                and self.counts[kind] + self.reservations.get(kind, 0) + amount > limit
            ):
                raise PipelineError(kind + "_limit")
            self.counts[kind] += amount

    def note(self, step, **details):
        with self.lock:
            self.trace.append(
                dict(
                    step=step, elapsed_ms=int((self.clock() - self.started) * 1000), details=details
                )
            )

    def remaining(self):
        value = self.deadline - self.clock()
        if value <= 0:
            raise PipelineError("deadline")
        return min(value, self.settings.call_timeout_seconds)
