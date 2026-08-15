from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.project import ProjectStatus


class EvidenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvidenceSourceTrust(str, Enum):
    official = "official"
    public_domain = "public_domain"
    licensed = "licensed"
    user_provided = "user_provided"
    approved = "approved"


class EvidenceSourceKind(str, Enum):
    pdf = "pdf"
    image = "image"
    webpage = "webpage"
    wikimedia = "wikimedia"


class EvidenceBBox(EvidenceModel):
    x: float
    y: float
    width: float
    height: float

    @model_validator(mode="after")
    def validate_box_bounds(self) -> EvidenceBBox:
        if not (0.0 <= self.x <= 1.0):
            raise ValueError(f"x must be within [0.0, 1.0], got {self.x}")
        if not (0.0 <= self.y <= 1.0):
            raise ValueError(f"y must be within [0.0, 1.0], got {self.y}")
        if not (0.0 < self.width <= 1.0):
            raise ValueError(f"width must be within (0.0, 1.0], got {self.width}")
        if not (0.0 < self.height <= 1.0):
            raise ValueError(f"height must be within (0.0, 1.0], got {self.height}")
        if self.x + self.width > 1.0001:
            raise ValueError(f"x + width must be <= 1.0, got {self.x + self.width}")
        if self.y + self.height > 1.0001:
            raise ValueError(f"y + height must be <= 1.0, got {self.y + self.height}")
        return self


class EvidenceSource(EvidenceModel):
    id: str
    kind: EvidenceSourceKind
    url: str | None = None
    local_file: str | None = None
    title: str
    publisher: str | None = None
    trust: EvidenceSourceTrust
    license: str | None = None
    tags: list[str] = Field(default_factory=list)
    allowed_for_evidence: bool = True
    page_hint: int | None = None
    quote_hint: str | None = None
    bbox_hint: EvidenceBBox | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id", "title")
    @classmethod
    def validate_non_empty_strings(cls, value: str) -> str:
        value = " ".join(value.split()).strip()
        if not value:
            raise ValueError("field must not be empty")
        return value

    @field_validator("page_hint")
    @classmethod
    def validate_page_hint(cls, value: int | None) -> int | None:
        if value is not None and value < 1:
            raise ValueError("page_hint must be >= 1")
        return value

    @model_validator(mode="after")
    def validate_location(self) -> EvidenceSource:
        has_url = bool(self.url and self.url.strip())
        has_local = bool(self.local_file and self.local_file.strip())

        if self.kind in (EvidenceSourceKind.pdf, EvidenceSourceKind.image, EvidenceSourceKind.webpage):
            if not has_url and not has_local:
                raise ValueError(f"Source {self.id} of kind {self.kind} must specify either 'url' or 'local_file'")
        elif self.kind == EvidenceSourceKind.wikimedia:
            # Wikimedia can have a direct URL, local_file, or title/query in metadata/title
            if not has_url and not has_local and not self.title:
                raise ValueError(f"Wikimedia source {self.id} must specify 'url', 'local_file', or 'title'")

        return self


class EvidenceSourceRegistry(EvidenceModel):
    schema_version: Literal["1.0"] = "1.0"
    sources: list[EvidenceSource] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_source_ids(self) -> EvidenceSourceRegistry:
        ids = [s.id for s in self.sources]
        if len(ids) != len(set(ids)):
            duplicates = [sid for sid in ids if ids.count(sid) > 1]
            raise ValueError(f"Duplicate source IDs found in registry: {set(duplicates)}")
        return self


class EvidenceCandidate(EvidenceModel):
    id: str
    source_id: str
    kind: EvidenceSourceKind
    title: str
    publisher: str | None = None
    trust: EvidenceSourceTrust
    license: str | None = None
    source_url: str | None = None
    local_file: str | None = None
    query: str
    page_number: int | None = None
    page_count: int | None = None
    matched_text: str | None = None
    match_type: Literal["exact_target", "exact_quote_hint", "query_relevance", "page_hint", "none"] = "none"
    highlight_boxes: list[EvidenceBBox] = Field(default_factory=list)
    width: int | None = None
    height: int | None = None
    score: float = 0.0
    score_breakdown: dict[str, float] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SelectedEvidenceAsset(EvidenceModel):
    scene_id: str
    source_id: str
    source_kind: str
    title: str
    publisher: str | None = None
    trust: str
    source_url: str | None = None
    local_source_file: str | None = None
    source_sha256: str | None = None
    page_number: int | None = None
    matched_text: str | None = None
    match_type: str
    highlight_boxes: list[dict[str, float]] = Field(default_factory=list)
    score: float
    score_breakdown: dict[str, float] = Field(default_factory=dict)
    render_mode: str = "document_page"
    source_file: str | None = None
    page_image_file: str | None = None
    annotated_image_file: str | None = None
    rendered_file: str
    license: str | None = None
    spec_fingerprint: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvidenceManifest(EvidenceModel):
    schema_version: Literal["1.0"] = "1.0"
    project_title: str
    task_id: str
    status: ProjectStatus
    assets: list[SelectedEvidenceAsset] = Field(default_factory=list)
    failed_scenes: list[dict[str, Any]] = Field(default_factory=list)
    skipped_scenes: list[dict[str, Any]] = Field(default_factory=list)
    source_registry_file: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    error: str | None = None
