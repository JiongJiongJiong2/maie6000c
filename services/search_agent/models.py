"""Contracts shared by the agent, worker, and candidate-processing module."""

import ipaddress
import time
from pathlib import Path, PurePosixPath
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SearchBudget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    max_rounds: int = Field(default=2, ge=1, le=2)
    max_downloads: int = Field(default=6, ge=0, le=6)
    max_results: int = Field(default=3, ge=1, le=3)
    desired_candidates: int = Field(default=1, ge=1, le=3)
    timeout_seconds: float = Field(default=60, gt=0, le=300, allow_inf_nan=False)
    call_timeout_seconds: float = Field(default=12, gt=0, le=60, allow_inf_nan=False)


class CandidateBudget(BaseModel):
    model_config = ConfigDict(frozen=True)
    remaining_downloads: int = Field(ge=0)
    deadline: float

    def remaining_seconds(self) -> float:
        return max(0, self.deadline - time.monotonic())


class Source(BaseModel):
    model_config = ConfigDict(extra="ignore")
    title: str = Field(default="", max_length=500)
    source_url: str = Field(max_length=4096)
    image_url: str | None = Field(default=None, max_length=4096)
    snippet: str = Field(default="", max_length=2000)
    provider: str = Field(max_length=50)

    @field_validator("source_url", "image_url")
    @classmethod
    def public_reference(cls, value):
        if value is None:
            return value
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower()
        if (
            parsed.scheme not in {"https", "http"}
            or not host
            or parsed.username
            or parsed.password
            or host == "localhost"
            or "." not in host
            or host.endswith((".local", ".internal"))
        ):
            raise ValueError("Not a public HTTP reference")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            if not address.is_global:
                raise ValueError("Not a public address")
        return value


class Candidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    relative_path: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_url: str
    image_url: str
    provider: str
    format: Literal["GIF"]
    frame_count: int = Field(gt=1)
    score: float = Field(allow_inf_nan=False)

    @field_validator("relative_path")
    @classmethod
    def relative_file(cls, value):
        path = PurePosixPath(value)
        if not value or path.is_absolute() or ".." in path.parts or "\\" in value or ":" in value:
            raise ValueError("Candidate must use a relative path")
        return value

    def contained_file(self, work_dir: Path) -> Path:
        path = (work_dir / self.relative_path).resolve()
        if not path.is_relative_to(work_dir.resolve()) or not path.is_file():
            raise ValueError("Candidate file is missing or outside work directory")
        return path


class PreparedBatch(BaseModel):
    candidates: list[Candidate] = Field(default_factory=list)
    # Codes only: external pages and free-form instructions are never planner feedback.
    failures: list[
        Literal[
            "static_image",
            "not_gif",
            "invalid_media",
            "unsupported_source",
            "download_failed",
            "download_timeout",
            "source_unavailable",
            "model_unavailable",
            "embedding_failed",
            "storage_failed",
        ]
    ] = Field(default_factory=list)
    diagnostics: list[dict] = Field(default_factory=list)
    redirects: int = Field(default=0, ge=0)
    rejected_low_score: int = Field(default=0, ge=0)
    downloads_used: int = Field(ge=0)
    model_version: str = Field(default="unspecified", min_length=1, max_length=100)


class TraceEvent(BaseModel):
    round: int
    step: str
    elapsed_ms: int
    details: dict = Field(default_factory=dict)


class SearchResult(BaseModel):
    status: Literal["completed", "failed"]
    result_kind: Literal["sources", "candidates", "no_results"]
    stop_reason: str
    sources: list[Source] = Field(default_factory=list)
    candidates: list[Candidate] = Field(default_factory=list)
    trace: list[TraceEvent] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    search_calls: int = 0
    planner_calls: int = 0
    downloads_used: int = 0
    model_version: str | None = None
    agent_version: str = "web-search-v1"

    @model_validator(mode="after")
    def result_contract(self):
        if self.status == "failed" and self.candidates:
            raise ValueError("Failed result cannot contain candidates")
        if bool(self.candidates) != (self.result_kind == "candidates"):
            raise ValueError("Candidate result kind must match candidates")
        return self
