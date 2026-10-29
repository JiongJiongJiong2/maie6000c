from __future__ import annotations

import math
from typing import Literal
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


class SearchError(BaseModel):
    code: str
    message: str


class SearchRead(AcceptedSearch):
    result_kind: Literal["candidates", "no_candidates"] | None
    candidates: list[CandidateRead]
    error: SearchError | None


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
