"""Typed, JSON-serializable contracts for Evidence-First review artifacts."""
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


SCHEMA_VERSION = "2.0"

InputRole = Literal["workpaper", "checkpoints", "attachments_preview"]
CaptureStatus = Literal["complete", "truncated"]
ArtifactStatus = Literal["running", "completed", "error"]


class InputFile(BaseModel):
    role: InputRole
    path: str
    filename: str
    sha256: str
    size: int
    media_type: str = (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


class CellEvidence(BaseModel):
    evidence_id: str
    sheet_name: str
    coordinate: str
    value: str | None
    formula: str | None
    data_type: str
    content_hash: str


class SheetEvidence(BaseModel):
    name: str
    normalized_name: str = ""
    sheet_hash: str
    max_row: int = 0
    max_column: int = 0
    layout_header_row: int | None = None
    standard_column: int | None = None
    execution_columns: list[int] = Field(default_factory=list)
    merged_ranges: list[str] = Field(default_factory=list)
    cells: list[CellEvidence] = Field(default_factory=list)


class EvidenceGraph(BaseModel):
    schema_version: str = SCHEMA_VERSION
    source_sha256: str
    sheets: list[SheetEvidence] = Field(default_factory=list)
    captured_cell_count: int
    omitted_cell_count: int
    capture_status: CaptureStatus


class ReviewManifest(BaseModel):
    schema_version: str = SCHEMA_VERSION
    review_id: str
    source: str
    requested_sheets: list[str] = Field(default_factory=list)
    inputs: list[InputFile] = Field(default_factory=list)
    engine_version: str = "stage-a-shadow"
    artifact_status: ArtifactStatus = "running"
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
