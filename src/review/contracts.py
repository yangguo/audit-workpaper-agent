"""Typed, JSON-serializable contracts for Evidence-First review artifacts."""
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, model_validator


SCHEMA_VERSION = "2.0"

InputRole = Literal["workpaper", "checkpoints", "attachments_dir", "attachments_preview"]
CaptureStatus = Literal["complete", "truncated"]
ArtifactStatus = Literal["running", "completed", "error"]

# Additive quality metadata used by the legacy V1 finding projection. These
# aliases live beside the Evidence-First contracts so API/artifact consumers
# can share the vocabulary without changing the V1 finding shape.
CitationValidationStatus = Literal[
    "verified", "partial", "invalid", "not_available"
]
QualityGateStatus = Literal["passed", "flagged", "not_run", "error"]
ClaimSupportStatus = Literal[
    "supported", "partial", "unsupported", "not_required", "error"
]
ConsistencyStatus = Literal["consistent", "conflicted", "not_comparable"]


class InputFile(BaseModel):
    role: InputRole
    path: str
    filename: str
    sha256: str
    size: int
    media_type: str = (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


class PolicyPackRef(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    version: str = Field(min_length=5, max_length=40)


class RuntimeConfigSnapshot(BaseModel):
    """Non-secret runtime choices that affect a review execution."""

    review_model: str = ""
    review_endpoint_sha256: str = ""
    review_temperature: float = 0.1
    review_json_mode: bool = True
    verify_ssl: bool = True
    quality_mode: Literal["off", "shadow", "on"] = "shadow"
    deterministic_crosscheck_mode: Literal["all_findings", "p0_only", "off"] = (
        "all_findings"
    )
    evidence_agent_mode: str = "fallback"
    evidence_snapshot_max_cells: int = Field(default=50_000, ge=1)
    challenger_full_text: bool = True
    mineru_ocr_mode: str = "off"
    mineru_ocr_language: str = "ch"
    mineru_model_version: str = "vlm"
    policy_mode: Literal["shadow", "off"] = "shadow"
    judgement_mode: Literal["shadow", "off"] = "off"
    judgement_max_requests: int = Field(default=200, ge=1)
    prompt_bundle_version: str = "review-prompts/1"


class ExecutionComponentRef(BaseModel):
    """Identity of a reviewed code/configuration component without its path."""

    component_id: str = Field(min_length=1, max_length=120)
    version: str = Field(min_length=1, max_length=80)
    sha256: str = Field(min_length=1, max_length=128)


class EvidenceFact(BaseModel):
    """Minimal immutable identity for a source available to a review."""

    fact_id: str = Field(min_length=1, max_length=256)
    fact_type: Literal["cell", "attachment"]
    source_ref: str = Field(min_length=1, max_length=1_000)
    source_sha256: str = Field(default="", max_length=128)
    content_hash: str = Field(default="", max_length=128)
    sheet_scope: list[str] = Field(default_factory=list, max_length=200)
    extraction_status: str = Field(default="unknown", max_length=80)
    # Directory sources are frozen files; previews only declare that an
    # attachment was received and cannot prove the file/content assertion.
    source_type: Literal["workpaper", "directory", "preview", "unknown"] = (
        "unknown"
    )


class ClaimSupport(BaseModel):
    """Whether verified sources support one controlled finding claim."""

    status: ClaimSupportStatus = "not_required"
    assertion_id: str = ""
    claim_type: str = ""
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    missing_requirements: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)


class QualityDisposition(BaseModel):
    """Audit record of any shadow/on quality decision."""

    original_status: str = ""
    effective_status: str = ""
    original_severity: str = ""
    reason_codes: list[str] = Field(default_factory=list)


class FindingConflict(BaseModel):
    conflict_id: str = Field(min_length=1, max_length=128)
    conflict_type: Literal[
        "exclusive_claim_values", "status_disagreement", "support_contradiction"
    ]
    finding_ids: list[str] = Field(default_factory=list, min_length=2)
    assertion_id: str = ""
    claim_subject: str = ""
    values: list[str] = Field(default_factory=list)


class FindingConsistency(BaseModel):
    status: ConsistencyStatus = "not_comparable"
    conflict_ids: list[str] = Field(default_factory=list)
    related_finding_ids: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)


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

    @model_validator(mode="after")
    def _validate_capture_counts(self) -> "EvidenceGraph":
        actual_captured = sum(len(sheet.cells) for sheet in self.sheets)
        if self.captured_cell_count != actual_captured:
            raise ValueError(
                "captured_cell_count must equal the number of retained cells"
            )
        if self.omitted_cell_count < 0:
            raise ValueError("omitted_cell_count must not be negative")
        if self.capture_status == "complete" and self.omitted_cell_count:
            raise ValueError(
                "capture_status must be truncated when cells are omitted"
            )
        if self.capture_status == "truncated" and not self.omitted_cell_count:
            raise ValueError(
                "capture_status must be complete when no cells are omitted"
            )
        return self


class ReviewManifest(BaseModel):
    schema_version: str = SCHEMA_VERSION
    review_id: str
    source: str
    requested_sheets: list[str] = Field(default_factory=list)
    inputs: list[InputFile] = Field(default_factory=list)
    policy_pack: PolicyPackRef | None = None
    judgement_policy_pack: PolicyPackRef | None = None
    engine_version: str = "stage-a-shadow"
    # These fields are additive so stored Stage-A manifests remain readable.
    # ``input_sha256`` remains available from the workpaper InputFile for
    # legacy consumers; the two hashes below identify the full execution.
    input_set_sha256: str = ""
    execution_sha256: str = ""
    runtime_config: RuntimeConfigSnapshot | None = None
    components: list[ExecutionComponentRef] = Field(default_factory=list)
    artifact_status: ArtifactStatus = "running"
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
