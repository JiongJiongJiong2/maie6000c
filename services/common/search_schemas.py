from __future__ import annotations

import math
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class AcceptedSearch(BaseModel):
    request_id: UUID
    job_id: UUID
    status: Literal["pending", "running", "completed", "failed"]


class CandidateRead(BaseModel):
    candidate_id: UUID
    rank: int
    score: float
    media_url: str
    source_url: str | None = None
    image_url: str | None = None
    provider: str | None = None
    save_status: Literal["not_saved", "saved"] = "not_saved"
    asset_id: UUID | None = None
    index_status: Literal["pending", "running", "ready", "failed"] | None = None


class SearchError(BaseModel):
    code: str
    message: str


class SearchJobRead(BaseModel):
    job_id: UUID
    job_kind: Literal["local", "web"]
    status: Literal["pending", "running", "completed", "failed"]
    stage: str
    description: str | None
    result_kind: Literal["candidates", "no_candidates"] | None
    error: SearchError | None


class SearchRead(BaseModel):
    request_id: UUID
    job_id: UUID
    status: Literal["pending", "running", "completed", "failed"]
    job_kind: Literal["local", "web"]
    stage: str
    local_job_id: UUID
    web_searches: list[SearchJobRead]
    result_kind: Literal["candidates", "no_candidates"] | None
    candidates: list[CandidateRead]
    error: SearchError | None


class WebSearchCreate(BaseModel):
    description: str = Field(min_length=1, max_length=500)
    client_search_key: str = Field(min_length=1, max_length=128, pattern=r"^\S+$")

    @model_validator(mode="after")
    def normalize_description(self) -> WebSearchCreate:
        self.description = self.description.strip()
        if not self.description:
            raise ValueError("description must not be blank")
        return self


class SavedAssetRead(BaseModel):
    asset_id: UUID
    save_status: Literal["saved"]
    media_url: str
    index_status: Literal["pending", "running", "ready", "failed"]
    index_error: str | None = None


class SaveCreate(BaseModel):
    client_save_key: str = Field(min_length=1, max_length=128, pattern=r"^\S+$")


class WebCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relative_path: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_url: str = Field(min_length=1, max_length=4096)
    image_url: str = Field(min_length=1, max_length=4096)
    provider: str = Field(min_length=1, max_length=50)
    format: Literal["GIF"]
    frame_count: int = Field(gt=1)
    score: float = Field(allow_inf_nan=False)


class WebSearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["completed", "failed"]
    result_kind: Literal["sources", "candidates", "no_results"]
    stop_reason: str = Field(min_length=1, max_length=100)
    candidates: list[WebCandidate] = Field(default_factory=list, max_length=3)
    trace: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    search_calls: int = Field(ge=0, le=2)
    planner_calls: int = Field(ge=0, le=2)
    downloads_used: int = Field(ge=0, le=6)
    model_version: str | None = Field(default=None, max_length=100)
    agent_version: str = Field(default="web-search-v1", max_length=100)

    @model_validator(mode="after")
    def validate_result(self) -> WebSearchResult:
        if self.result_kind == "candidates" and not self.candidates:
            raise ValueError("candidate result must contain candidates")
        if self.result_kind != "candidates" and self.candidates:
            raise ValueError("only candidate results may contain candidates")
        if self.status == "failed" and self.result_kind == "candidates":
            raise ValueError("failed searches cannot expose candidates as a completed result")
        return self


class ReviewCreate(BaseModel):
    decision: Literal["accept", "reject_all"]
    candidate_id: UUID | None = None
    client_review_key: str = Field(min_length=1, max_length=128, pattern=r"^\S+$")

    @model_validator(mode="after")
    def validate_candidate(self) -> ReviewCreate:
        if (self.decision == "accept") != (self.candidate_id is not None):
            raise ValueError("accept requires candidate_id; reject_all requires null")
        return self


class ReviewRead(BaseModel):
    review_id: UUID


class RetryCreate(BaseModel):
    client_retry_key: str = Field(min_length=1, max_length=128, pattern=r"^\S+$")


class RetrievalMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reference_asset_id: UUID
    score: float

    @field_validator("score")
    @classmethod
    def finite_score(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("score must be finite")
        return value


class RetrievalResult(BaseModel):
    matches: list[RetrievalMatch] = Field(max_length=3)
    model_version: str = Field(min_length=1, max_length=100)
    corpus_version: str = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_ranking(self) -> RetrievalResult:
        ids = [match.reference_asset_id for match in self.matches]
        if len(set(ids)) != len(ids):
            raise ValueError("matches must contain distinct assets")
        scores = [match.score for match in self.matches]
        if scores != sorted(scores, reverse=True):
            raise ValueError("matches must be sorted by descending score")
        return self
