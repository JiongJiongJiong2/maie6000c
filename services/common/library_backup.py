"""Portable, versioned original GIF manifests."""

from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from services.common.library_metadata import Annotation, MetadataEdit

MAX_BACKUP_ITEMS = 60
MAX_BACKUP_BYTES = 256 * 1024 * 1024
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class BackupSource(BaseModel):
    provider: str = Field(min_length=1, max_length=50)
    source_url: str = Field(max_length=4096)
    image_url: str = Field(max_length=4096)

    @field_validator("source_url", "image_url")
    @classmethod
    def safe_url(cls, value):
        if not value:
            return value
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Only HTTP source URLs can be restored")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("Source URLs must not contain credentials")
        return value


class BackupFrame(BaseModel):
    frame_index: int = Field(ge=0, lt=1000)
    time_ms: int = Field(ge=0)


class BackupAnnotation(Annotation):
    version: str = Field(min_length=1, max_length=200)
    sha256: Digest
    sampled_frames: list[BackupFrame] = Field(min_length=1, max_length=4)


class BackupEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sha256: Digest
    path: str = Field(max_length=80)
    byte_size: int = Field(gt=0, le=MAX_BACKUP_BYTES)
    frame_count: int = Field(ge=2, le=1000)
    title: str = Field(min_length=1, max_length=200)
    source: BackupSource | None = None
    manual: MetadataEdit | None = None
    annotation: BackupAnnotation | None = None

    @model_validator(mode="after")
    def check_identity(self):
        if self.path != f"assets/{self.sha256}.gif":
            raise ValueError("Invalid GIF archive path")
        if self.annotation is not None and (
            self.annotation.sha256 != self.sha256
            or any(
                frame.frame_index >= self.frame_count for frame in self.annotation.sampled_frames
            )
        ):
            raise ValueError("Annotation does not match its GIF")
        return self


class BackupManifest(BaseModel):
    version: Literal[1]
    profile: Literal["original_zip"]
    assets: list[BackupEntry] = Field(min_length=1, max_length=MAX_BACKUP_ITEMS)

    @model_validator(mode="after")
    def check_assets(self):
        if len({asset.sha256 for asset in self.assets}) != len(self.assets):
            raise ValueError("Backup includes a GIF more than once")
        return self
